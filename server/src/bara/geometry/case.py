"""enclose stage: a two-piece case (tray + bezel) built around a KiCad board outline.

Every dimension comes from the board record (Edge.Cuts outline, thickness, placements with
footprint sizes and part heights). The numbers that do not come from a record are hand-set
and live in HAND_SET below, so they can be listed honestly.

Frames: the board frame is build space before tenting (mm, Z up, board bottom at z = 0,
outline already in build X/Y). The returned transform maps the board frame to build space
(tent rotation about the outer bottom edge, then a lift so the case sits on the desk).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import manifold3d as mf
import numpy as np

from bara.config import load_settings
from bara.geometry.meshio import MeshPart, write_3mf, write_glb, write_stl

# Hand-set constants (not derived from a part record or a measurement). One table, on purpose.
HAND_SET: dict[str, float] = {
    "wall_mm": 3.0,  # tray side wall thickness
    "floor_mm": 2.5,  # tray floor under the deepest pocket
    "wall_top_mm": 3.6,  # tray wall top above the board top surface (bezel seat)
    "bezel_top_mm": 5.1,  # bezel top above the board top surface
    "fillet_mm": 2.0,  # outer corner rounding of the plan outline
    "tray_clearance_mm": 0.5,  # board edge to inner tray wall
    "floor_clearance_mm": 0.5,  # bottom-side part to pocket floor
    "pocket_clearance_mm": 0.5,  # bottom-side part to pocket side (battery 0.5 in v4)
    "key_opening_clearance_mm": 0.5,  # keycap edge to bezel opening
    "part_opening_clearance_mm": 0.5,  # any other tall top part to bezel opening
    "encoder_clearance_mm": 1.5,  # encoder body circumcircle to bezel hole
    "ball_clearance_mm": 0.5,  # ball surface to cup inner surface
    "ball_ring_clearance_mm": 0.15,  # ball to bezel ring (radial)
    "cup_wall_mm": 2.0,  # trackball cup shell thickness
    "ball_exposed_fraction": 0.45,  # of the ball diameter above the bezel, when no height given
    "lens_gap_mm": 2.4,  # ball bottom to sensor lens (PMW3360 datasheet 2.4 +-0.3, typed in)
    "sensor_window_d_mm": 9.0,  # through-hole in the cup bottom for the sensor optics
    "sensor_pocket_depth_mm": 6.0,  # sensor + its PCB below the window, when no part given
    "usb_opening_w_mm": 12.0,  # USB-C plug overmold clearance width
    "usb_opening_h_mm": 7.0,  # USB-C plug overmold clearance height
    "keycap_fallback_w_mm": 18.0,  # keycap footprint when no keycap placement exists
    "keycap_fallback_d_mm": 18.0,
    "tent_deg": 8.0,  # when the brief asks for tenting without an angle
    "pcb_thickness_mm": 1.6,  # only when the board record has no thickness
    "explode_bezel_mm": 25.0,  # explode offset of the bezel above the tray
    "explode_case_mm": -30.0,  # explode offset of the whole case
    "circular_segments": 48,
}

TOUCH_MIN_MM = 9.0  # smallest opening for a part a person touches
DEFAULT_CASE_HEX = "#9E9E9E"

# Roles taller than the bezel underside get an opening; these keep their own opening shape.
ROLE_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("keycap", ("keycap",)),
    ("knob", ("knob",)),
    ("trackball", ("trackball", "ball")),
    ("encoder", ("rotary_encoder", "encoder", "ec11", "ec12")),
    ("screen", ("oled", "display", "lcd", "ssd1306", "screen", "epaper", "tft")),
    ("sensor", ("pmw", "paw3", "optical_sensor")),
    ("battery", ("battery", "lipo", "li-po", "18650", "cr2032")),
    ("usb", ("usb",)),
    (
        "mcu",
        (
            "xiao",
            "nice_nano",
            "nicenano",
            "promicro",
            "pro_micro",
            "rp2040",
            "esp32",
            "mcu",
            "pico",
            "blackpill",
            "module",
        ),
    ),
    (
        "switch",
        (
            "sw_choc",
            "choc",
            "kailh",
            "cherry",
            "sw_mx",
            "mx_",
            "gateron",
            "hotswap",
            "pg1350",
            "pg1353",
            "switch_keyboard",
            "sw_push",
        ),
    ),
]
FUNCTION_ROLES = {
    "input.key": "switch",
    "input.key_matrix": "switch",
    "mech.keycap": "keycap",
    "input.rotary_encoder": "encoder",
    "mech.knob": "knob",
    "input.trackball": "trackball",
    "power.battery": "battery",
    "compute.mcu": "mcu",
    "power.usb_in": "usb",
    "comms.usb_device": "usb",
}
STACKED_ROLES = {
    ("keycap", "switch"),
    ("knob", "encoder"),
    ("trackball", "sensor"),
    ("usb", "mcu"),
}
HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


@dataclass
class Feature:
    ref: str
    role: str
    x: float
    y: float
    rot_deg: float
    side: str  # top | bottom
    height: float  # above the top surface (top) or below the bottom surface (bottom)
    w: float
    d: float
    lib_id: str = ""
    source_url: str = ""
    licence: str = ""
    z_bottom: float | None = None  # explicit lower z in the board frame, when known
    z_top: float | None = None  # explicit upper z (parts off the board, e.g. a ball sensor)
    touch: bool = False  # a person touches or looks at it: it gets an opening in the shell

    def z_range(self, t: float) -> tuple[float, float]:
        if self.z_bottom is not None and self.z_top is not None:
            return self.z_bottom, self.z_top
        if self.side == "bottom":
            return -self.height, 0.0
        lo = t if self.z_bottom is None else self.z_bottom
        return lo, t + self.height


@dataclass
class EncloseReport:
    enclosure: dict[str, Any]
    tray: mf.Manifold
    bezel: mf.Manifold
    transform: np.ndarray  # 4x4 board frame -> build space
    board: dict[str, Any]
    features: list[Feature]
    thickness: float
    outline: np.ndarray
    holes: list[np.ndarray]
    levels: dict[str, float]
    openings: dict[str, Any] = field(default_factory=dict)
    timings_ms: dict[str, float] = field(default_factory=dict)
    checks: list[dict[str, Any]] = field(default_factory=list)
    world_tray: mf.Manifold | None = None  # final build-space meshes (tented, on the desk)
    world_bezel: mf.Manifold | None = None

    def board_pose(self) -> tuple[list[float], list[float]]:
        """position_mm / rotation_deg for the board (its frame origin) in build space."""
        return pose_from_matrix(self.transform)

    def place(
        self, position_mm: list[float], rotation_deg: list[float]
    ) -> tuple[list[float], list[float]]:
        """Map a board-frame pose (SPEC 3.2 Euler XYZ) into tented build space."""
        m = np.eye(4)
        m[:3, :3] = euler_xyz_matrix(rotation_deg)
        m[:3, 3] = position_mm
        return pose_from_matrix(self.transform @ m)


# ---------------------------------------------------------------- small maths


def euler_xyz_matrix(deg: list[float]) -> np.ndarray:
    x, y, z = (math.radians(float(a)) for a in deg)
    cx, sx, cy, sy, cz, sz = (
        math.cos(x),
        math.sin(x),
        math.cos(y),
        math.sin(y),
        math.cos(z),
        math.sin(z),
    )
    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return rx @ ry @ rz


def pose_from_matrix(m: np.ndarray) -> tuple[list[float], list[float]]:
    r = m[:3, :3]
    y = math.asin(max(-1.0, min(1.0, r[0, 2])))
    if abs(r[0, 2]) < 0.9999999:
        x = math.atan2(-r[1, 2], r[2, 2])
        z = math.atan2(-r[0, 1], r[0, 0])
    else:
        x = math.atan2(r[2, 1], r[1, 1])
        z = 0.0
    pos = [round(float(v), 4) for v in m[:3, 3]]
    return pos, [round(math.degrees(a), 4) for a in (x, y, z)]


def _rot2(deg: float) -> np.ndarray:
    a = math.radians(deg)
    return np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])


def rect_corners(cx: float, cy: float, w: float, d: float, rot_deg: float) -> np.ndarray:
    local = np.array([[-w / 2, -d / 2], [w / 2, -d / 2], [w / 2, d / 2], [-w / 2, d / 2]])
    return local @ _rot2(rot_deg).T + np.array([cx, cy])


def point_in_polygon(px: float, py: float, poly: np.ndarray) -> bool:
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > py) != (y2 > py):
            xc = x1 + (py - y1) * (x2 - x1) / (y2 - y1)
            if px < xc:
                inside = not inside
    return inside


def _ccw(poly: np.ndarray) -> np.ndarray:
    area = 0.5 * float(
        np.sum(poly[:, 0] * np.roll(poly[:, 1], -1) - np.roll(poly[:, 0], -1) * poly[:, 1])
    )
    return poly if area > 0 else poly[::-1]


# ---------------------------------------------------------------- inputs


def infer_role(*texts: str | None) -> str:
    blob = " ".join(t.lower() for t in texts if t)
    for role, words in ROLE_KEYWORDS:
        if any(w in blob for w in words):
            return role
    return "other"


def _num(value: Any, default: float) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _feature_from_placement(p: dict[str, Any]) -> Feature | None:
    size = p.get("size_mm") or [0, 0]
    role = p.get("role") or infer_role(p.get("lib_id"), p.get("ref"))
    if role not in {r for r, _ in ROLE_KEYWORDS} and role != "other":
        role = infer_role(role, p.get("lib_id"))
    w, d = _num(size[0], 0.0), _num(size[1] if len(size) > 1 else size[0], 0.0)
    if w <= 0 or d <= 0:
        return None
    return Feature(
        ref=str(p.get("ref") or p.get("instance_id") or role),
        role=role,
        x=_num(p.get("x_mm"), 0.0),
        y=_num(p.get("y_mm"), 0.0),
        rot_deg=_num(p.get("rot_deg"), 0.0),
        side="bottom" if p.get("side") == "bottom" else "top",
        height=max(0.0, _num(p.get("height_mm"), 0.0)),
        w=w,
        d=d,
        lib_id=str(p.get("lib_id") or ""),
        source_url=str(p.get("source_url") or ""),
        licence=str(p.get("licence") or ""),
        z_bottom=None if p.get("z_bottom_mm") is None else _num(p.get("z_bottom_mm"), 0.0),
        touch=bool(p.get("touch")),
    )


def _layout_positions(item: dict[str, Any]) -> list[tuple[float, float, float]]:
    """SPEC 3.3 layout math, in the plane: (x, y, yaw_deg) per element."""
    pl = item.get("placement") or {}
    layout = item.get("layout") or {}
    px, py = _num(layout.get("pitch_x_mm"), 19.05), _num(layout.get("pitch_y_mm"), 19.05)
    ox, oy = (pl.get("position_mm") or [0, 0, 0])[:2]
    yaw0 = _num((pl.get("rotation_deg") or [0, 0, 0])[2], 0.0)
    out = []
    for k in sorted(layout.get("keys") or [], key=lambda k: k.get("i", 0)):
        w_u, h_u = _num(k.get("w_u"), 1), _num(k.get("h_u"), 1)
        c = np.array([(k["x_u"] + w_u / 2) * px, -(k["y_u"] + h_u / 2) * py])
        piv = np.array([_num(k.get("rx_u"), 0) * px, -_num(k.get("ry_u"), 0) * py])
        r = _num(k.get("r_deg"), 0)
        c = (c - piv) @ _rot2(-r).T + piv
        c = c @ _rot2(yaw0).T + np.array([ox, oy])
        out.append((float(c[0]), float(c[1]), yaw0 - r))
    return out


def _features_from_parts(parts: list[dict[str, Any]], t: float) -> list[Feature]:
    out: list[Feature] = []
    for item in parts:
        card = item.get("card") or {}
        role = item.get("role") or FUNCTION_ROLES.get(
            str(item.get("function") or card.get("primary_function") or "")
        )
        if not role:
            role = infer_role(item.get("lib_id"), item.get("part_id"), card.get("display_name"))
        if role == "other":
            continue
        bbox = item.get("bbox_mm") or ((item.get("mechanical") or {}).get("bbox_mm")) or {}
        lo, hi = bbox.get("min"), bbox.get("max")
        size = item.get("size_mm")
        if size is None and lo and hi:
            size = [hi[0] - lo[0], hi[1] - lo[1]]
        if not size:
            continue
        pl = item.get("placement") or {}
        if pl.get("mode") == "layout" and item.get("layout"):
            poses = _layout_positions(item)
        else:
            pos = pl.get("position_mm") or [item.get("x_mm", 0), item.get("y_mm", 0), 0]
            yaw = _num((pl.get("rotation_deg") or [0, 0, item.get("rot_deg", 0)])[2], 0.0)
            poses = [(_num(pos[0], 0), _num(pos[1], 0), yaw)]
        top = _num(item.get("height_mm"), _num((hi or [0, 0, 0])[2], 0.0))
        z_lo = None
        if lo and hi and pl.get("position_mm") is not None:
            z_lo = _num(pl["position_mm"][2], t) + _num(lo[2], 0.0)
            top = _num(pl["position_mm"][2], t) + _num(hi[2], 0.0) - t
        for i, (x, y, yaw) in enumerate(poses):
            out.append(
                Feature(
                    ref=f"{item.get('instance_id') or item.get('ref') or role}"
                    + (f"[{i}]" if len(poses) > 1 else ""),
                    role=role,
                    x=x,
                    y=y,
                    rot_deg=yaw,
                    side="bottom" if item.get("side") == "bottom" else "top",
                    height=max(0.0, top),
                    w=_num(size[0], 0.0),
                    d=_num(size[1], 0.0),
                    lib_id=str(item.get("lib_id") or ""),
                    source_url=str(card.get("source_url") or item.get("source_url") or ""),
                    licence=str(card.get("licence_spdx") or item.get("licence") or ""),
                    z_bottom=z_lo,
                )
            )
    return out


def collect_features(board: dict[str, Any], parts: list[dict[str, Any]]) -> list[Feature]:
    t = _num(board.get("thickness_mm"), HAND_SET["pcb_thickness_mm"])
    feats = [f for p in board.get("placements") or [] if (f := _feature_from_placement(p))]
    for extra in _features_from_parts(parts, t):
        dup = any(
            f.role == extra.role and abs(f.x - extra.x) < 1.0 and abs(f.y - extra.y) < 1.0
            for f in feats
        )
        if not dup:
            feats.append(extra)
    return feats


def case_color(brief: dict[str, Any]) -> tuple[str, str]:
    colors = brief.get("colors") or brief.get("colours") or {}
    candidates: list[Any] = []
    if isinstance(colors, dict):
        candidates += [colors.get(k) for k in ("case", "case_color", "body", "primary")]
    elif isinstance(colors, list):
        candidates += colors[:1]
    candidates += [brief.get("case_color"), brief.get("case_colour")]
    for c in candidates:
        if isinstance(c, dict):
            c = c.get("hex")
        if isinstance(c, str) and HEX_RE.match(c):
            return c.upper(), "user"
    return DEFAULT_CASE_HEX, "default"


def tent_angle(brief: dict[str, Any]) -> float:
    if brief.get("tent_deg") is not None:
        return max(0.0, min(30.0, _num(brief.get("tent_deg"), 0.0)))
    tent = brief.get("tenting", brief.get("tented"))
    feats = brief.get("features")
    if isinstance(feats, dict):
        tent = tent or feats.get("tenting") or feats.get("tented")
    elif isinstance(feats, list):
        tent = tent or any(str(f).lower().startswith("tent") for f in feats)
    if isinstance(tent, int | float) and not isinstance(tent, bool):
        return max(0.0, min(30.0, float(tent)))
    return HAND_SET["tent_deg"] if tent else 0.0


def board_side(board: dict[str, Any], outline: np.ndarray) -> str | None:
    side = board.get("side")
    if side in ("left", "right"):
        return side
    if "side" in board:  # explicit "none"/null: a single board, never guess a half
        return None
    bid = str(board.get("board_id") or "")
    if bid.endswith(("_l", "_left")):
        return "left"
    if bid.endswith(("_r", "_right")):
        return "right"
    cx = float(outline[:, 0].mean())
    return None if abs(cx) < 1.0 else ("left" if cx < 0 else "right")


# ---------------------------------------------------------------- geometry


def _prism(cs: mf.CrossSection, z0: float, z1: float) -> mf.Manifold:
    if z1 <= z0:
        return mf.Manifold()
    return mf.Manifold.extrude(cs, z1 - z0).translate((0, 0, z0))


def _rect_cs(cx: float, cy: float, w: float, d: float, rot: float) -> mf.CrossSection:
    return mf.CrossSection([rect_corners(cx, cy, w, d, rot).tolist()])


def _circle_cs(cx: float, cy: float, r: float) -> mf.CrossSection:
    return mf.CrossSection.circle(r, int(HAND_SET["circular_segments"])).translate((cx, cy))


def _box(lo: tuple[float, float, float], hi: tuple[float, float, float]) -> mf.Manifold:
    size = tuple(h - lo_ for lo_, h in zip(lo, hi, strict=True))
    return mf.Manifold.cube(size).translate(lo)


def _soft_edge(
    cs: mf.CrossSection, z0: float, z1: float, rise: float, width: float, bottom: bool
) -> mf.Manifold:
    """A prism of cs from z0 to z1 whose bottom (or top) edge is rounded: a quarter-circle
    profile `rise` tall and `width` in from the outline, built as thin stepped slices."""
    steps = 8
    solids: list[mf.Manifold] = []
    if bottom:
        solids.append(_prism(cs, z0 + rise, z1))
    else:
        solids.append(_prism(cs, z0, z1 - rise))
    for i in range(steps):
        a, b = rise * i / steps, rise * (i + 1) / steps
        mid = (a + b) / 2
        u = (rise - mid) / rise if bottom else mid / rise
        inset = width * (1.0 - math.sqrt(max(0.0, 1.0 - u * u)))
        ring = cs.offset(-inset, mf.JoinType.Round) if inset > 1e-6 else cs
        if ring.is_empty():
            continue
        if bottom:
            solids.append(_prism(ring, z0 + a, z0 + b + 0.01))
        else:
            solids.append(_prism(ring, z1 - rise + a, z1 - rise + b + 0.01))
    return _union(solids)


def _union(items: list[mf.Manifold]) -> mf.Manifold:
    items = [m for m in items if not m.is_empty()]
    if not items:
        return mf.Manifold()
    return mf.Manifold.batch_boolean(items, mf.OpType.Add) if len(items) > 1 else items[0]


FACE_DIR = {"pos_x": (1, 0), "neg_x": (-1, 0), "pos_y": (0, 1), "neg_y": (0, -1)}


def _hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def enclosure_dir() -> Path:
    return load_settings().assets_dir / "cache" / "enclosures"


def mesh_part(name: str, m: mf.Manifold, transform: np.ndarray, hex_color: str) -> MeshPart:
    mesh = m.calculate_normals(3, 40.0).to_mesh(3)
    props = np.asarray(mesh.vert_properties, dtype=np.float64)
    v = props[:, :3] @ transform[:3, :3].T + transform[:3, 3]
    n = props[:, 3:6] @ transform[:3, :3].T
    return MeshPart(name, v, np.asarray(mesh.tri_verts, dtype=np.int64), n, hex_color)


def enclose_report(
    board: dict[str, Any], parts_with_poses: list[dict[str, Any]], brief: dict[str, Any]
) -> EncloseReport:
    from bara.geometry.validate import validate  # local: validate imports this module

    t_start = time.perf_counter()
    H = HAND_SET
    mf.set_circular_segments(int(H["circular_segments"]))
    outline = _ccw(np.asarray(board["outline"], dtype=np.float64)[:, :2])
    holes = [np.asarray(h, dtype=np.float64)[:, :2] for h in board.get("holes") or []]
    t = _num(board.get("thickness_mm"), H["pcb_thickness_mm"])
    feats = collect_features(board, parts_with_poses)
    side = board_side(board, outline)
    hex_color, color_source = case_color(brief)
    tent = tent_angle(brief)

    board_cs = mf.CrossSection([outline.tolist()])
    inner_cs = board_cs.offset(H["tray_clearance_mm"], mf.JoinType.Miter)
    outer_cs = (
        board_cs.offset(H["tray_clearance_mm"] + H["wall_mm"], mf.JoinType.Round)
        .offset(-H["fillet_mm"], mf.JoinType.Round)
        .offset(H["fillet_mm"], mf.JoinType.Round)
    )

    top = t  # board top surface
    wall_top = top + H["wall_top_mm"]
    bezel_top = top + H["bezel_top_mm"]

    # Pockets for bottom-side parts; the floor goes under the deepest one.
    pockets: list[mf.Manifold] = []
    deepest = 0.0
    for f in feats:
        if f.side != "bottom" or f.height <= 0 or f.role == "sensor":
            continue
        depth = f.height + H["floor_clearance_mm"]
        deepest = max(deepest, depth)
        c = H["pocket_clearance_mm"] * 2
        pockets.append(_prism(_rect_cs(f.x, f.y, f.w + c, f.d + c, f.rot_deg), -depth, 0.01))

    balls = [f for f in feats if f.role == "trackball"]
    ball_geo: list[dict[str, float]] = []
    z_bot = -deepest - H["floor_mm"]
    for b in balls:
        r = max(b.w, b.d) / 2
        ball_top = top + (
            b.height if b.height > 0 else H["bezel_top_mm"] + H["ball_exposed_fraction"] * 2 * r
        )
        cz = ball_top - r
        sensor = next(
            (s for s in feats if s.role == "sensor" and math.hypot(s.x - b.x, s.y - b.y) < r), None
        )
        sensor_depth = (
            sensor.height if sensor and sensor.height > 0 else H["sensor_pocket_depth_mm"]
        )
        lens_z = cz - r - H["lens_gap_mm"]
        pocket_bottom = lens_z - sensor_depth - H["floor_clearance_mm"]
        if sensor:  # the sensor hangs in its own pocket under the cup, off the main board
            sensor.z_bottom = pocket_bottom + H["floor_clearance_mm"]
            sensor.z_top = lens_z
        ball_geo.append(
            {
                "x": b.x,
                "y": b.y,
                "cz": cz,
                "r": r,
                "lens_z": lens_z,
                "pocket_bottom": pocket_bottom,
                "sw": (sensor.w if sensor else H["sensor_window_d_mm"] + 4),
                "sd": (sensor.d if sensor else H["sensor_window_d_mm"] + 4),
                # the sensor body's own centre and angle (its lens sits under the ball)
                "sx": sensor.x if sensor else b.x,
                "sy": sensor.y if sensor else b.y,
                "srot": sensor.rot_deg if sensor else 0.0,
            }
        )
        cup_bottom = cz - r - H["ball_clearance_mm"] - H["cup_wall_mm"]
        z_bot = min(z_bot, pocket_bottom - H["floor_mm"], cup_bottom)

    # The product's own thickness (from its form) sets the body height; the board stays at the
    # top, with the extra body below it.
    body = _num(brief.get("body_thickness_mm"), 0.0)
    if body > 0 and body > bezel_top - z_bot:
        z_bot = bezel_top - body

    t_geo = time.perf_counter()
    # ---- tray
    shaped = body > 0
    soft = min(8.0, 0.3 * (wall_top - z_bot)) if shaped else 0.0
    if shaped:
        # the belly of the product: a rounded underside, as deep as the body is thicker than
        # its rim (grips thicker than the edge), never less than the fillet radius
        edge = _num(brief.get("edge_thickness_mm"), 0.0)
        rise = min(max(body - edge, 0.5 * soft, 3.0), 0.5 * (wall_top - z_bot))
        solids = [_soft_edge(outer_cs, z_bot, wall_top, rise, min(rise * 1.2, 8.0), True)]
    else:
        solids = [_prism(outer_cs, z_bot, wall_top)]
    for g in ball_geo:
        rr = g["r"] + H["ball_clearance_mm"] + H["cup_wall_mm"]
        solids.append(_prism(_circle_cs(g["x"], g["y"], rr), z_bot, wall_top))
    tray = _union(solids)
    cuts = [_prism(inner_cs, 0.0, wall_top + 1.0), *pockets]
    tray = tray - _union(cuts)
    for g in ball_geo:
        rin = g["r"] + H["ball_clearance_mm"]
        shell = mf.Manifold.sphere(rin + H["cup_wall_mm"]).translate((g["x"], g["y"], g["cz"]))
        shell = shell.trim_by_plane((0, 0, -1), -g["cz"])  # keep z <= centre
        tray = tray + shell
        tray = tray - mf.Manifold.sphere(rin).translate((g["x"], g["y"], g["cz"]))
        tray = tray - _prism(_circle_cs(g["x"], g["y"], rin), g["cz"], wall_top + 1.0)
        tray = tray - _prism(
            _circle_cs(g["x"], g["y"], H["sensor_window_d_mm"] / 2), g["pocket_bottom"], g["cz"]
        )
        c = H["pocket_clearance_mm"] * 2
        tray = tray - _prism(
            _rect_cs(g["sx"], g["sy"], g["sw"] + c, g["sd"] + c, g["srot"]),
            g["pocket_bottom"],
            g["lens_z"],
        )

    # ---- bezel openings
    seat = wall_top
    holes_cs: list[mf.CrossSection] = []
    openings: dict[str, Any] = {"keys": 0, "encoders": [], "screens": [], "usb": []}
    keycaps = [f for f in feats if f.role == "keycap"]
    for f in feats:
        z_lo, z_hi = f.z_range(t)
        if f.side == "bottom" or f.role in ("trackball", "sensor"):
            continue
        if f.role == "switch":
            if keycaps:
                continue
            cw, cd = max(f.w, H["keycap_fallback_w_mm"]), max(f.d, H["keycap_fallback_d_mm"])
            c = 2 * H["key_opening_clearance_mm"]
            holes_cs.append(_rect_cs(f.x, f.y, cw + c, cd + c, f.rot_deg))
            openings["keys"] += 1
        elif f.role == "keycap":
            c = 2 * H["key_opening_clearance_mm"]
            holes_cs.append(_rect_cs(f.x, f.y, f.w + c, f.d + c, f.rot_deg))
            openings["keys"] += 1
        elif f.role in ("encoder", "knob"):
            r = math.hypot(f.w, f.d) / 2 + H["encoder_clearance_mm"]
            if f.role == "knob":
                r = max(f.w, f.d) / 2 + H["encoder_clearance_mm"]
            holes_cs.append(_circle_cs(f.x, f.y, r))
            openings["encoders"].append({"ref": f.ref, "r": r})
        elif f.role == "screen":
            holes_cs.append(_rect_cs(f.x, f.y, f.w, f.d, f.rot_deg))
            openings["screens"].append(f.ref)
        elif f.touch and f.role not in ("usb", "mcu", "battery"):
            # finger-sized, soft-cornered: a bare switch footprint is far smaller than the
            # button a person presses
            c = 2 * H["part_opening_clearance_mm"]
            ow, od = max(f.w + c, TOUCH_MIN_MM), max(f.d + c, TOUCH_MIN_MM)
            r = 0.4 * min(ow, od)
            holes_cs.append(
                _rect_cs(f.x, f.y, ow, od, f.rot_deg)
                .offset(-r, mf.JoinType.Round)
                .offset(r, mf.JoinType.Round)
            )
        elif z_hi > seat - 0.01:
            c = 2 * H["part_opening_clearance_mm"]
            holes_cs.append(_rect_cs(f.x, f.y, f.w + c, f.d + c, f.rot_deg))
    for g in ball_geo:
        holes_cs.append(_circle_cs(g["x"], g["y"], g["r"] + H["ball_ring_clearance_mm"]))
    crown = 0.0
    if shaped:
        bx = outer_cs.bounds()
        crown = max(1.5, min(4.0, 0.12 * min(bx[2] - bx[0], bx[3] - bx[1])))
        bezel = _soft_edge(outer_cs, seat, bezel_top + crown, crown, crown * 1.1, False)
    else:
        bezel = _prism(outer_cs, seat, bezel_top)
    if holes_cs:
        bezel = bezel - _prism(
            mf.CrossSection.batch_boolean(holes_cs, mf.OpType.Add)
            if len(holes_cs) > 1
            else holes_cs[0],
            seat - 1,
            bezel_top + crown + 1,
        )
    if shaped and holes_cs:
        # raised collars around every opening: stick wells, button bosses, a d-pad crown
        opened = mf.CrossSection.batch_boolean(holes_cs, mf.OpType.Add)
        collar = mf.CrossSection.batch_boolean(
            [opened.offset(2.2, mf.JoinType.Round), opened], mf.OpType.Subtract
        )
        collar = mf.CrossSection.batch_boolean(
            [collar, outer_cs.offset(-crown * 1.2, mf.JoinType.Round)], mf.OpType.Intersect
        )
        if not collar.is_empty():
            bezel = bezel + _prism(collar, bezel_top + crown - 0.05, bezel_top + crown + 1.6)

    # ---- USB openings through the wall (tray and bezel)
    cutouts: list[dict[str, Any]] = []
    usb_feats = [f for f in feats if f.role == "usb"] or [f for f in feats if f.role == "mcu"]
    for f in usb_feats:
        face, exit_s = _port_exit(f.x, f.y, outer_cs)
        dx, dy = FACE_DIR[face]
        z_lo, z_hi = f.z_range(t)
        zc = (top + max(z_hi, top + 1.0)) / 2 if f.side == "top" else (z_lo + 0.0) / 2
        reach = exit_s + 1.0  # through the wall and no further
        w, h = H["usb_opening_w_mm"], H["usb_opening_h_mm"]
        if dx:
            cs = mf.CrossSection([[[0, -w / 2], [reach, -w / 2], [reach, w / 2], [0, w / 2]]])
            cs = cs.scale((dx, 1)).translate((f.x, f.y))
        else:
            cs = mf.CrossSection([[[-w / 2, 0], [w / 2, 0], [w / 2, reach], [-w / 2, reach]]])
            cs = cs.scale((1, dy)).translate((f.x, f.y))
        cutter = _prism(cs, zc - h / 2, zc + h / 2)
        tray = tray - cutter
        bezel = bezel - cutter
        wall_hit = (f.x + dx * exit_s, f.y + dy * exit_s)
        center = [round(wall_hit[0], 3), round(wall_hit[1], 3), round(zc, 3)]
        openings["usb"].append({"ref": f.ref, "face": face, "center": center, "z": zc})
        cutouts.append(
            {
                "cutout_id": f"cut_usb_{_slug(f.ref)}",
                "feature": "usb_c",
                "face": face,
                "shape": "slot",
                "center_mm": center,
                "size_mm": [w, h],
            }
        )
    for o in openings["encoders"]:
        f = next(x for x in feats if x.ref == o["ref"])
        cutouts.append(
            {
                "cutout_id": f"cut_enc_{_slug(f.ref)}",
                "feature": "encoder",
                "face": "pos_z",
                "shape": "circle",
                "center_mm": [round(f.x, 3), round(f.y, 3), round(bezel_top, 3)],
                "size_mm": [round(2 * o["r"], 3), round(2 * o["r"], 3)],
            }
        )
    for ref in openings["screens"]:
        f = next(x for x in feats if x.ref == ref)
        cutouts.append(
            {
                "cutout_id": f"cut_screen_{_slug(f.ref)}",
                "feature": "screen_window",
                "face": "pos_z",
                "shape": "rect",
                "center_mm": [round(f.x, 3), round(f.y, 3), round(bezel_top, 3)],
                "size_mm": [round(f.w, 3), round(f.d, 3)],
            }
        )
    for g in ball_geo:
        cutouts.append(
            {
                "cutout_id": f"cut_ball_{len(cutouts)}",
                "feature": "trackball",
                "face": "pos_z",
                "shape": "circle",
                "center_mm": [round(g["x"], 3), round(g["y"], 3), round(bezel_top, 3)],
                "size_mm": [round(2 * g["r"] + 2 * H["ball_ring_clearance_mm"], 3)] * 2,
            }
        )
        cutouts.append(
            {
                "cutout_id": f"cut_sensor_{len(cutouts)}",
                "feature": "sensor_window",
                "face": "neg_z",
                "shape": "circle",
                "center_mm": [round(g["x"], 3), round(g["y"], 3), round(g["lens_z"], 3)],
                "size_mm": [H["sensor_window_d_mm"]] * 2,
            }
        )

    # ---- tenting: rotate about the outer bottom edge, fill the wedge, lift to the desk
    xform = np.eye(4)
    if tent > 0:
        lo_x, lo_y, _, hi_x, hi_y, _ = tray.bounding_box()
        if side == "left":  # raise the inner (+x) edge: pivot at min x
            r = euler_xyz_matrix([0, -tent, 0])
            pivot = np.array([lo_x, 0, z_bot])
        elif side == "right":
            r = euler_xyz_matrix([0, tent, 0])
            pivot = np.array([hi_x, 0, z_bot])
        else:  # single board: raise the back (+y) edge, pivot at the front edge
            r = euler_xyz_matrix([tent, 0, 0])
            pivot = np.array([0, lo_y, z_bot])
        xform[:3, :3] = r
        xform[:3, 3] = pivot - r @ pivot
    m34 = xform[:3, :].tolist()
    tray_w = tray.transform(m34)
    bezel_w = bezel.transform(m34)
    if tent > 0:
        up = xform[:3, :3] @ np.array([0, 0, 1.0])
        p0 = xform[:3, :3] @ np.array([0, 0, z_bot]) + xform[:3, 3]
        foot = tray_w.project()
        lo = tray_w.bounding_box()[2]
        wedge = mf.Manifold.extrude(foot, 400.0).translate((0, 0, lo))
        wedge = wedge.trim_by_plane(tuple(-up), -float(up @ p0) - 0.05)
        wedge = wedge.trim_by_plane((0, 0, 1), lo)
        tray_w = tray_w + wedge
    lift = -tray_w.bounding_box()[2]
    tray_w = tray_w.translate((0, 0, lift))
    bezel_w = bezel_w.translate((0, 0, lift))
    xform[2, 3] += lift
    t_geo_ms = (time.perf_counter() - t_geo) * 1000

    # ---- files
    t_io = time.perf_counter()
    eid = "e_case_" + (_slug(side) if side else _slug(str(board.get("board_id") or "main")))[:50]
    key = _hash(
        {
            "outline": outline.round(4).tolist(),
            "holes": [h.tolist() for h in holes],
            "t": t,
            "feats": [f.__dict__ for f in feats],
            "color": hex_color,
            "tent": tent,
            "side": side,
            "hand": HAND_SET,
            "v": 2,
            "body": body,
            "edge": brief.get("edge_thickness_mm"),
        }
    )[:24]
    ident = np.eye(4)
    parts_mesh = [
        mesh_part(f"{eid}_tray", tray_w, ident, hex_color),
        mesh_part(f"{eid}_bezel", bezel_w, ident, hex_color),
    ]
    out_dir = enclosure_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    assets = []
    for kind, ext, role, ctype, writer in (
        ("glb", "glb", "model", "model/gltf-binary", write_glb),
        ("stl", "stl", "export", "model/stl", write_stl),
        ("3mf", "3mf", "export", "model/3mf", write_3mf),
    ):
        path = out_dir / f"{key}.{ext}"
        if not path.exists():
            data = writer(parts_mesh)
            tmp = path.with_suffix(f".{ext}.tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
        data = path.read_bytes()
        ref: dict[str, Any] = {
            "asset_id": f"a_{eid}_{key[:12]}_{ext}",
            "kind": kind,
            "role": role,
            "url": f"/assets/cache/enclosures/{key}.{ext}",
            "content_type": ctype,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "status": "ready",
            "origin": "generated",
        }
        if kind == "glb":
            ref["nodes"] = [p.name for p in parts_mesh]
        assets.append(ref)
    io_ms = (time.perf_counter() - t_io) * 1000

    lo3 = np.minimum(np.array(tray_w.bounding_box()[:3]), np.array(bezel_w.bounding_box()[:3]))
    hi3 = np.maximum(np.array(tray_w.bounding_box()[3:]), np.array(bezel_w.bounding_box()[3:]))
    enclosure: dict[str, Any] = {
        "enclosure_id": eid,
        "kind": "generated",
        "for_instance_ids": [],
        "params": {
            "wall_mm": H["wall_mm"],
            "floor_mm": H["floor_mm"],
            "fillet_mm": H["fillet_mm"],
            "clearance_mm": H["tray_clearance_mm"],
            "height_mm": round(float(hi3[2] - lo3[2]), 3),
            "split": "tray",
            "standoff_height_mm": 0.0,
        },
        "outer_size_mm": [round(float(v), 3) for v in (hi3 - lo3)],
        "position_mm": [0.0, 0.0, 0.0],
        "rotation_deg": [0.0, 0.0, 0.0],
        "explode_offset_mm": [0.0, 0.0, H["explode_case_mm"]],
        "cutouts": cutouts,
        "color": {"hex": hex_color, "material": "plastic", "node": None},
        "assets": assets,
        "status": "ok",
        "revision": 1,
        "material": "plastic",
        "color_source": color_source,
    }
    if side:
        enclosure["side"] = side
    report = EncloseReport(
        enclosure=enclosure,
        tray=tray,
        bezel=bezel,
        transform=xform,
        board=board,
        features=feats,
        thickness=t,
        outline=outline,
        holes=holes,
        levels={
            "top": top,
            "wall_top": wall_top,
            "bezel_top": bezel_top,
            "z_bot": z_bot,
            "tent_deg": tent,
        },
        openings={**openings, "balls": ball_geo},
        world_tray=tray_w,
        world_bezel=bezel_w,
    )
    report.timings_ms = {"geometry": round(t_geo_ms, 2), "files": round(io_ms, 2)}
    enclosure["duration_ms"] = int(round((time.perf_counter() - t_start) * 1000))
    t_val = time.perf_counter()
    report.checks = validate(report)
    report.timings_ms["validate"] = round((time.perf_counter() - t_val) * 1000, 2)
    report.timings_ms["total"] = round((time.perf_counter() - t_start) * 1000, 2)
    return report


def _crossings(x: float, y: float, dx: int, dy: int, outer: mf.CrossSection) -> list[float]:
    """Distances along a ray from (x, y) at which it crosses the outer plan outline."""
    out = []
    for poly in outer.to_polygons():
        p = np.asarray(poly)
        for i in range(len(p)):
            a, b = p[i], p[(i + 1) % len(p)]
            e = b - a
            den = dx * e[1] - dy * e[0]
            if abs(den) < 1e-12:
                continue
            w = a - np.array([x, y])
            s = (w[0] * e[1] - w[1] * e[0]) / den
            u = (w[0] * dy - w[1] * dx) / den
            if s >= 0 and 0 <= u < 1:
                out.append(float(s))
    return sorted(out)


def _port_exit(x: float, y: float, outer: mf.CrossSection) -> tuple[str, float]:
    """Face and distance for a port at (x, y): the axis ray that leaves the case for good
    soonest. A ray that leaves and re-enters (across a notch) would cut the case it crosses,
    so a single-crossing ray wins over a shorter re-entering one."""
    best: tuple[int, float, str] | None = None
    for face, (dx, dy) in FACE_DIR.items():
        hits = _crossings(x, y, dx, dy, outer)
        if not hits:
            continue
        cand = (0 if len(hits) == 1 else 1, hits[-1], face)
        if best is None or cand < best:
            best = cand
    if best is None:
        return "pos_y", 0.0
    return best[2], best[1]


def _slug(text: str) -> str:
    out = re.sub(r"[^a-z0-9_]+", "_", text.lower()).strip("_")
    return out or "x"


def enclose(
    board: dict[str, Any], parts_with_poses: list[dict[str, Any]], brief: dict[str, Any]
) -> dict[str, Any]:
    """SPEC 4.7 Enclosure (kind generated) with the case GLB/STL/3MF asset refs."""
    return enclose_report(board, parts_with_poses, brief).enclosure
