"""Validator for a generated case: SPEC 6.1 style CheckResults measured with rays and booleans.

Everything is checked in the board frame (before tenting) except watertightness and floating
pieces, which are checked on the final build-space meshes.
"""

from __future__ import annotations

import math
import statistics
import time
from typing import TYPE_CHECKING, Any

import manifold3d as mf
import numpy as np

from bara.geometry.case import (
    STACKED_ROLES,
    Feature,
    _prism,
    _rect_cs,
    point_in_polygon,
    rect_corners,
)

if TYPE_CHECKING:
    from bara.geometry.case import EncloseReport

# Hand-set validator limits (not from a record).
LIMITS: dict[str, float] = {
    "overlap_volume_mm3": 0.5,  # intersection volume treated as a collision
    "overlap_depth_mm": 0.05,  # OBB overlap tolerated between neighbouring parts
    "support_min_fraction": 0.25,  # board bottom area resting on the tray floor
    "ball_clearance_min_mm": 0.1,
    "ball_clearance_max_mm": 1.5,
    "screen_visible_fraction": 0.9,
    "screen_tilt_deg": 25.0,  # second viewing ray, tilted toward the user
    "stem_engagement_mm": 3.0,  # keycap/knob bottom below its switch/encoder top
    "ray_length_mm": 300.0,
}
SEVERITY = {
    "mech.case.watertight": "error",
    "mech.fit.floating": "error",
    "mech.fit.enclosure": "error",
    "mech.fit.collision": "error",
    "mech.fit.trackball": "error",
    "mech.fit.sensor_window": "error",
    "mech.view.screen": "warning",
    "mech.access.panel": "warning",
    "mech.cable.length": "error",
}


def _check(
    rule: str,
    subject: str,
    ok: bool | None,
    message: str,
    *,
    measured: Any = None,
    limit: Any = None,
    unit: str | None = None,
    enclosure_id: str,
    board_id: str | None,
    started: float,
    fix: str | None = None,
) -> dict[str, Any]:
    subj: dict[str, Any] = {"enclosure_id": enclosure_id}
    if board_id:
        subj["board_id"] = board_id
    out: dict[str, Any] = {
        "check_key": f"{rule}:{subject}"[:200],
        "rule_id": rule,
        "status": "unknown" if ok is None else ("pass" if ok else "fail"),
        "severity": SEVERITY[rule],
        "message": message[:300],
        "subjects": [subj],
        "measured": measured,
        "limit": limit,
        "unit": unit,
        "stage": "enclose",
        "duration_ms": int(round((time.perf_counter() - started) * 1000)),
    }
    if fix and not ok:
        out["fix_hint"] = fix[:200]
    return out


def _first_hit(
    case: mf.Manifold, origin: np.ndarray, direction: np.ndarray, length: float
) -> float | None:
    end = origin + direction * length
    hits = case.ray_cast(tuple(origin.tolist()), tuple(end.tolist()))
    if not hits:
        return None
    return min(float(np.linalg.norm(np.asarray(h.position) - origin)) for h in hits)


def _open_edges(m: mf.Manifold) -> int:
    tris = np.asarray(m.to_mesh().tri_verts, dtype=np.int64)
    if tris.size == 0:
        return 0
    e = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    fwd = {tuple(x) for x in e.tolist()}
    return sum(1 for a, b in fwd if (b, a) not in fwd) + (len(e) - len(fwd))


def _feature_box(f: Feature, t: float, z_lo: float | None = None) -> mf.Manifold:
    lo, hi = f.z_range(t)
    if z_lo is not None:
        lo = z_lo
    return _prism(_rect_cs(f.x, f.y, f.w, f.d, f.rot_deg), lo, max(hi, lo + 0.01))


def _stack_partner(f: Feature, feats: list[Feature]) -> Feature | None:
    for g in feats:
        if (f.role, g.role) in STACKED_ROLES and math.hypot(f.x - g.x, f.y - g.y) < max(
            f.w, f.d
        ) / 2:
            return g
    return None


def _z_lo(f: Feature, feats: list[Feature], t: float) -> float:
    lo, _ = f.z_range(t)
    if f.z_bottom is None and f.role in ("keycap", "knob"):
        partner = _stack_partner(f, feats)
        if partner:
            lo = max(lo, partner.z_range(t)[1] - LIMITS["stem_engagement_mm"])
    return lo


def _obb_overlap(a: np.ndarray, b: np.ndarray) -> float:
    """Minimum separating-axis penetration of two convex quads (<= 0 means apart)."""
    depth = math.inf
    for poly in (a, b):
        for i in range(len(poly)):
            e = poly[(i + 1) % len(poly)] - poly[i]
            n = np.array([-e[1], e[0]])
            n = n / (np.linalg.norm(n) or 1)
            pa, pb = a @ n, b @ n
            depth = min(depth, min(pa.max(), pb.max()) - max(pa.min(), pb.min()))
            if depth <= 0:
                return depth
    return depth


def validate(report: EncloseReport) -> list[dict[str, Any]]:
    eid = report.enclosure["enclosure_id"]
    bid = report.board.get("board_id")
    t = report.thickness
    feats = report.features
    case = report.tray + report.bezel
    lv = report.levels
    checks: list[dict[str, Any]] = []
    kw = {"enclosure_id": eid, "board_id": bid}

    # 1. watertight case pieces (final meshes)
    s = time.perf_counter()
    world = [
        (n, getattr(report, f"world_{n}", None) or getattr(report, n)) for n in ("tray", "bezel")
    ]
    bad = []
    for name, m in world:
        if m.status() != mf.Error.NoError or m.is_empty() or m.volume() <= 0:
            bad.append(f"{name} invalid")
        elif (open_edges := _open_edges(m)) > 0:
            bad.append(f"{name} {open_edges} open edges")
    checks.append(
        _check(
            "mech.case.watertight",
            eid,
            not bad,
            "Case tray and bezel are closed 2-manifold solids."
            if not bad
            else "Case is not watertight: " + ", ".join(bad),
            measured=len(bad),
            limit=0,
            unit="defects",
            started=s,
            **kw,
        )
    )

    # 2. nothing floating
    s = time.perf_counter()
    pieces = {name: len(m.decompose()) for name, m in world}
    outline = report.outline
    lo_xy, hi_xy = outline.min(axis=0), outline.max(axis=0)
    grid_n = 24
    supported = total = 0
    tray = report.tray
    for gx in np.linspace(lo_xy[0], hi_xy[0], grid_n + 2)[1:-1]:
        for gy in np.linspace(lo_xy[1], hi_xy[1], grid_n + 2)[1:-1]:
            if not point_in_polygon(gx, gy, outline) or any(
                point_in_polygon(gx, gy, h) for h in report.holes
            ):
                continue
            total += 1
            d = _first_hit(tray, np.array([gx, gy, 0.05]), np.array([0, 0, -1.0]), 1.0)
            if d is not None and d <= 0.1:
                supported += 1
    frac = supported / total if total else 0.0
    loose = []
    for f in feats:
        if f.role == "trackball":
            continue
        if f.z_top is not None and f.z_bottom is not None:  # hangs in its own pocket
            d = _first_hit(
                tray, np.array([f.x, f.y, f.z_bottom + 0.05]), np.array([0, 0, -1.0]), 2.0
            )
            if d is None or d > 1.0:
                loose.append(f.ref)
            continue
        inside = point_in_polygon(f.x, f.y, outline) and not any(
            point_in_polygon(f.x, f.y, h) for h in report.holes
        )
        if not inside and f.role not in ("usb",):
            loose.append(f.ref)
    for g in report.openings.get("balls", []):
        d = _first_hit(
            tray,
            np.array(
                [g["x"] + g["r"] * 0.3, g["y"], g["cz"] - g["r"] * math.sqrt(1 - 0.09) + 0.01]
            ),
            np.array([0, 0, -1.0]),
            5.0,
        )
        if d is None or d > 2.0:
            loose.append("trackball")
    ok = (
        all(v == 1 for v in pieces.values())
        and frac >= LIMITS["support_min_fraction"]
        and not loose
    )
    msg = (
        f"Tray {pieces['tray']} piece, bezel {pieces['bezel']} piece; board rests on the "
        f"floor over {frac:.0%} of its area"
    )
    if loose:
        msg += f"; unsupported: {', '.join(loose[:6])}"
    checks.append(
        _check(
            "mech.fit.floating",
            eid,
            ok,
            msg + ".",
            measured=round(frac, 3),
            limit=LIMITS["support_min_fraction"],
            unit="fraction",
            started=s,
            **kw,
        )
    )

    # 3. parts inside the case with clearance (boolean volume + horizontal rays)
    s = time.perf_counter()
    offenders = []
    min_clear = math.inf
    board_cs = mf.CrossSection(
        [outline.tolist(), *[h[::-1].tolist() for h in report.holes]], mf.FillRule.EvenOdd
    )
    board_slab = _prism(board_cs, 0.0, t)
    v = (board_slab ^ case).volume()
    if v > LIMITS["overlap_volume_mm3"]:
        offenders.append(f"board ({v:.1f} mm3)")
    for f in feats:
        if f.role == "trackball":
            continue
        box = _feature_box(f, t, _z_lo(f, feats, t))
        v = (box ^ case).volume()
        if v > LIMITS["overlap_volume_mm3"]:
            offenders.append(f"{f.ref} ({v:.1f} mm3)")
        lo, hi = f.z_range(t)
        zc = (max(lo, 0.0) + max(hi, 0.0)) / 2 if f.side == "top" else (lo + hi) / 2
        a = math.radians(f.rot_deg)
        for ux, uy, half in (
            (math.cos(a), math.sin(a), f.w / 2),
            (-math.sin(a), math.cos(a), f.d / 2),
        ):
            for sign in (1, -1):
                d = _first_hit(
                    case,
                    np.array([f.x, f.y, zc]),
                    np.array([sign * ux, sign * uy, 0]),
                    LIMITS["ray_length_mm"],
                )
                if d is not None:
                    min_clear = min(min_clear, d - half)
    for g in report.openings.get("balls", []):
        sph = mf.Manifold.sphere(g["r"]).translate((g["x"], g["y"], g["cz"]))
        v = (sph ^ case).volume()
        if v > LIMITS["overlap_volume_mm3"]:
            offenders.append(f"trackball ({v:.1f} mm3)")
    mc = None if min_clear == math.inf else round(min_clear, 3)
    checks.append(
        _check(
            "mech.fit.enclosure",
            eid,
            not offenders and (mc is None or mc >= -0.01),
            (
                f"{len(feats)} parts and the board fit inside the case; nearest wall {mc} mm."
                if not offenders
                else "Parts cut into the case: " + ", ".join(offenders[:5])
            ),
            measured=mc,
            limit=0,
            unit="mm",
            started=s,
            fix="Grow the outline or move the part off the wall.",
            **kw,
        )
    )

    # 4. keep-outs: no two parts overlap (stacked mates excluded)
    s = time.perf_counter()
    clashes = []
    rects = [rect_corners(f.x, f.y, f.w, f.d, f.rot_deg) for f in feats]
    zr = [(_z_lo(f, feats, t), f.z_range(t)[1]) for f in feats]
    for i in range(len(feats)):
        for j in range(i + 1, len(feats)):
            a, b = feats[i], feats[j]
            if (a.role, b.role) in STACKED_ROLES or (b.role, a.role) in STACKED_ROLES:
                continue
            if min(zr[i][1], zr[j][1]) - max(zr[i][0], zr[j][0]) <= LIMITS["overlap_depth_mm"]:
                continue
            if _obb_overlap(rects[i], rects[j]) > LIMITS["overlap_depth_mm"]:
                clashes.append(f"{a.ref}/{b.ref}")
    checks.append(
        _check(
            "mech.fit.collision",
            eid,
            not clashes,
            f"No keep-out overlaps among {len(feats)} parts."
            if not clashes
            else f"{len(clashes)} overlaps: " + ", ".join(clashes[:5]),
            measured=len(clashes),
            limit=0,
            unit="overlaps",
            started=s,
            **kw,
        )
    )

    # 5. trackball in its cup, sensor window
    for k, g in enumerate(report.openings.get("balls", [])):
        s = time.perf_counter()
        c = np.array([g["x"], g["y"], g["cz"]])
        clear = []
        for pol in np.linspace(100, 175, 16):
            for az in np.linspace(0, 360, 24, endpoint=False):
                p, a = math.radians(pol), math.radians(az)
                d = np.array([math.sin(p) * math.cos(a), math.sin(p) * math.sin(a), math.cos(p)])
                hit = _first_hit(report.tray, c, d, g["r"] + 10)
                if hit is not None and hit < g["r"] + 5:
                    clear.append(hit - g["r"])
        ok = (
            bool(clear)
            and min(clear) >= LIMITS["ball_clearance_min_mm"]
            and statistics.median(clear) <= LIMITS["ball_clearance_max_mm"]
        )
        checks.append(
            _check(
                "mech.fit.trackball",
                f"{eid}_ball{k}",
                ok,
                (
                    f"Ball {2 * g['r']:.2f} mm in its cup: clearance min {min(clear):.2f}, median "
                    f"{statistics.median(clear):.2f} mm ({len(clear)} rays)."
                )
                if clear
                else "No cup surface found under the ball.",
                measured=round(min(clear), 3) if clear else None,
                limit=LIMITS["ball_clearance_min_mm"],
                unit="mm",
                started=s,
                **kw,
            )
        )
        s = time.perf_counter()
        bottom = c - np.array([0, 0, g["r"]])
        gap = g["cz"] - g["r"] - g["lens_z"]
        hit = _first_hit(report.tray, bottom - np.array([0, 0, 0.01]), np.array([0, 0, -1.0]), gap)
        checks.append(
            _check(
                "mech.fit.sensor_window",
                f"{eid}_ball{k}",
                hit is None,
                f"Sensor sees the ball through the cup window, lens gap {gap:.2f} mm."
                if hit is None
                else f"Cup material {hit:.2f} mm under the ball blocks the sensor.",
                measured=round(gap, 3),
                limit=round(gap, 3),
                unit="mm",
                started=s,
                **kw,
            )
        )

    # 6. screens visible through the window
    tilt = math.radians(LIMITS["screen_tilt_deg"])
    for f in feats:
        if f.role != "screen":
            continue
        s = time.perf_counter()
        _, z_hi = f.z_range(t)
        a = math.radians(f.rot_deg)
        rot = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
        seen = n = 0
        for u in np.linspace(-0.45, 0.45, 9):
            for w in np.linspace(-0.45, 0.45, 9):
                xy = rot @ np.array([u * f.w, w * f.d]) + np.array([f.x, f.y])
                o = np.array([xy[0], xy[1], z_hi + 0.01])
                for d in (np.array([0, 0, 1.0]), np.array([0, -math.sin(tilt), math.cos(tilt)])):
                    n += 1
                    if _first_hit(case, o, d, LIMITS["ray_length_mm"]) is None:
                        seen += 1
        frac = seen / n
        checks.append(
            _check(
                "mech.view.screen",
                f.ref,
                frac >= LIMITS["screen_visible_fraction"],
                f"Screen {f.ref} visible through the window: {seen}/{n} rays.",
                measured=round(frac, 3),
                limit=LIMITS["screen_visible_fraction"],
                unit="fraction",
                started=s,
                fix="Open the bezel window over the screen.",
                **kw,
            )
        )

    # 7. ports and controls reachable
    for o in report.openings.get("usb", []):
        s = time.perf_counter()
        f = next(x for x in feats if x.ref == o["ref"])
        dx, dy = {"pos_x": (1, 0), "neg_x": (-1, 0), "pos_y": (0, 1), "neg_y": (0, -1)}[o["face"]]
        blocked = 0
        rays = 0
        for a in (-2.5, 0.0, 2.5):
            for b in (-1.0, 0.0, 1.0):
                rays += 1
                origin = np.array([f.x + (-dy) * a, f.y + dx * a, o["z"] + b])
                if _first_hit(case, origin, np.array([dx, dy, 0.0]), 200.0) is not None:
                    blocked += 1
        checks.append(
            _check(
                "mech.access.panel",
                f"usb_{f.ref}",
                blocked == 0,
                f"USB on {f.ref} reachable through the {o['face']} wall: {rays - blocked}/{rays} "
                "rays clear."
                if blocked == 0
                else f"USB on {f.ref} is blocked by the case wall: {blocked}/{rays} rays hit.",
                measured=rays - blocked,
                limit=rays,
                unit="rays",
                started=s,
                fix="Cut a USB opening in the wall the connector faces.",
                **kw,
            )
        )
    for f in feats:
        if f.role != "encoder":
            continue
        s = time.perf_counter()
        _, z_hi = f.z_range(t)
        r = max(f.w, f.d) / 2
        blocked = sum(
            1
            for a in np.linspace(0, 2 * math.pi, 8, endpoint=False)
            if _first_hit(
                case,
                np.array([f.x + r * math.cos(a), f.y + r * math.sin(a), lv["top"] + 0.2]),
                np.array([0, 0, 1.0]),
                100.0,
            )
            is not None
        )
        checks.append(
            _check(
                "mech.access.panel",
                f"encoder_{f.ref}",
                blocked == 0,
                f"Encoder {f.ref} shaft and knob clear of the bezel ({8 - blocked}/8 rays)."
                if blocked == 0
                else f"Bezel overhangs encoder {f.ref}: {blocked}/8 rays hit.",
                measured=8 - blocked,
                limit=8,
                unit="rays",
                started=s,
                **kw,
            )
        )

    # 8. cables long enough
    by_ref = {f.ref: f for f in feats}
    for cab in report.board.get("cables") or []:
        s = time.perf_counter()
        a, b = by_ref.get(cab.get("from_ref")), by_ref.get(cab.get("to_ref"))
        length = float(cab.get("length_mm") or 0)
        subject = f"{cab.get('from_ref')}_{cab.get('to_ref')}"
        if not a or not b:
            checks.append(
                _check(
                    "mech.cable.length",
                    subject,
                    None,
                    "Cable end not found among the placements.",
                    limit=length,
                    unit="mm",
                    started=s,
                    **kw,
                )
            )
            continue
        za = sum(a.z_range(t)) / 2
        zb = sum(b.z_range(t)) / 2
        straight = math.dist((a.x, a.y, za), (b.x, b.y, zb))
        routed = abs(a.x - b.x) + abs(a.y - b.y) + abs(za - zb)
        checks.append(
            _check(
                "mech.cable.length",
                subject,
                routed <= length,
                f"Cable {subject}: straight {straight:.1f} mm, routed {routed:.1f} mm vs "
                f"{length:.0f} mm cable.",
                measured=round(routed, 2),
                limit=length,
                unit="mm",
                started=s,
                **kw,
            )
        )
    return checks
