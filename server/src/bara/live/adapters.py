"""Adapters to the BOARD (KiCad) and GEOMETRY (case) packages.

Both are imported lazily: when a package or a tool it needs is missing, the caller gets
None plus the reason, and the stage reports degraded instead of inventing a result.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Callable
from functools import lru_cache
from typing import Any

from bara.live.layout import PITCH_MM

log = logging.getLogger(__name__)

Progress = Callable[[str, float | None], None]


# ---- BOARD ------------------------------------------------------------------------------
def board_module() -> tuple[Any | None, str | None]:
    try:
        import bara.board as board  # type: ignore[import-not-found]
    except Exception as exc:  # missing package or a broken import: report, do not guess
        return None, f"board package unavailable ({type(exc).__name__})"
    if not hasattr(board, "build_board"):
        return None, "bara.board.build_board is not available yet"
    return board, None


@lru_cache(maxsize=1)
def board_controllers() -> dict[str, int]:
    """Registry controller id -> GPIO on the module's edge rows (from its KiCad symbol)."""
    try:
        from bara.board import registry  # type: ignore[import-not-found]
        from bara.board.layout import controller_gpio  # type: ignore[import-not-found]
    except Exception:
        return {}
    out: dict[str, int] = {}
    for ctrl in getattr(registry, "CONTROLLERS", []):
        try:
            out[ctrl["id"]] = len(controller_gpio(ctrl)[0])
        except Exception:  # a controller whose library files are missing is skipped
            log.warning("live: no GPIO count for controller %s", ctrl.get("id"))
    return out


def board_brief(brief: dict[str, Any], mcu_label: str | None) -> dict[str, Any]:
    """The BOARD brief keys, typed the way bara.board.layout.normalize_brief reads them."""
    feats = []
    for f in brief.get("features", []):
        if f["kind"] not in ("knob", "screen", "trackball"):
            continue
        hint = " ".join(x for x in (f.get("position"), f.get("side")) if x)
        feats.append({"kind": f["kind"], "count": int(f.get("count") or 1), "position": hint})
    style = brief.get("layout_style")
    return {
        "key_count": brief.get("key_count"),
        "layout_style": style,
        "rows": brief.get("rows"),
        "cols": brief.get("cols"),
        "thumb_keys": brief.get("thumb_keys"),
        "switch_family": brief.get("switch_family") or "mx",
        "mcu": mcu_label or "",
        "features": feats,
        "wireless": brief.get("wireless") in ("ble", "wifi"),
        "battery": brief.get("power_source") == "battery",
        "column_stagger": (brief.get("stagger") or ("column" if style == "split" else "ortho"))
        == "column",
    }


async def run_board(
    brief: dict[str, Any],
    parts: list[dict[str, Any]],
    build_id: str,
    on_progress: Progress,
    heartbeat_s: float = 2.0,
) -> tuple[dict[str, Any] | None, str | None]:
    """Run build_board in a worker thread, relaying its progress. (result, error)."""
    board, why = board_module()
    if board is None:
        return None, why
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, float | None]] = asyncio.Queue()

    def progress(message: str, fraction: float | None = None) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, (str(message), fraction))

    started = time.monotonic()
    task = asyncio.ensure_future(
        asyncio.to_thread(board.build_board, brief, parts, build_id=build_id, progress=progress)
    )
    last = "Building the KiCad board"
    while not task.done():
        try:
            message, fraction = await asyncio.wait_for(queue.get(), heartbeat_s)
            last = message
            on_progress(message, fraction)
        except TimeoutError:
            on_progress(f"{last} ({int(time.monotonic() - started)} s)", None)
    while not queue.empty():
        message, fraction = queue.get_nowait()
        on_progress(message, fraction)
    try:
        return task.result(), None
    except Exception as exc:  # KiCad, Freerouting or DRC failed; the stage reports it
        log.exception("live: build_board failed")
        return None, f"KiCad board build failed: {type(exc).__name__}: {str(exc)[:160]}"


def layout_from_keys(
    keys: list[dict[str, Any]], layout_id: str, name: str, pitch: tuple[float, float]
) -> tuple[dict[str, Any], list[float]]:
    """SPEC 3.3 layout + its position_mm from per-key board centres (build space, Y up)."""
    px, py = pitch
    xs = [k["x"] for k in keys]
    ys = [k["y"] for k in keys]
    ox, oy = min(xs) - px / 2, max(ys) + py / 2
    out = []
    for i, k in enumerate(keys):
        x_u = round((k["x"] - ox) / px - 0.5, 4)
        y_u = round(-(k["y"] - oy) / py - 0.5, 4)
        entry: dict[str, Any] = {"i": i, "x_u": x_u, "y_u": y_u}
        rot = float(k.get("rot") or 0.0)
        if abs(rot) > 1e-6:
            entry.update({"r_deg": round(-rot, 3), "rx_u": x_u + 0.5, "ry_u": y_u + 0.5})
        if k.get("matrix") is not None:
            entry["matrix"] = k["matrix"]
        out.append(entry)
    layout = {
        "layout_id": layout_id,
        "name": name[:80],
        "pitch_x_mm": px,
        "pitch_y_mm": py,
        "keys": out,
    }
    return layout, [round(ox, 3), round(oy, 3), 0.0]


def key_pitch(switch_family: str | None) -> tuple[float, float]:
    try:
        from bara.board import registry  # type: ignore[import-not-found]

        fam = "choc" if (switch_family or "").startswith("choc") else "mx"
        return tuple(registry.SWITCHES[fam]["pitch"])  # type: ignore[return-value]
    except Exception:
        return (PITCH_MM, PITCH_MM)


# ---- GEOMETRY ---------------------------------------------------------------------------
def geometry_module() -> tuple[Any | None, str | None]:
    try:
        import bara.geometry as geometry
    except Exception as exc:
        return None, f"geometry package unavailable ({type(exc).__name__})"
    if not hasattr(geometry, "enclose_report"):
        return None, "bara.geometry.enclose_report is not available"
    return geometry, None


def geometry_brief(brief: dict[str, Any]) -> dict[str, Any]:
    colours = brief.get("colours") or []
    case = next((c for c in colours if c.get("target") in ("case", "all")), None)
    feats = [f["kind"] for f in brief.get("features", [])]
    out: dict[str, Any] = {
        "layout": brief.get("layout_style"),
        "colors": {"case": case["hex"]} if case else {},
        "features": feats + (["tented"] if brief.get("tented") else []),
        "tented": bool(brief.get("tented")),
    }
    return out


def parts_board(parts: list[dict[str, Any]], catalog_parts: dict[str, dict[str, Any]]) -> dict:
    """Carrier outline for a device with no KiCad board: parts packed in a row, by bbox.

    Used only when BOARD has no planner for the device class. The record says so
    (board_id pcb_none) and the board stage reports it as skipped.
    """
    gap = 4.0
    x = 0.0
    placements = []
    for part in parts:
        record = catalog_parts.get(part["part_id"]) or {}
        bbox = (record.get("mechanical") or {}).get("bbox_mm") or {}
        lo, hi = bbox.get("min"), bbox.get("max")
        if lo and hi:
            w, d, h = hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]
        else:
            w = d = 20.0
            h = 5.0
        for _ in range(
            int(part.get("quantity") or 1)
            if part.get("placement", {}).get("mode") != "layout"
            else 1
        ):
            placements.append(
                {
                    "instance_id": part["instance_id"],
                    "ref": part["instance_id"],
                    "part_id": part["part_id"],
                    "role": None,
                    "lib_id": part["part_id"],
                    "x_mm": x + w / 2,
                    "y_mm": 0.0,
                    "rot_deg": 0.0,
                    "side": "top",
                    "height_mm": round(h, 2),
                    "size_mm": [round(w, 2), round(d, 2)],
                    "sized_from": "bbox" if lo else "placeholder",
                }
            )
            x += w + gap
    width = max(30.0, x - gap)
    depth = max([p["size_mm"][1] for p in placements] + [30.0]) + 2 * gap
    for p in placements:
        p["x_mm"] -= width / 2
    hw, hd = width / 2 + gap, depth / 2
    return {
        "board_id": "pcb_none",
        "side": "none",
        "outline": [[-hw, -hd], [hw, -hd], [hw, hd], [-hw, hd]],
        "thickness_mm": 1.6,
        "position_mm": [0, 0, 0],
        "placements": placements,
        "cables": [],
    }


def plan_outline(half: Any, style: str, margin_mm: float = 5.0, gap_mm: float = 40.0) -> dict:
    """Plain rectangle around one half's key grid, used only when the KiCad build failed."""
    w = half.width_u * PITCH_MM + 2 * margin_mm
    d = half.height_u * PITCH_MM + 2 * margin_mm
    cx = {"left": -(gap_mm + w) / 2, "right": (gap_mm + w) / 2}.get(half.side, 0.0)
    return {
        "board_id": f"pcb_{half.side if half.side != 'none' else 'main'}",
        "side": half.side,
        "outline": [
            [cx - w / 2, -d / 2],
            [cx + w / 2, -d / 2],
            [cx + w / 2, d / 2],
            [cx - w / 2, d / 2],
        ],
        "holes": [],
        "thickness_mm": 1.6,
        "position_mm": [0, 0, 0],
        "placements": [],
        "cables": [],
    }


def geometry_board(entry: dict[str, Any]) -> dict[str, Any]:
    """BOARD output entry -> the board record shape GEOMETRY reads."""
    spec_board = entry.get("board") or {}
    outline = entry.get("outline") or entry.get("outline_mm") or spec_board.get("outline_mm")
    return {
        "board_id": spec_board.get("board_id") or f"pcb_{entry.get('name', 'main')}",
        "side": spec_board.get("side") or entry.get("name"),
        "outline": outline,
        "holes": entry.get("holes") or [],
        "thickness_mm": spec_board.get("thickness_mm") or 1.6,
        "position_mm": spec_board.get("position_mm") or [0, 0, 0],
        "placements": entry.get("placements") or [],
        "cables": entry.get("cables") or [],
    }


def run_enclose(
    board_record: dict[str, Any], parts: list[dict[str, Any]], brief: dict[str, Any]
) -> tuple[Any | None, str | None]:
    geometry, why = geometry_module()
    if geometry is None:
        return None, why
    try:
        return geometry.enclose_report(board_record, parts, geometry_brief(brief)), None
    except Exception as exc:  # a degenerate outline must not take the build down
        log.exception("live: enclose failed")
        return None, f"case generation failed: {type(exc).__name__}: {str(exc)[:160]}"


def fallback_enclosure(
    board_record: dict[str, Any], brief: dict[str, Any], instance_ids: list[str], side: str
) -> dict[str, Any]:
    """Enclosure record with status pending when GEOMETRY is unavailable (no mesh)."""
    pts = board_record.get("outline") or [[0, 0]]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    height = max([p.get("height_mm") or 0 for p in board_record.get("placements", [])] + [5.0])
    colours = brief.get("colours") or []
    case = next((c for c in colours if c.get("target") in ("case", "all")), None)
    suffix = {"left": "_l", "right": "_r"}.get(side, "")
    return {
        "enclosure_id": f"e_case{suffix}",
        "kind": "generated",
        "side": side if side in ("left", "right") else "none",
        "for_instance_ids": instance_ids,
        "params": {
            "wall_mm": 3.0,
            "floor_mm": 2.5,
            "fillet_mm": 2.0,
            "clearance_mm": 0.5,
            "height_mm": None,
            "split": "tray",
            "standoff_height_mm": None,
            "screw": "m2",
        },
        "outer_size_mm": [
            round(max(xs) - min(xs) + 7.0, 2),
            round(max(ys) - min(ys) + 7.0, 2),
            round(height + 8.0, 2),
        ],
        "position_mm": [round((max(xs) + min(xs)) / 2, 2), round((max(ys) + min(ys)) / 2, 2), 0.0],
        "rotation_deg": [0, 0, 0],
        "explode_offset_mm": [0, 0, -30.0],
        "cutouts": [],
        "color": {"hex": case["hex"] if case else "#9E9E9E", "material": "plastic", "node": None},
        "material": "plastic",
        "color_source": "user" if case else "default",
        "assets": [],
        "status": "pending",
        "duration_ms": 0,
        "revision": 1,
    }


def distance(a: list[float], b: list[float]) -> float:
    return math.dist(a[:2], b[:2])
