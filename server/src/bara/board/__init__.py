"""Brief -> real routed KiCad boards.

build_board() lays out the keys and features generically (layout.py), writes a .kicad_pcb with
KiCad's own pcbnew, routes it with Freerouting through DSN/SES, checks it with
`kicad-cli pcb drc` and exports a GLB with `kicad-cli pcb export glb`. Results are cached by
a composition key (the exact KiCad input plus tool versions).

Frames: layout and KiCad use y down. Everything returned is in build space (SPEC 3: Z up,
+X right, +Y away from the user), so y is negated and split halves are moved apart.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from shapely.geometry import Point, Polygon

from bara.config import load_settings
from bara.geometry import glbopt

from . import kicad as K
from . import registry as R
from .layout import HALF_GAP_MM, BoardPlan, plan_boards, sensor_lens
from .libs import LIBRARIES, repo_commit

__all__ = ["build_board", "plan_board", "route_board", "BoardBuildError"]

Progress = Callable[[str, float | None], None]
CACHE_VERSION = "board-v3"
PCB_THICKNESS_MM = 1.6

# Composer part function / role words -> layout roles (for part_id mapping only).
_PART_ROLES: list[tuple[str, tuple[str, ...]]] = [
    ("keycap", ("mech.keycap", "keycap")),
    ("switch", ("input.key", "switch")),
    ("encoder", ("rotary_encoder", "encoder", "knob")),
    ("screen", ("display", "oled", "screen", "lcd")),
    ("trackball", ("trackball",)),
    ("sensor", ("pmw", "optical_sensor", "motion_sensor")),
    ("battery", ("power.battery", "battery", "lipo")),
    ("mcu", ("compute.mcu", "mcu", "nice_nano", "xiao", "controller")),
    ("diode", ("diode",)),
]


class BoardBuildError(RuntimeError):
    pass


def _part_role(part: dict) -> str | None:
    card = part.get("card") or {}
    blob = " ".join(
        str(v).lower()
        for v in (
            part.get("role"),
            part.get("function"),
            card.get("primary_function"),
            part.get("part_id"),
            card.get("display_name"),
            part.get("name"),
        )
        if v
    )
    for role, words in _PART_ROLES:
        if any(w in blob for w in words):
            return role
    return None


def _parts_by_role(parts: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for p in parts or []:
        role = _part_role(p)
        if role and role not in out:
            out[role] = p
    return out


def _catalog_lookup(part: dict | None) -> tuple[str | None, str | None]:
    """catalog_db.footprint_for / model_for when that module exists; else (None, None)."""
    if not part:
        return None, None
    try:
        from bara import catalog_db  # type: ignore[attr-defined]
    except ImportError:
        return None, None
    pid = part.get("part_id")
    fp = getattr(catalog_db, "footprint_for", None)
    md = getattr(catalog_db, "model_for", None)
    try:
        return (fp(pid) if fp else None), (md(pid) if md else None)
    except Exception:  # noqa: BLE001 - catalog is optional; fall back to direct libraries
        return None, None


# ---------------------------------------------------------------- frames


def _half_offset(plan: BoardPlan) -> float:
    x0, _, x1, _ = plan.outline.bounds
    if plan.name == "left":
        return -HALF_GAP_MM / 2 - x1
    if plan.name == "right":
        return HALF_GAP_MM / 2 - x0
    return -(x0 + x1) / 2


def _to_build(x: float, y: float, dx: float, dy: float) -> tuple[float, float]:
    return round(x + dx, 3), round(-(y + dy), 3)


def _poly_build(poly: Polygon, dx: float, dy: float) -> list[list[float]]:
    pts = list(poly.exterior.coords)[:-1]
    out = [list(_to_build(x, y, dx, dy)) for x, y in pts]
    return out[::-1]  # y flip reverses winding; keep counter-clockwise


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in text.lower()).strip("_")[:63] or "main"


def _instance_id(text: str) -> str:
    s = "".join(c if c.isalnum() else "_" for c in text.lower()).strip("_")
    return (s if s and s[0].isalpha() else "p_" + s)[:64]


# ---------------------------------------------------------------- one board


def _fp_lib_table(plan_data: dict) -> str:
    """Project library table so DRC can compare each footprint with its source library."""
    rows = sorted({(Path(f["lib_dir"]).stem, f["lib_dir"]) for f in plan_data["footprints"]})
    body = "".join(
        f'  (lib (name "{nick}")(type "KiCad")(uri "{uri}")(options "")(descr ""))\n'
        for nick, uri in rows
    )
    return f"(fp_lib_table\n  (version 7)\n{body})\n"


def _cache_key(kicad_input: dict, passes: int) -> str:
    stable = json.loads(json.dumps(kicad_input))
    stable.pop("board_path", None)
    stable.pop("dsn_path", None)
    blob = json.dumps(
        {
            "v": CACHE_VERSION,
            "input": stable,
            "rules": K.RULES,
            "passes": passes,
            "freerouting": K.FREEROUTING_VERSION,
            "strategies": K.ROUTE_STRATEGIES,
            "script": hashlib.sha256(K.SCRIPT.read_bytes()).hexdigest(),
        },
        sort_keys=True,
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


@contextmanager
def _key_lock(path: Path) -> Iterator[None]:
    """Exclusive lock across threads and processes (flock on a lock file)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _route_one(
    plan: BoardPlan,
    work_root: Path,
    glb_root: Path,
    origin_plan: tuple[float, float],
    route_timeout_s: float,
    passes: int,
    progress: Progress,
) -> dict:
    t0 = time.monotonic()
    probe = K.plan_json(plan, Path("main.kicad_pcb"), Path("main.dsn"))
    key = _cache_key(probe, passes)
    work = work_root / key
    result_path = work / "result.json"
    glb = glb_root / f"{key}.glb"
    # Identical boards from concurrent builds share this key, work dir and GLB path. Without
    # the lock their kicad-cli runs interleave into one corrupt GLB that then stays cached.
    with _key_lock(work_root / f"{key}.lock"):
        if result_path.exists() and glb.exists():
            cached = json.loads(result_path.read_text())
            if not glbopt.is_valid(glb) and (work / "main.kicad_pcb").exists():
                # Routing is cached and fine; only the GLB is damaged: export it again.
                progress(f"{plan.name}: re-exporting damaged GLB {key}", 0.85)
                ox, oy = K.KICAD_OFFSET
                K.export_glb(
                    work / "main.kicad_pcb", glb, (origin_plan[0] + ox, origin_plan[1] + oy)
                )
            cached["cache_hit"] = True
            progress(f"{plan.name}: cached board {key}", 1.0)
            return cached
        work.mkdir(parents=True, exist_ok=True)
        pcb = work / "main.kicad_pcb"
        dsn = work / "main.dsn"
        ses = work / "main.ses"
        for stale in (pcb, dsn, ses):
            stale.unlink(missing_ok=True)
        plan_data = K.plan_json(plan, pcb, dsn)
        plan_path = work / "plan.json"
        plan_path.write_text(json.dumps(plan_data, indent=1))
        (work / "fp-lib-table").write_text(_fp_lib_table(plan_data))
        timings: dict[str, float] = {}

        attempts: list[dict] = []
        deadline = time.monotonic() + route_timeout_s
        drc: dict = {}
        route: dict = {}
        for i, (strategy, extra) in enumerate(K.ROUTE_STRATEGIES):
            remaining = deadline - time.monotonic()
            if i and remaining < 10:
                break
            for stale in (pcb, dsn, ses):
                stale.unlink(missing_ok=True)
            progress(f"{plan.name}: writing KiCad board", 0.1)
            t = time.monotonic()
            K.build_pcb(plan_path)
            timings["kicad_build_s"] = round(time.monotonic() - t, 2)

            progress(
                f"{plan.name}: autorouting with Freerouting {K.FREEROUTING_VERSION} ({strategy})",
                0.25,
            )
            route = K.freeroute(dsn, ses, remaining, passes=passes, extra=extra)
            timings["route_s"] = round(timings.get("route_s", 0.0) + route["seconds"], 2)

            progress(f"{plan.name}: importing routes", 0.7)
            t = time.monotonic()
            K.import_ses(pcb, ses)
            timings["ses_import_s"] = round(time.monotonic() - t, 2)

            progress(f"{plan.name}: DRC", 0.75)
            t = time.monotonic()
            drc = K.run_drc(pcb)
            timings["drc_s"] = round(time.monotonic() - t, 2)
            attempts.append(
                {
                    "strategy": strategy,
                    "route_s": route["seconds"],
                    "passes": route.get("passes"),
                    "errors": drc["errors"],
                    "unconnected": drc["unconnected"],
                }
            )
            if drc["errors"] == 0 and drc["unconnected"] == 0:
                break
            progress(
                f"{plan.name}: {drc['unconnected']} unconnected after {strategy}, retrying", 0.3
            )

        progress(f"{plan.name}: exporting GLB", 0.85)
        t = time.monotonic()
        ox, oy = K.KICAD_OFFSET
        K.export_glb(pcb, glb, (origin_plan[0] + ox, origin_plan[1] + oy))
        timings["glb_s"] = round(time.monotonic() - t, 2)
        timings["total_s"] = round(time.monotonic() - t0, 2)

        result = {
            "key": key,
            "kicad_pcb": str(pcb),
            "glb_path": str(glb),
            "drc": drc,
            "routing": {
                **K.count_routing(pcb),
                "router_unrouted": route.get("unrouted"),
                "passes": route.get("passes"),
                "unrouted_nets": drc.get("unconnected_nets", []),
                "strategy": attempts[-1]["strategy"],
                "attempts": attempts,
            },
            "timings": timings,
            "cache_hit": False,
        }
        result_path.write_text(json.dumps(result, indent=1))
        return result


# ---------------------------------------------------------------- records


def _placements(
    plan: BoardPlan, dx: float, dy: float, roles: dict[str, dict], side_tag: str
) -> list[dict]:
    out = []
    for it in plan.items:
        bx, by = _to_build(it.x, it.y, dx, dy)
        part = roles.get(it.role)
        size = list(it.size_mm) if it.size_mm else (list(it.fp.size_mm) if it.fp else [1, 1])
        if it.fp is not None and it.role == "switch":
            size = [round(v, 2) for v in it.fp.size_mm]
        lib = LIBRARIES.get(it.fp.lib) if it.fp else None
        inst = _instance_id(f"{side_tag}_{it.ref}")
        # x/y and placement.position_mm are the footprint origin (where the KiCad model sits);
        # x_mm/y_mm are the body (courtyard) centre, which is what size_mm is centred on.
        cx, cy = _to_build(*it.centre(), dx, dy) if it.fp else (bx, by)
        out.append(
            {
                "ref": it.ref,
                "part_id": part.get("part_id") if part else None,
                "instance_id": inst,
                "role": it.role,
                "label": it.label,
                "lib_id": it.fp.lib_id if it.fp else "",
                "x": bx,
                "y": by,
                "rot": round(it.rot, 3),
                "x_mm": cx,
                "y_mm": cy,
                "rot_deg": round(it.rot, 3),
                "side": it.side,
                "on_pcb": it.on_pcb,
                "touch": bool(it.meta.get("touch")),
                "height_mm": it.height_mm,
                "size_mm": [round(float(v), 3) for v in size],
                "source_url": str(lib["url"]) if lib else "",
                "licence": str(lib["licence"]) if lib else "",
                "commit": repo_commit(it.fp.lib) if it.fp else None,
                "placement": {
                    "mode": "single",
                    "position_mm": [bx, by, 0.0 if it.side == "top" else -PCB_THICKNESS_MM],
                    "rotation_deg": [0.0 if it.side == "top" else 180.0, 0.0, round(it.rot, 3)],
                    "source": "solver",
                },
            }
        )
        if it.meta.get("instance_id"):
            out[-1]["for_instance_id"] = it.meta["instance_id"]
        if it.role == "switch" and it.meta.get("matrix") is not None:
            out[-1]["matrix"] = list(it.meta["matrix"])
        w_u = float(it.meta.get("w_u") or 1.0) if it.role == "switch" else 1.0
        if it.role == "switch":
            out[-1]["w_u"] = w_u
        cap = it.meta.get("keycap_mm") if it.role == "switch" else None
        if cap:
            out.append(
                {
                    "ref": f"KC{it.ref.removeprefix('SW')}",
                    "part_id": (roles.get("keycap") or {}).get("part_id"),
                    "instance_id": _instance_id(f"{side_tag}_kc{it.ref.removeprefix('SW')}"),
                    "role": "keycap",
                    "label": f"{w_u:g}u keycap envelope",
                    "w_u": w_u,
                    "lib_id": "",
                    "x": bx,
                    "y": by,
                    "rot": round(it.rot, 3),
                    "x_mm": bx,
                    "y_mm": by,
                    "rot_deg": round(it.rot, 3),
                    "side": "top",
                    "on_pcb": False,
                    "mounted_on": it.ref,
                    "height_mm": it.meta["keycap_top_mm"],
                    "size_mm": [float(cap[0]), float(cap[1])],
                    "source_url": "",
                    "licence": "",
                    "commit": None,
                    "hand_set": True,
                    "placement": {
                        "mode": "single",
                        "position_mm": [bx, by, 0.0],
                        "rotation_deg": [0.0, 0.0, round(it.rot, 3)],
                        "source": "solver",
                    },
                }
            )
    return out


def _attach_daughter_boards(boards: list[dict]) -> None:
    """Give each host half a placement standing in for its sensor daughter board.

    GEOMETRY works one board at a time: it sizes the trackball cup's sensor pocket from a
    "sensor" placement under the ball and checks cables between refs on the same board.
    """
    by_id = {bd["board_id"]: bd for bd in boards}
    for host in boards:
        for cab in host["cables"]:
            sub = by_id.get(cab["to_board"])
            if sub is None:
                continue
            xs = [p[0] for p in sub["outline"]]
            ys = [p[1] for p in sub["outline"]]
            sensor = next((p for p in sub["placements"] if p["role"] == "sensor"), None)
            ball = next((p for p in host["placements"] if p["role"] == "trackball"), None)
            cx, cy = (
                (ball["x_mm"], ball["y_mm"])
                if ball
                else ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
            )
            tallest = max((p["height_mm"] for p in sub["placements"] if p["on_pcb"]), default=0)
            ref = f"SB{len([p for p in host['placements'] if p['ref'].startswith('SB')]) + 1}"
            host["placements"].append(
                {
                    "ref": ref,
                    "part_id": sensor.get("part_id") if sensor else None,
                    "instance_id": _instance_id(f"{host['name']}_{ref}"),
                    "role": "sensor",
                    "label": f"sensor board {sub['board_id']} (under the trackball)",
                    "lib_id": sensor["lib_id"] if sensor else "",
                    "x": round(cx, 4),
                    "y": round(cy, 4),
                    "rot": 0.0,
                    "x_mm": round((min(xs) + max(xs)) / 2, 4),
                    "y_mm": round((min(ys) + max(ys)) / 2, 4),
                    "rot_deg": 0.0,
                    "side": "bottom",
                    "on_pcb": False,
                    "board_ref": sub["board_id"],
                    "lens_mm": [round(cx, 4), round(cy, 4)],
                    "height_mm": round(PCB_THICKNESS_MM + tallest, 3),
                    "size_mm": [round(max(xs) - min(xs), 3), round(max(ys) - min(ys), 3)],
                    "source_url": sensor["source_url"] if sensor else "",
                    "licence": sensor["licence"] if sensor else "",
                    "commit": sensor["commit"] if sensor else None,
                    "placement": {
                        "mode": "single",
                        "position_mm": [round(cx, 4), round(cy, 4), -PCB_THICKNESS_MM],
                        "rotation_deg": [0.0, 0.0, 0.0],
                        "source": "solver",
                    },
                }
            )
            cab["to_board_ref"] = cab["to_ref"]
            cab["to_ref"] = ref


def _nets(plan: BoardPlan, side_tag: str) -> list[dict]:
    members: dict[str, list[dict]] = {}
    for it in plan.items:
        if not it.on_pcb:
            continue
        for pin, net in sorted(it.pads.items()):
            if net:
                members.setdefault(net, []).append(
                    {"instance_id": _instance_id(f"{side_tag}_{it.ref}"), "pin": pin}
                )
    out = []
    for name in sorted(members):
        kind = (
            "ground"
            if name == "GND"
            else "power"
            if name in ("3V3", "BAT+", "VBAT_IN", "VDD18", "VDDPIX", "5V", "VBUS", "VBAT")
            else "signal"
        )
        out.append({"name": name, "kind": kind, "members": members[name]})
    return out


def _glb_ref(path: Path, key: str) -> dict:
    data = path.read_bytes()
    return {
        "asset_id": f"board_{key}",
        "kind": "glb",
        "role": "model",
        "url": f"/assets/cache/boards/{path.name}",
        "content_type": "model/gltf-binary",
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "status": "ready",
        "origin": "generated",
    }


# ---------------------------------------------------------------- entry


def plan_board(brief: dict, parts: list[dict], *, build_id: str | None = None) -> dict:
    """Phase 1 (fast, no KiCad): lay the boards out. Placements, outlines, nets, pin budget.

    The returned dict has the same "boards" entries as build_board() minus the routing,
    DRC and GLB fields; pass it to route_board() to finish it.
    """
    t = time.monotonic()
    if brief.get("generic"):
        from .generic import plan_device_board

        b, log = None, []
        plans = [plan_device_board(parts, log, brief)]
    else:
        b, plans, log = plan_boards(brief)
    plan_s = round(time.monotonic() - t, 3)
    roles = _parts_by_role(parts)
    fp_hint, model_hint = _catalog_lookup(roles.get("mcu"))
    if fp_hint or model_hint:
        log.append(f"catalog footprint/model hint for MCU: {fp_hint} / {model_hint}")

    offsets: dict[str, tuple[float, float]] = {}
    for plan in plans:
        if plan.name in ("left", "right", "main"):
            offsets[plan.name] = (_half_offset(plan), 0.0)

    boards: list[dict] = []
    for plan in plans:
        is_sensor = plan.name.endswith("sensor")
        host_name = plan.name.removesuffix("sensor").rstrip("_") if is_sensor else None
        if plan.name in offsets:
            dx, dy = offsets[plan.name]
        else:
            # sensor board: centred under its trackball in the host half's frame
            want = host_name or "main"
            host = next((p for p in plans if p.name == want), plans[0])
            hdx, hdy = offsets.get(host.name, (0.0, 0.0))
            ball = next((it for it in host.items if it.role == "trackball"), None)
            sc = sensor_lens(plan)  # the lens goes under the ball
            if ball is not None:
                dx, dy = ball.x + hdx - sc.x, ball.y + hdy - sc.y
            else:
                dx, dy = hdx, hdy
        side = (
            plan.name
            if plan.name in ("left", "right")
            else (host_name if host_name in ("left", "right") else "none")
        )
        tag = plan.name
        outline = _poly_build(plan.outline, dx, dy)
        holes = [
            _poly_build(Point(cx, cy).buffer(r, 64), dx, dy) for cx, cy, r in plan.hole_circles
        ]
        placements = _placements(plan, dx, dy, roles, tag)
        x0, y0, x1, y1 = plan.outline.bounds
        cables = [
            {
                "from_ref": link["from_ref"],
                "to_board": "pcb_" + _slug(link["to_board"]),
                "to_ref": link["to_ref"],
                "length_mm": link["cable_mm"],
            }
            for link in plan.links
        ]
        boards.append(
            {
                "name": plan.name,
                "board_id": "pcb_" + _slug(plan.name),
                "side": side,
                "outline": outline,
                "outline_mm": outline,
                "holes": holes,
                "size_mm": [round(x1 - x0, 3), round(y1 - y0, 3)],
                "thickness_mm": PCB_THICKNESS_MM,
                "position_mm": [0.0, 0.0, 0.0],
                "nets": _nets(plan, tag),
                "placements": placements,
                "cables": cables,
                "controller": plan.controller["id"] if plan.controller else None,
                "pin_budget": plan.pin_budget,
                "_plan": plan,
                "_origin": (-dx, -dy),
            }
        )
    _attach_daughter_boards(boards)
    return {
        "build_id": build_id,
        "boards": boards,
        "controller": {bd["name"]: bd["controller"] for bd in boards if bd["controller"]},
        "pin_budget": {bd["name"]: bd["pin_budget"] for bd in boards if bd["pin_budget"]},
        "log": log,
        "hand_set": list(R.HAND_SET),
        "brief": (
            {"key_count": b.key_count, "split": b.split, "switch": b.switch}
            if b is not None
            else {"generic": True}
        ),
        "timings": {"plan_s": plan_s},
        "placements": boards[0]["placements"],
        "outline": boards[0]["outline"],
        "nets": boards[0]["nets"],
    }


def route_board(
    planned: dict,
    *,
    progress: Progress | None = None,
    route_timeout_s: float = 300.0,
    passes: int = 100,
) -> dict:
    """Phase 2: write each planned board with pcbnew, autoroute, DRC, export the GLB."""
    report: Progress = progress or (lambda _msg, _frac: None)
    t0 = time.monotonic()
    settings = load_settings()
    work_root = settings.data_dir / "cache" / "boards"
    glb_root = settings.assets_dir / "cache" / "boards"
    work_root.mkdir(parents=True, exist_ok=True)
    glb_root.mkdir(parents=True, exist_ok=True)
    boards = planned["boards"]
    for i, entry in enumerate(boards):
        plan: BoardPlan = entry.pop("_plan")
        origin_plan = entry.pop("_origin")

        def sub(msg: str, frac: float | None, _i: int = i) -> None:
            report(msg, None if frac is None else (_i + frac) / len(boards))

        res = _route_one(plan, work_root, glb_root, origin_plan, route_timeout_s, passes, sub)
        drc = res["drc"]
        ok = drc["errors"] == 0 and drc["unconnected"] == 0
        glb_ref = _glb_ref(Path(res["glb_path"]), res["key"])
        spec_board = {
            "board_id": entry["board_id"],
            "source": "unknown",
            "side": entry["side"],
            "part_instance_id": None,
            "for_instance_ids": [p["instance_id"] for p in entry["placements"]],
            "outline_mm": entry["outline"],
            "size_mm": entry["size_mm"],
            "thickness_mm": PCB_THICKNESS_MM,
            "layers": 2,
            "position_mm": [0.0, 0.0, 0.0],
            "rotation_deg": [0.0, 0.0, 0.0],
            "nets": entry["nets"],
            "routing": {
                "status": "routed" if drc["unconnected"] == 0 else "partial",
                "unrouted_nets": res["routing"].get("unrouted_nets", []),
                "duration_ms": int(res["timings"]["route_s"] * 1000),
                "method": "autorouted",
                "cache_key": res["key"],
                "cache_hit": res["cache_hit"],
                "router": f"freerouting {K.FREEROUTING_VERSION}",
            },
            "drc": "pass" if ok else "fail",
            "assets": [glb_ref],
            "status": "ok" if ok else "failed",
            "revision": 0,
        }
        entry.update(
            {
                "board": spec_board,
                "kicad_pcb": res["kicad_pcb"],
                "kicad_pcb_path": res["kicad_pcb"],
                "glb": glb_ref,
                "glb_path": res["glb_path"],
                "glb_url": glb_ref["url"],
                "drc": drc,
                "routing": res["routing"],
                "timings": res["timings"],
                "cache_hit": res["cache_hit"],
            }
        )
    main = boards[0]
    report("boards done", 1.0)
    planned["tools"] = {
        "kicad": K.kicad_version(),
        "freerouting": K.FREEROUTING_VERSION,
        "strategies": K.ROUTE_STRATEGIES,
    }
    planned["timings"] = {
        **planned.get("timings", {}),
        "route_total_s": round(time.monotonic() - t0, 2),
        "per_board": {bd["name"]: bd["timings"] for bd in boards},
    }
    planned["timings"]["total_s"] = round(
        planned["timings"].get("plan_s", 0.0) + planned["timings"]["route_total_s"], 2
    )
    planned.update(
        {
            "kicad_pcb": main["kicad_pcb"],
            "glb": main["glb"],
            "drc": main["drc"],
            "nets": main["nets"],
            "outline": main["outline"],
            "placements": main["placements"],
        }
    )
    return planned


def build_board(
    brief: dict,
    parts: list[dict],
    *,
    build_id: str | None = None,
    progress: Progress | None = None,
    route_timeout_s: float = 300.0,
    passes: int = 100,
) -> dict:
    """Generic brief -> list of routed KiCad boards (one per half, plus sensor boards).

    Returns {"boards": [...], "controller", "pin_budget", "log", "timings", "hand_set"} plus
    main-board shortcuts kicad_pcb, glb, drc, nets, outline, placements.
    """
    report: Progress = progress or (lambda _msg, _frac: None)
    planned = plan_board(brief, parts, build_id=build_id)
    report(f"planned {len(planned['boards'])} board(s)", 0.05)
    return route_board(planned, progress=report, route_timeout_s=route_timeout_s, passes=passes)
