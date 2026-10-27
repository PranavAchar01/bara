"""The fit agent: look at a photo, decide, and propose the next build action.

Perception runs the OpenCV measurement (on AWS Lambda when BARA_VISION_URL is set, locally
otherwise). The agent reads what came back and picks what happens next:

- no marker found: retry once with contrast enhancement, then ask for a retake with a reason
- unsure segmentation: ask for a specific retake (step back, clear the desk) instead of guessing
- a clean footprint and no build yet: propose starting the build with the measured size as a
  hard constraint
- a clean footprint and an open build: compare the case to the space; if it does not fit,
  propose the edit that would make it fit (a shrink request, or a direct height resize)

Every proposal needs the person's click before it touches the build. The full trace of tool
calls and decisions comes back with the answer so the UI can show its reasoning.
"""

from __future__ import annotations

import base64
import os
import time
from typing import Any

import httpx

from bara.vision import measure as m

RETAKE_TIPS = {
    "no_marker": "I can't find the printed marker. Lay it flat next to the object, fully in frame.",
    "cut_off": "The object runs off the edge of the photo. Step back so all of it is in frame.",
    "whole_frame": "The object fills the whole photo. Step back so some desk shows around it.",
    "two_objects": "I see two things of similar size. Clear the desk so only one is there.",
    "ragged": "The outline is ragged, maybe a shadow. Try softer light or a plainer surface.",
    "no_object": "I can see the marker but nothing else. Put the object on a plain surface.",
}


def _remote_url() -> str | None:
    url = os.environ.get("BARA_VISION_URL", "").strip()
    return url or None


def run_measure(data: bytes, marker_mm: float, enhance: bool) -> dict[str, Any]:
    """The perception tool. Uses the AWS Lambda endpoint when configured, else runs in process."""
    url = _remote_url()
    t0 = time.perf_counter()
    if url:
        if len(data) > 3 * 1024 * 1024:
            # Lambda function URLs cap the payload; the measurement downsizes to 1600 px anyway
            ok, jpg = m.cv2.imencode(".jpg", m._decode(data), [m.cv2.IMWRITE_JPEG_QUALITY, 90])
            if ok:
                data = jpg.tobytes()
        try:
            resp = httpx.post(
                url,
                json={
                    "image_b64": base64.b64encode(data).decode("ascii"),
                    "marker_mm": marker_mm,
                    "enhance": enhance,
                },
                timeout=30.0,
            )
            resp.raise_for_status()
            out = resp.json()
            out["where"] = "aws-lambda"
            out["round_trip_ms"] = round((time.perf_counter() - t0) * 1e3, 1)
            return out
        except (httpx.HTTPError, ValueError) as err:
            out = m.measure(data, marker_mm=marker_mm, enhance=enhance)
            out["where"] = "local"
            out["remote_error"] = f"{type(err).__name__}: {err}"[:200]
            return out
    out = m.measure(data, marker_mm=marker_mm, enhance=enhance)
    out["where"] = "local"
    out["round_trip_ms"] = round((time.perf_counter() - t0) * 1e3, 1)
    return out


def _fits(case_xy: tuple[float, float], space_xy: tuple[float, float]) -> tuple[bool, float]:
    """Does a case footprint fit a space, either way round? Returns (fits, spare mm on the
    tighter side; negative means how much it is over)."""
    a = sorted(case_xy, reverse=True)
    b = sorted(space_xy, reverse=True)
    spare = min(b[0] - a[0], b[1] - a[1])
    return spare >= 0, round(spare, 1)


def _strip(meas: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in meas.items() if k != "annotated_jpg_b64"}


def decide(
    data: bytes,
    *,
    mode: str = "fit_inside",
    marker_mm: float = 40.0,
    clearance_mm: float = 2.0,
    height_limit_mm: float | None = None,
    device: str = "",
    enclosure: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Perceive, decide, propose. `enclosure` is the open build's case, if there is one."""
    steps: list[dict[str, Any]] = []

    meas = run_measure(data, marker_mm, enhance=False)
    steps.append(
        {
            "tool": "measure",
            "args": {"enhance": False},
            "status": meas["status"],
            "where": meas.get("where"),
            "ms": meas.get("ms"),
        }
    )
    if meas["status"] in ("no_marker", "unsure", "no_object"):
        # adjust and look again before bothering the person
        retry = run_measure(data, marker_mm, enhance=True)
        steps.append(
            {
                "tool": "measure",
                "args": {"enhance": True},
                "status": retry["status"],
                "where": retry.get("where"),
                "ms": retry.get("ms"),
                "why": f"first pass was {meas['status']}, retrying with contrast boost",
            }
        )
        if retry["status"] == "ok" or (
            meas["status"] == "no_marker" and retry["status"] != "no_marker"
        ):
            meas = retry

    out: dict[str, Any] = {
        "measurement": _strip(meas),
        "annotated_jpg_b64": meas.get("annotated_jpg_b64", ""),
        "steps": steps,
    }

    if meas["status"] != "ok":
        if meas["status"] == "unsure":
            issues = [t["issues"] for t in meas["tried"] if t["issues"]]
            first = issues[0][0] if issues and issues[0] else "ragged"
        else:
            first = meas["status"]
        tip = RETAKE_TIPS.get(first, RETAKE_TIPS["ragged"])
        steps.append({"decide": "ask_retake", "reason": first})
        out["action"] = {"kind": "retake", "label": "Retake photo", "needs_approval": False}
        out["message"] = tip
        return out

    obj = meas["object"]
    w, d = obj["width_mm"], obj["depth_mm"]
    room = (round(w - 2 * clearance_mm, 1), round(d - 2 * clearance_mm, 1))
    if mode == "match":
        target = (w, d)
        shape = {"round": "round", "oval": "oval"}.get(obj["kind"], "rectangular")
        constraint = (
            f"Make the case a {shape} footprint of {target[0]:g} x {target[1]:g} mm, "
            f"matching an object I measured from a photo."
        )
    else:
        target = room
        constraint = (
            f"It has to fit in a {w:g} x {d:g} mm space I measured from a photo, so keep "
            f"the case footprint within {room[0]:g} x {room[1]:g} mm"
            + (f" and under {height_limit_mm:g} mm tall." if height_limit_mm else ".")
        )

    if enclosure is None:
        prompt = f"{device.strip().rstrip('.')}. {constraint}" if device.strip() else constraint
        steps.append({"decide": "start_build", "target_mm": list(target)})
        out["action"] = {
            "kind": "build",
            "label": "Build with this size",
            "prompt": prompt,
            "needs_approval": True,
        }
        out["message"] = f"Measured {w:g} x {d:g} mm ({obj['kind']}). " + (
            "I'll size the case to match it."
            if mode == "match"
            else f"With {clearance_mm:g} mm clearance the case gets {room[0]:g} x {room[1]:g} mm."
        )
        return out

    size = enclosure.get("outer_size_mm") or [0, 0, 0]
    case_xy = (float(size[0]), float(size[1]))
    ok, spare = _fits(case_xy, target)
    check: dict[str, Any] = {
        "case_mm": [round(v, 1) for v in size],
        "space_mm": list(target),
        "footprint_fits": ok,
        "spare_mm": spare,
    }
    tall = bool(height_limit_mm) and float(size[2]) > float(height_limit_mm or 0)
    check["height_fits"] = not tall
    out["fit"] = check
    steps.append({"tool": "fit_check", **check})

    if ok and not tall:
        steps.append({"decide": "report_fit"})
        out["action"] = {"kind": "none", "label": "It fits", "needs_approval": False}
        out["message"] = (
            f"The case is {case_xy[0]:.0f} x {case_xy[1]:.0f} mm and the space allows "
            f"{target[0]:g} x {target[1]:g} mm. It fits with {spare:g} mm to spare."
        )
        return out
    if ok and tall:
        steps.append({"decide": "resize_height", "to_mm": height_limit_mm})
        out["action"] = {
            "kind": "edit",
            "label": f"Set case height to {height_limit_mm:g} mm",
            "ops": [
                {
                    "op": "resize",
                    "target": {"enclosure_id": enclosure.get("enclosure_id")},
                    "params": {"height_mm": height_limit_mm},
                }
            ],
            "needs_approval": True,
        }
        out["message"] = (
            f"The footprint fits, but the case is {size[2]:.0f} mm tall and the space allows "
            f"{height_limit_mm:g} mm."
        )
        return out
    steps.append({"decide": "propose_shrink", "over_mm": -spare})
    out["action"] = {
        "kind": "prompt",
        "label": "Shrink to fit",
        "prompt": (
            f"Make the case smaller so its footprint is at most {target[0]:g} x {target[1]:g} mm. "
            "Pack the parts closer together or pick smaller ones if needed."
        ),
        "needs_approval": True,
    }
    out["message"] = (
        f"The case is {case_xy[0]:.0f} x {case_xy[1]:.0f} mm but the space allows "
        f"{target[0]:g} x {target[1]:g} mm: {-spare:g} mm too big on the tight side."
    )
    return out
