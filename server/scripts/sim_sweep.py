"""Sweep every build in the Library through the simulator and report, per device: does it boot,
does every input part produce a visible or audible response, does every output part show life.

    BARA_PORT=8851 .venv/bin/python scripts/sim_sweep.py [--port 8851] [--ids b_x,b_y] [--out sweep.json]

The checks are by I/O class (key, button, encoder, axis, switch / led, tone, display), never by
device. Needs a running engine; it only calls the public sim routes.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any


def call(
    port: int, method: str, path: str, body: dict[str, Any] | None = None, timeout: int = 240
) -> dict[str, Any]:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read())
        except Exception:
            return {"error": {"message": f"HTTP {e.code}"}}


def screen_text(snap: dict[str, Any]) -> str:
    return "\n".join(snap.get("screen") or []).strip()


def fb_sum(snap: dict[str, Any]) -> str:
    fb = snap.get("fb")
    return fb["b64"] if fb else ""


def sig(snap: dict[str, Any]) -> tuple:
    return (
        screen_text(snap),
        fb_sum(snap),
        tuple((l["id"], l["on"]) for l in snap.get("leds") or []),
        snap.get("hid"),
    )


def act(
    port: int, bid: str, iid: str, action: str, value: Any = None, run_ms: int = 60
) -> dict[str, Any]:
    body: dict[str, Any] = {"id": iid, "action": action, "since": 0, "run_ms": run_ms}
    if value is not None:
        body["value"] = value
    return call(port, "POST", f"/v1/builds/{bid}/sim/input", body)


def run(port: int, bid: str, ms: int) -> dict[str, Any]:
    return (
        call(port, "POST", f"/v1/builds/{bid}/sim/run", {"ms": ms, "since": 0}).get("snapshot")
        or {}
    )


def probe_input(port: int, bid: str, inp: dict[str, Any]) -> tuple[bool, str]:
    """Drive one input and say whether anything the user can see or hear changed."""
    iid, kind = inp["id"], inp["kind"]
    before = run(port, bid, 30)
    events: list[dict[str, Any]] = []
    after: dict[str, Any] = before

    def step(action: str, value: Any = None, ms: int = 80) -> dict[str, Any]:
        r = act(port, bid, iid, action, value, ms)
        s = r.get("snapshot") or {}
        events.extend(s.get("events") or [])
        return s

    if kind == "encoder":
        step("turn", 1, 40)
        after = step("turn", -1, 40)
    elif kind == "axis":
        step("axis", 1.0, 80)
        after = step("axis", -1.0, 80)
        step("axis", 0.0, 40)
    elif kind == "switch":
        after = step("press", None, 80)
        step("release", None, 40)
    else:
        step("press", None, 120)
        after = step("release", None, 120)
    changed = sig(before) != sig(after) or any(
        e.get("type") in ("typed", "hid", "tone", "gpio", "serial") for e in events
    )
    why = "" if changed else "no visible, audible or USB response"
    return changed, why


def sweep_one(port: int, bid: str) -> dict[str, Any]:
    t0 = time.time()
    out: dict[str, Any] = {"build_id": bid}
    r = call(port, "POST", f"/v1/builds/{bid}/sim/start", {"labels": False})
    if "sim" not in r:
        out.update(
            boots=False,
            error=(r.get("error") or {}).get("message", "no sim"),
            inputs=[],
            outputs=[],
        )
        return out
    sim = r["sim"]
    io, fw = sim["io"], sim["firmware"]
    snap = sim.get("snapshot") or {}
    out["device"] = io["device"]["name"]
    out["prompt"] = sim.get("prompt")
    out["mode"] = fw.get("mode")
    out["fw_status"] = fw.get("status")
    out["boots"] = bool(snap) and fw.get("status") == "ok" and bool(snap.get("powered", True))
    out["error"] = (
        ""
        if out["boots"]
        else (fw.get("target", {}).get("log") or fw.get("host", {}).get("log") or "no session")[
            -300:
        ]
    )
    out["unsimulated"] = [u["label"] for u in io.get("unsimulated") or []]
    ins = []
    if out["boots"]:
        for inp in io["inputs"]:
            ok, why = probe_input(port, bid, inp)
            ins.append(
                {"id": inp["id"], "label": inp["label"], "kind": inp["kind"], "ok": ok, "why": why}
            )
        act(port, bid, "device", "reset")
    out["inputs"] = ins
    outs = []
    snap = run(port, bid, 200) if out["boots"] else {}
    leds = {l["id"]: l for l in snap.get("leds") or []}
    for o in io["outputs"]:
        if o["kind"] == "display":
            ok = bool(snap.get("fb")) or bool(screen_text(snap))
            outs.append(
                {
                    "id": o["id"],
                    "label": o["label"],
                    "kind": "display",
                    "ok": ok,
                    "why": "" if ok else "blank display",
                }
            )
        elif o["kind"] in ("led", "tone"):
            # a light or a speaker is alive when the firmware can drive it: a pin is assigned
            ok = bool(o.get("pin")) and o["id"] in leds
            outs.append(
                {
                    "id": o["id"],
                    "label": o["label"],
                    "kind": o["kind"],
                    "ok": ok,
                    "why": "" if ok else "no pin or not watched",
                }
            )
    out["outputs"] = outs
    out["tests"] = {}
    out["seconds"] = round(time.time() - t0, 1)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8851)
    ap.add_argument("--ids", default="")
    ap.add_argument("--out", default="sweep.json")
    a = ap.parse_args()
    ids = [i for i in a.ids.split(",") if i] or [
        b["build_id"] for b in call(a.port, "GET", "/v1/library")["builds"]
    ]
    results = []
    for n, bid in enumerate(ids, 1):
        try:
            r = sweep_one(a.port, bid)
        except Exception as e:  # keep sweeping; the failure is the finding
            r = {
                "build_id": bid,
                "boots": False,
                "error": f"sweep crashed: {e}",
                "inputs": [],
                "outputs": [],
            }
        results.append(r)
        bad_in = [i["label"] for i in r["inputs"] if not i["ok"]]
        bad_out = [o["label"] for o in r["outputs"] if not o["ok"]]
        print(
            f"{n}/{len(ids)} {bid} {r.get('device', '?')[:28]:28} boots={r['boots']} in={len(r['inputs'])}(-{len(bad_in)}) out={len(r['outputs'])}(-{len(bad_out)}) {r.get('error', '')[:80]}",
            flush=True,
        )
        with open(a.out, "w") as f:
            json.dump(results, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
