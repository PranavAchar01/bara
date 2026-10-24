"""Brief -> boards: key points, matrix, pin budget, feature placement, outlines.

All geometry is in the KiCad board frame (x right, y down, mm). Splits are laid out as the
left half and mirrored for the right half. No per-prompt branches: every keyboard comes
from the same rules (normalize -> grid -> thumbs -> features -> netlist -> outline).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from shapely import affinity
from shapely.geometry import MultiPolygon, Point, Polygon, box
from shapely.ops import unary_union

from . import registry as R
from .libs import FootprintInfo, footprint_ref, symbol_pins

# hand-set layout defaults (listed in registry.HAND_SET)
STAGGER_PROFILE = [0.0, 0.25, 0.5, 0.25, 0.125, 0.0, 0.0, 0.0]  # in key pitches, outer -> inner
THUMB_FAN_DEG = 9.0
BOARD_MARGIN = 1.0
CLOSE_RADIUS = 12.0  # fills necks between parts so traces have room
EDGE_BAND = 0.45
HALF_GAP_MM = 40.0  # gap between the inner edges of split halves in build space
CUP_WALL_MM = 4.0  # keep-out ring around the trackball for its cup
FEATURE_GAP = 1.5
SMALL_BOARD_MARGIN = 2.0
CUTOUT_RING = 2.0  # board kept around a footprint's own cutout (e.g. the PMW3360 lens slot)
KEY_CLEARANCE = 0.6  # copper/courtyard gap between neighbouring switch footprints
# Fanned thumb keycaps keep this gap to each other and to the grid: with the case's 0.5 mm
# opening clearance per side it leaves a 2 mm bezel web, wide enough to print and joined to
# the rest of the bezel (a thinner gap left a loose 2 mm sliver between thumb caps).
THUMB_CAP_GAP = 3.0
# The case bezel opens a circle of (body circumradius + 1.5 mm, GEOMETRY encoder_clearance)
# around an encoder; the board keeps this much more beyond it so the bezel ring stays whole.
ENCODER_OPENING_MM = 1.5
OPENING_RING_MM = 1.0


# ---------------------------------------------------------------- brief


@dataclass
class Feature:
    kind: str  # knob | screen | trackball
    hint: str = ""  # free text position hint, e.g. "top left", "right thumb"


@dataclass
class Brief:
    key_count: int
    split: bool
    style: str  # split | unibody | macropad
    switch: str  # choc | mx
    wireless: bool
    battery: bool
    rows: int | None
    cols: int | None
    thumbs: int | None
    stagger: bool
    features: list[Feature]
    mcu_hint: str
    raw: dict


_FEATURE_WORDS = {
    "knob": "knob",
    "encoder": "knob",
    "rotary": "knob",
    "screen": "screen",
    "oled": "screen",
    "display": "screen",
    "trackball": "trackball",
    "ball": "trackball",
}


def _as_int(v: Any) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def normalize_brief(brief: dict) -> Brief:
    raw = dict(brief)
    text = " ".join(str(v) for v in brief.values() if isinstance(v, str)).lower()
    style = str(brief.get("layout_style") or brief.get("style") or "").lower()
    if style not in ("split", "unibody", "macropad"):
        style = "split" if "split" in text else ("macropad" if "macropad" in text else "unibody")
    key_count = _as_int(brief.get("key_count") or brief.get("keys"))
    rows = _as_int(brief.get("rows"))
    cols = _as_int(brief.get("cols") or brief.get("columns"))
    if key_count is None:
        key_count = (rows or 4) * (cols or 4) * (2 if style == "split" else 1)
    switch = str(
        brief.get("switch_family") or brief.get("switch_type") or brief.get("switch") or ""
    )
    switch = "mx" if "mx" in switch.lower() or "cherry" in switch.lower() else "choc"
    feats: list[Feature] = []
    raw_feats = brief.get("features") or []
    if isinstance(raw_feats, dict):
        raw_feats = [
            {"type": k, **(v if isinstance(v, dict) else {"value": v})}
            for k, v in raw_feats.items()
            if v
        ]
    for f in raw_feats:
        if isinstance(f, str):
            kind = next((v for k, v in _FEATURE_WORDS.items() if k in f.lower()), None)
            hint = f
            count = 1
        else:
            name = str(f.get("type") or f.get("kind") or f.get("name") or "")
            kind = next((v for k, v in _FEATURE_WORDS.items() if k in name.lower()), None)
            hint = str(f.get("position") or f.get("where") or f.get("side") or f.get("hint") or "")
            count = _as_int(f.get("count")) or 1
        if kind:
            feats += [Feature(kind, hint) for _ in range(count)]
    knob_count = _as_int(brief.get("knob_count") or brief.get("knobs"))
    if knob_count is not None:
        knobs = [f for f in feats if f.kind == "knob"]
        others = [f for f in feats if f.kind != "knob"]
        knobs = (knobs + [Feature("knob", "") for _ in range(knob_count)])[:knob_count]
        feats = others + knobs
    if brief.get("trackball") and not any(f.kind == "trackball" for f in feats):
        feats.append(Feature("trackball", str(brief.get("trackball"))))
    wireless = bool(brief.get("wireless")) or "wireless" in text or "bluetooth" in text
    battery = (
        wireless
        or bool(brief.get("battery"))
        or any("battery" in str(f).lower() for f in raw_feats)
    )
    return Brief(
        key_count=key_count,
        split=style == "split",
        style=style,
        switch=switch,
        wireless=wireless,
        battery=battery,
        rows=rows,
        cols=cols,
        thumbs=_as_int(brief.get("thumb_keys") or brief.get("thumbs")),
        stagger=bool(brief.get("column_stagger", style == "split")),
        features=feats,
        mcu_hint=str(brief.get("mcu") or "").lower(),
        raw=raw,
    )


# ---------------------------------------------------------------- geometry primitives


@dataclass
class Item:
    """One footprint (or off-board object) on a board."""

    ref: str
    role: str
    fp: FootprintInfo | None
    x: float
    y: float
    rot: float = 0.0
    side: str = "top"
    pads: dict[str, str] = field(default_factory=dict)
    label: str = ""
    height_mm: float = 0.0
    extra_models: list[str] = field(default_factory=list)
    model_override: dict | None = None
    on_pcb: bool = True
    size_mm: tuple[float, float] | None = None
    meta: dict = field(default_factory=dict)

    def local_poly(self, which: str = "court") -> Polygon:
        if self.fp is None:
            w, h = self.size_mm or (1.0, 1.0)
            return box(-w / 2, -h / 2, w / 2, h / 2)
        if which == "back" and self.fp.courtyard_back:
            return box(*self.fp.courtyard_back)
        if which == "pads":
            return unary_union(
                [
                    box(p.x - p.w / 2, p.y - p.h / 2, p.x + p.w / 2, p.y + p.h / 2)
                    for p in self.fp.pads
                ]
            )
        return box(*self.fp.courtyard)

    def world(self, geom: Polygon) -> Polygon:
        g = geom
        if self.side == "bottom":
            g = affinity.scale(g, xfact=-1, yfact=1, origin=(0, 0))
        # KiCad orientation is counter-clockwise on screen; with y down that is a negative
        # mathematical rotation.
        g = affinity.rotate(g, -self.rot, origin=(0, 0))
        return affinity.translate(g, self.x, self.y)

    def footprint_poly(self) -> Polygon:
        if self.fp is None:
            return self.world(self.local_poly())
        parts = [self.world(self.local_poly()), self.world(self.local_poly("pads"))]
        cut = self.cutout_poly()
        if cut is not None:
            parts.append(cut.buffer(CUTOUT_RING, join_style="mitre"))
        return unary_union(parts)

    def centre(self) -> tuple[float, float]:
        """Courtyard centre in board coords (footprint origins are often a pin, not the body)."""
        c = self.world(self.local_poly()).centroid
        return (c.x, c.y)

    def envelope(self) -> Polygon:
        """Footprint plus what the case must clear above it: keycap, encoder bezel opening."""
        parts = [self.footprint_poly()]
        cap = self.meta.get("keycap_mm")
        if self.role == "switch" and cap:
            w, h = cap
            parts.append(self.world(box(-w / 2, -h / 2, w / 2, h / 2)))
        if self.role == "encoder" and self.fp is not None:
            x0, y0, x1, y1 = self.fp.courtyard
            r = math.hypot(x1 - x0, y1 - y0) / 2 + ENCODER_OPENING_MM + OPENING_RING_MM
            parts.append(Point(*self.centre()).buffer(r, 64))
        return unary_union(parts)

    def cutout_poly(self) -> Polygon | None:
        """A hole the footprint cuts in the board (its own Edge.Cuts), in board coords."""
        if self.fp is None or self.fp.cutout is None:
            return None
        return self.world(box(*self.fp.cutout))

    def bottom_poly(self) -> Polygon | None:
        """What this item occupies on the underside (sockets, SMD on B, THT pins)."""
        if self.fp is None:
            return self.world(self.local_poly()) if self.side == "bottom" else None
        parts = []
        if self.side == "bottom":
            parts.append(self.world(self.local_poly()))
        if self.fp.courtyard_back and self.side == "top":
            parts.append(self.world(self.local_poly("back")))
        for p in self.fp.pads:
            on_back = any(layer.startswith(("B.", "*.")) for layer in p.layers)
            if on_back or self.side == "bottom":
                parts.append(
                    self.world(box(p.x - p.w / 2, p.y - p.h / 2, p.x + p.w / 2, p.y + p.h / 2))
                )
        return unary_union(parts) if parts else None


@dataclass
class Key:
    x: float
    y: float
    rot: float
    row: int
    col: int
    thumb: bool = False


@dataclass
class BoardPlan:
    name: str  # left | right | main | sensor
    items: list[Item]
    outline: Polygon
    hole_circles: list[tuple[float, float, float]]
    keys: list[Key]
    matrix: dict
    controller: dict | None
    pin_budget: dict | None
    nets: list[str]
    log: list[str]
    mirror: bool = False
    links: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------- key grid


def _split_counts(b: Brief) -> list[int]:
    if b.split:
        left = math.ceil(b.key_count / 2)
        return [left, b.key_count - left]
    return [b.key_count]


def _grid_shape(n: int, b: Brief) -> tuple[int, int, int]:
    """(rows, cols, thumbs) for one board holding n keys."""
    if b.rows and b.cols:
        rows, cols = b.rows, b.cols
        if b.split and rows * cols > n:  # brief gave the whole-keyboard grid
            cols = max(1, math.ceil(cols / 2)) if rows * math.ceil(cols / 2) <= n else cols
        thumbs = max(0, n - rows * cols)
        return rows, cols, thumbs
    if b.style == "macropad":
        cols = b.cols or math.ceil(math.sqrt(n))
        rows = math.ceil(n / cols)
        return rows, cols, 0
    if b.thumbs is not None:
        t = b.thumbs if not b.split else b.thumbs
        rest = n - t
        for cols in (5, 6, 4, 7):
            if rest % cols == 0:
                return rest // cols, cols, t
    for rows in (3, 4, 5):
        for cols in (5, 6):
            t = n - rows * cols
            if 0 < t <= 5:
                return rows, cols, t
    cols = 5 if n >= 10 else max(2, math.ceil(math.sqrt(n)))
    rows = n // cols
    return rows, cols, n - rows * cols


def _key_rect(pitch: tuple[float, float]) -> Polygon:
    px, py = pitch
    return box(-px / 2, -py / 2, px / 2, py / 2)


def _place_keys(
    n: int,
    b: Brief,
    pitch: tuple[float, float],
    shape: Polygon,
    mirror: bool,
    log: list[str],
) -> list[Key]:
    """Key points in the board's final frame (x mirrored for a right half).

    shape is the switch footprint's local outline (courtyard, back courtyard, pads) plus its
    keycap; the thumb fan is opened and pushed down until no shape touches another.
    """
    rows, cols, thumbs = _grid_shape(n, b)
    px, py = pitch
    sgn = -1.0 if mirror else 1.0
    keys: list[Key] = []
    stagger = [
        STAGGER_PROFILE[c % len(STAGGER_PROFILE)] * py if b.stagger else 0.0 for c in range(cols)
    ]
    count = 0
    for c in range(cols):
        for r in range(rows):
            if count >= n - thumbs:
                break
            keys.append(Key(sgn * c * px, r * py - stagger[c], 0.0, r, c))
            count += 1
    log.append(
        f"grid {rows}x{cols} + {thumbs} thumb keys (pitch {px}x{py} mm, "
        f"stagger {'on' if b.stagger else 'off'})"
    )

    def poly(k: Key) -> Polygon:
        return affinity.translate(affinity.rotate(shape, -k.rot, origin=(0, 0)), k.x, k.y)

    if thumbs:
        inner_cols = [k for k in keys if k.col >= cols - max(2, thumbs)]
        y0 = max(k.y for k in inner_cols) + py
        x_center = (cols - 1) * px - (thumbs - 1) * px / 2 + px / 2
        placed = unary_union([poly(k) for k in keys]).buffer(THUMB_CAP_GAP / 2)
        half = math.radians(THUMB_FAN_DEG / 2)
        radius = px / (2 * math.sin(half))  # chord between neighbours = one pitch
        trial: list[Key] = []
        for _ in range(60):
            trial = []
            for i in range(thumbs):
                theta = math.radians((i - (thumbs - 1) / 2) * THUMB_FAN_DEG)
                x = x_center + radius * math.sin(theta)
                y = y0 + radius * (1 - math.cos(theta))
                trial.append(Key(sgn * x, y, -sgn * math.degrees(theta), rows, i, True))
            polys = [poly(t).buffer(THUMB_CAP_GAP / 2) for t in trial]
            if not any(polys[i].intersects(polys[i + 1]) for i in range(len(polys) - 1)):
                break
            radius += 2.0
        for push in range(0, 80):
            moved = [Key(t.x, t.y + push * 0.5, t.rot, t.row, t.col, True) for t in trial]
            if not any(poly(t).buffer(THUMB_CAP_GAP / 2).intersects(placed) for t in moved):
                keys += moved
                break
        else:
            raise ValueError("thumb cluster does not fit below the key grid")
    return keys


# ---------------------------------------------------------------- placement search


def _direction(hint: str, inner_sign: float) -> tuple[float, float]:
    h = hint.lower()
    dx = dy = 0.0
    if "left" in h:
        dx = -1
    if "right" in h:
        dx = 1
    if "inner" in h or "center" in h or "middle" in h:
        dx = inner_sign
    if "outer" in h:
        dx = -inner_sign
    if "top" in h or "upper" in h:
        dy = -1
    if "bottom" in h or "lower" in h or "thumb" in h:
        dy = 1
    if dx == 0 and dy == 0:
        dy = -1
    n = math.hypot(dx, dy)
    return dx / n, dy / n


def _search(
    shape: Polygon,
    anchor: Polygon,
    direction: tuple[float, float],
    blocked: list[Polygon],
    gap: float = FEATURE_GAP,
    step: float = 1.0,
) -> tuple[float, float]:
    """Find the free position for `shape` (centred at 0,0) nearest the ideal spot.

    Ideal = the anchor's bounding-box point in `direction`, pushed out by the shape's
    half size. Candidates on a 1 mm grid, ranked by distance to the ideal point.
    """
    ax0, ay0, ax1, ay1 = anchor.bounds
    acx, acy = (ax0 + ax1) / 2, (ay0 + ay1) / 2
    sx0, sy0, sx1, sy1 = shape.bounds
    hw, hh = (sx1 - sx0) / 2, (sy1 - sy0) / 2
    dx, dy = direction
    ideal = (
        acx + dx * ((ax1 - ax0) / 2 + hw + gap) if dx else acx + 0.0,
        acy + dy * ((ay1 - ay0) / 2 + hh + gap) if dy else acy + 0.0,
    )
    # pull diagonal hints back inside the corner (top left = above the left columns)
    if dx and dy:
        ideal = (acx + dx * ((ax1 - ax0) / 2 - hw), ideal[1])
    keep = unary_union(blocked).buffer(gap) if blocked else None
    radius_max = 80
    best: tuple[float, float] | None = None
    for r in range(0, radius_max):
        ring = []
        for i in range(-r, r + 1):
            for j in (-r, r):
                ring += [(i, j), (j, i)]
        ring.sort(key=lambda p: math.hypot(p[0], p[1]))
        for i, j in ring:
            cx, cy = ideal[0] + i * step, ideal[1] + j * step
            cand = affinity.translate(shape, cx, cy)
            if keep is None or not cand.intersects(keep):
                best = (cx, cy)
                break
        if best:
            return best
    raise RuntimeError("no free spot for feature")


# ---------------------------------------------------------------- controller + budget


def controller_gpio(ctrl: dict) -> tuple[list[str], dict[str, str]]:
    """GPIO pad numbers on the module's edge rows, and the full pad->symbol-name map."""
    fp = footprint_ref(ctrl["footprint"])
    pins = symbol_pins(*ctrl["symbol"])
    thru = [p for p in fp.pads if p.kind == "thru_hole" and p.number]
    edge_x = max(abs(p.x) for p in thru)
    edge = {p.number for p in thru if abs(abs(p.x) - edge_x) < 0.5}
    gpio = [num for num, name in pins.items() if re.match(r"^P\d\.\d\d", name) and num in edge]
    gpio.sort(key=lambda n: int(n))
    return gpio, pins


def pick_controller(need: int, b: Brief, log: list[str]) -> tuple[dict, dict]:
    cands = [c for c in R.CONTROLLERS if c["wireless"] or not b.wireless]
    if b.mcu_hint:
        hinted = [c for c in cands if any(w in c["label"].lower() for w in b.mcu_hint.split())]
        if hinted:
            cands = hinted + [c for c in cands if c not in hinted]
    first = cands[0]
    for c in cands:
        gpio, _ = controller_gpio(c)
        if len(gpio) >= need:
            if c is not first:
                log.append(
                    f"MCU pin budget: {need} GPIO needed, {first['label']} has "
                    f"{len(controller_gpio(first)[0])}, upgraded to {c['label']} ({len(gpio)})"
                )
            else:
                log.append(f"MCU pin budget: {need} GPIO needed, {c['label']} has {len(gpio)}")
            return c, {"needed": need, "available": len(gpio), "controller": c["id"]}
    raise RuntimeError(f"no controller has {need} GPIO")


# ---------------------------------------------------------------- one keyboard half


def _features_for(board: str, b: Brief) -> list[Feature]:
    """Distribute brief features over boards: explicit left/right hints win, then round robin."""
    if not b.split:
        return list(b.features)
    out: list[Feature] = []
    by_kind: dict[str, list[Feature]] = {}
    for f in b.features:
        by_kind.setdefault(f.kind, []).append(f)
    for kind, feats in by_kind.items():
        unassigned = []
        for f in feats:
            h = f.hint.lower()
            side = "left" if "left" in h else ("right" if "right" in h else None)
            if side == board:
                out.append(f)
            elif side is None:
                unassigned.append(f)
        default_side = {"trackball": "right", "screen": "left"}.get(kind)
        for i, f in enumerate(unassigned):
            if len(unassigned) == 1 and default_side:
                if board == default_side:
                    out.append(f)
            elif (i % 2 == 0) == (board == "left"):
                out.append(f)
    return out


def plan_keyboard_board(name: str, n_keys: int, b: Brief, log: list[str]) -> list[BoardPlan]:
    sw = R.SWITCHES[b.switch]
    pitch = sw["pitch"]
    sw_fp = footprint_ref(sw["footprint"])
    mirror = name == "right"
    # The right half is laid out in its own true frame (mirrored key points, unmirrored
    # footprints), so every search, the thumb fan included, sees the real socket geometry.
    sw_shape = unary_union(
        [box(*sw_fp.courtyard)]
        + ([box(*sw_fp.courtyard_back)] if sw_fp.courtyard_back else [])
        + [box(p.x - p.w / 2, p.y - p.h / 2, p.x + p.w / 2, p.y + p.h / 2) for p in sw_fp.pads]
    )
    cw, ch = sw["keycap_mm"]
    # thumb fan spacing must clear the keycaps as well as the sockets
    key_shape = unary_union([sw_shape, box(-cw / 2, -ch / 2, cw / 2, ch / 2)])
    keys = _place_keys(n_keys, b, pitch, key_shape, mirror, log)
    inner_sign = -1.0 if mirror else 1.0  # inner = towards the other half
    feats = _features_for(name, b)
    items: list[Item] = []
    blocked_top: list[Polygon] = []
    for i, k in enumerate(keys):
        it = Item(
            f"SW{i + 1}",
            "switch",
            sw_fp,
            k.x,
            k.y,
            k.rot,
            "top",
            label=sw["label"],
            height_mm=sw["height_mm"],
            extra_models=list(sw["extra_models"]),
            meta={
                "row": k.row,
                "col": k.col,
                "thumb": k.thumb,
                "keycap_mm": sw["keycap_mm"],
                "keycap_top_mm": sw["keycap_top_mm"],
            },
        )
        items.append(it)
        rect = affinity.translate(
            affinity.rotate(_key_rect(pitch), -k.rot, origin=(0, 0)), k.x, k.y
        )
        blocked_top.append(unary_union([rect, it.footprint_poly()]))
    key_cloud = unary_union(blocked_top)
    thumbs_poly = (
        unary_union([p for p, k in zip(blocked_top, keys, strict=True) if k.thumb])
        if any(k.thumb for k in keys)
        else key_cloud
    )

    # matrix: physical rows (+ thumb row) x columns; encoder pushes fill free slots
    grid_rows = max(k.row for k in keys if not k.thumb) + 1
    grid_cols = max(k.col for k in keys if not k.thumb) + 1
    n_rows = grid_rows + (1 if any(k.thumb for k in keys) else 0)
    used = {(k.row, k.col) for k in keys}
    knobs = [f for f in feats if f.kind == "knob"]
    screens = [f for f in feats if f.kind == "screen"]
    balls = [f for f in feats if f.kind == "trackball"]
    free = [(r, c) for r in range(n_rows) for c in range(grid_cols) if (r, c) not in used]
    n_cols = grid_cols
    while len(free) < len(knobs):
        free += [(r, n_cols) for r in range(n_rows)]
        n_cols += 1
    knob_slots = free[: len(knobs)]
    gpio_need = n_rows + n_cols + 2 * len(knobs) + 2 * bool(screens) + 5 * len(balls)
    ctrl, budget = pick_controller(gpio_need, b, log)
    budget.update(
        {
            "rows": n_rows,
            "cols": n_cols,
            "encoders": len(knobs),
            "screen": bool(screens),
            "trackball_sensor": len(balls),
        }
    )

    # controller: top inner corner
    ctrl_fp = footprint_ref(ctrl["footprint"])
    mcu = Item(
        "U1",
        "mcu",
        ctrl_fp,
        0,
        0,
        0,
        "top",
        label=ctrl["label"],
        height_mm=ctrl["height_mm"],
        model_override=ctrl.get("model"),
    )
    pos = _search(mcu.footprint_poly(), key_cloud, _direction("top inner", inner_sign), blocked_top)
    mcu.x, mcu.y = pos
    items.append(mcu)
    blocked_top.append(mcu.footprint_poly())

    feature_items: list[Item] = []
    hole_circles: list[tuple[float, float, float]] = []
    for idx, f in enumerate(knobs):
        enc = Item(
            f"EN{idx + 1}",
            "encoder",
            footprint_ref(R.ENCODER["footprint"]),
            0,
            0,
            0,
            label=R.ENCODER["label"],
            height_mm=R.ENCODER["height_mm"],
        )
        hint = f.hint or "top outer"
        enc.x, enc.y = _search(enc.envelope(), key_cloud, _direction(hint, inner_sign), blocked_top)
        items.append(enc)
        feature_items.append(enc)
        blocked_top.append(enc.envelope())
    for idx, _f in enumerate(screens):
        scr = Item(
            f"DS{idx + 1}",
            "screen",
            footprint_ref(R.SCREEN["footprint"]),
            0,
            0,
            0,
            label=R.SCREEN["label"],
            height_mm=R.SCREEN["height_mm"],
        )
        anchor = mcu.footprint_poly()
        scr.x, scr.y = (
            _search(scr.footprint_poly(), anchor, _direction("bottom", inner_sign), blocked_top)
            if not b.split
            else _search(
                scr.footprint_poly(), key_cloud, _direction("top inner", inner_sign), blocked_top
            )
        )
        items.append(scr)
        blocked_top.append(scr.footprint_poly())
    for idx, f in enumerate(balls):
        r_ball = R.TRACKBALL["ball_mm"] / 2
        disc = Point(0, 0).buffer(r_ball + CUP_WALL_MM, 64)
        hint = f.hint or "thumb"
        direction = _direction(hint.replace("right", "").replace("left", ""), inner_sign)
        if "thumb" in hint.lower():
            direction = (-inner_sign, 0.3)  # beside the thumb cluster, away from the inner edge
            direction = (
                direction[0] / math.hypot(*direction),
                direction[1] / math.hypot(*direction),
            )
        cx, cy = _search(disc, thumbs_poly, direction, blocked_top)
        ball = Item(
            f"TB{idx + 1}",
            "trackball",
            None,
            cx,
            cy,
            0,
            "top",
            label=R.TRACKBALL["label"],
            on_pcb=False,
            size_mm=(2 * r_ball, 2 * r_ball),
            height_mm=2 * r_ball,
        )
        items.append(ball)
        hole_circles.append((cx, cy, r_ball + 1.0))
        blocked_top.append(Point(cx, cy).buffer(r_ball + CUP_WALL_MM, 64))
        conn = Item(
            f"J{3 + idx}",
            "sensor_link",
            footprint_ref(R.SENSOR_LINK["footprint"]),
            0,
            0,
            0,
            label=R.SENSOR_LINK["label"],
            height_mm=4.25,
        )
        conn.x, conn.y = _search(conn.footprint_poly(), blocked_top[-1], (0.0, 1.0), blocked_top)
        conn.pads = {str(i + 1): s for i, s in enumerate(R.SENSOR_LINK["signals"])}
        items.append(conn)
        blocked_top.append(conn.footprint_poly())

    # power: battery connector + switch + reset around the controller
    mcu_poly = mcu.footprint_poly()
    if b.battery:
        for ref, rec, role in (
            ("J1", R.BATTERY_CONN, "battery_connector"),
            ("SW_PWR1", R.POWER_SWITCH, "power_switch"),
        ):
            it = Item(
                ref,
                role,
                footprint_ref(rec["footprint"]),
                0,
                0,
                0,
                pads=dict(rec["pins"]),
                label=rec["label"],
                height_mm=rec["height_mm"],
            )
            it.x, it.y = _search(it.footprint_poly(), mcu_poly, (0.0, -1.0), blocked_top)
            items.append(it)
            blocked_top.append(it.footprint_poly())
    rst = Item(
        "SW_RST1",
        "reset",
        footprint_ref(R.RESET["footprint"]),
        0,
        0,
        0,
        pads=dict(R.RESET["pins"]),
        label=R.RESET["label"],
        height_mm=R.RESET["height_mm"],
    )
    rst.x, rst.y = _search(rst.footprint_poly(), mcu_poly, (inner_sign, 0.0), blocked_top)
    items.append(rst)
    blocked_top.append(rst.footprint_poly())

    # diodes on the underside, inside each switch cell, clear of the socket
    blocked_bottom = [p for p in (it.bottom_poly() for it in items) if p is not None]
    d_fp = footprint_ref(R.DIODE["footprint"])
    switches = [it for it in items if it.role == "switch"]
    for i, swi in enumerate(switches):
        d = Item(f"D{i + 1}", "diode", d_fp, 0, 0, swi.rot, "bottom", label="1N4148W SOD-123")
        d.x, d.y = _place_diode(d, swi, pitch, blocked_bottom)
        items.append(d)
        blocked_bottom.append(d.footprint_poly())
    knob_diodes = []
    for i, enc in enumerate(it for it in items if it.role == "encoder"):
        d = Item(
            f"D{len(switches) + i + 1}", "diode", d_fp, 0, 0, 0, "bottom", label="1N4148W SOD-123"
        )
        d.x, d.y = _search(
            d.footprint_poly(),
            enc.footprint_poly(),
            (0.0, 1.0),
            blocked_bottom + [mcu_poly],
            gap=0.8,
            step=0.5,
        )
        items.append(d)
        blocked_bottom.append(d.footprint_poly())
        knob_diodes.append(d)

    # battery cell under the board (off-PCB part; keeps clear of everything on the underside)
    if b.battery:
        w, h = R.BATTERY_CELL["size_mm"]
        cell = Item(
            "BT1",
            "battery",
            None,
            0,
            0,
            0,
            "bottom",
            label=R.BATTERY_CELL["label"],
            on_pcb=False,
            size_mm=(w, h),
            height_mm=R.BATTERY_CELL["height_mm"],
        )
        cell.x, cell.y = _search(
            box(-w / 2, -h / 2, w / 2, h / 2), mcu_poly, (0.0, 1.0), blocked_bottom, gap=0.5
        )
        items.append(cell)
        blocked_bottom.append(cell.footprint_poly())

    # ---- nets
    gpio, ctrl_pins = controller_gpio(ctrl)
    ctrl_nets: list[str] = [f"ROW{r}" for r in range(n_rows)] + [f"COL{c}" for c in range(n_cols)]
    for i in range(len(knobs)):
        ctrl_nets += [f"ENC{i + 1}_A", f"ENC{i + 1}_B"]
    if screens:
        ctrl_nets += ["SDA", "SCL"]
    if balls:
        ctrl_nets += ["SCLK", "MOSI", "MISO", "NCS", "MOTION"]
    mcu.pads = _assign_gpio(mcu, gpio, ctrl_nets, items)
    for num, pin_name in ctrl_pins.items():
        if pin_name in ctrl["power"] and any(p.number == num for p in ctrl_fp.pads):
            mcu.pads[num] = ctrl["power"][pin_name]
    if not b.battery:
        mcu.pads = {k: v for k, v in mcu.pads.items() if v != "BAT+"}
    diodes = [it for it in items if it.role == "diode"]
    for i, swi in enumerate(switches):
        r, c = swi.meta["row"], swi.meta["col"]
        if swi.meta["thumb"]:
            r = n_rows - 1
            c = min(c, n_cols - 1)
        knet = f"K{i + 1}"
        swi.pads = {sw["pins"]["col"]: f"COL{c}", sw["pins"]["row_side"]: knet}
        diodes[i].pads = {R.DIODE["pins"]["anode"]: knet, R.DIODE["pins"]["cathode"]: f"ROW{r}"}
        swi.meta["matrix"] = (r, c)
    for i, enc in enumerate(it for it in items if it.role == "encoder"):
        r, c = knob_slots[i]
        knet = f"KE{i + 1}"
        pins = R.ENCODER["pins"]
        enc.pads = {
            pins["A"]: f"ENC{i + 1}_A",
            pins["B"]: f"ENC{i + 1}_B",
            pins["common"]: "GND",
            pins["push_a"]: f"COL{c}",
            pins["push_b"]: knet,
        }
        knob_diodes[i].pads = {
            R.DIODE["pins"]["anode"]: knet,
            R.DIODE["pins"]["cathode"]: f"ROW{r}",
        }
    for it in items:
        if it.role == "screen":
            it.pads = dict(R.SCREEN["pins"])

    outline = _outline(items)
    plans = [
        BoardPlan(
            name,
            items,
            outline,
            hole_circles,
            keys,
            {"rows": n_rows, "cols": n_cols, "knob_slots": knob_slots},
            ctrl,
            budget,
            [],
            log,
            mirror=mirror,
        )
    ]
    for idx, _ in enumerate(balls):
        plans.append(plan_sensor_board(f"{name}_sensor" if b.split else "sensor", log))
        # The sensor board hangs under the ball inside this half's case, which is built from
        # this outline, so the outline covers the daughter board's footprint as well.
        ball = next(it for it in items if it.ref == f"TB{idx + 1}")
        lens = sensor_lens(plans[-1])
        sub = affinity.translate(
            box(*plans[-1].outline.bounds), ball.x - lens.x, ball.y - lens.y
        ).buffer(SENSOR_BOARD_CLEARANCE, join_style="mitre")
        if not plans[0].outline.contains(sub):
            grown = unary_union([plans[0].outline, sub])
            grown = grown.buffer(CLOSE_RADIUS, join_style="round").buffer(
                -CLOSE_RADIUS, join_style="round"
            )
            plans[0].outline = Polygon(grown.exterior).simplify(0.05)
            log.append(f"outline grown to cover the {plans[-1].name} board under TB{idx + 1}")
        plans[0].links.append(
            {
                "from_ref": f"J{3 + idx}",
                "to_board": plans[-1].name,
                "to_ref": "J1",
                "cable_mm": R.SENSOR_LINK["cable_mm"],
            }
        )
    return plans


def _place_diode(
    d: Item, sw: Item, pitch: tuple[float, float], blocked: list[Polygon]
) -> tuple[float, float]:
    """Nearest spot below the switch centre (switch frame) that clears the underside."""
    keep = unary_union(blocked).buffer(0.4)
    px, py = pitch
    a = math.radians(-sw.rot)
    cands = []
    for dx10 in range(-int(px * 5), int(px * 5) + 1, 5):
        for dy10 in range(-int(py * 5), int(py * 5) + 1, 5):
            dx, dy = dx10 / 10, dy10 / 10
            cands.append((math.hypot(dx, dy - py * 0.3), dx, dy))
    cands.sort()
    for _, dx, dy in cands:
        x = sw.x + dx * math.cos(a) - dy * math.sin(a)
        y = sw.y + dx * math.sin(a) + dy * math.cos(a)
        d.x, d.y = x, y
        if not d.footprint_poly().intersects(keep):
            return x, y
    raise RuntimeError(f"no room for diode under {sw.ref}")


def _assign_gpio(mcu: Item, gpio: list[str], nets: list[str], items: list[Item]) -> dict[str, str]:
    """Greedy nearest assignment: each net to the free GPIO pad closest to its consumers."""
    if len(nets) > len(gpio):
        raise RuntimeError(f"{len(nets)} signals but {len(gpio)} GPIO")
    pad_pos = {}
    for p in mcu.fp.pads if mcu.fp else []:
        if p.number in gpio and p.number not in pad_pos:
            c = mcu.world(Point(p.x, p.y))
            pad_pos[p.number] = (c.x, c.y)
    centroids: dict[str, tuple[float, float]] = {}
    for net in nets:
        pts = []
        for it in items:
            if it.role == "switch" and net.startswith("COL"):
                pts.append((it.x, it.y)) if f"COL{it.meta.get('col')}" == net else None
            elif it.role == "switch" and net.startswith("ROW"):
                pts.append((it.x, it.y)) if f"ROW{it.meta.get('row')}" == net else None
        centroids[net] = (
            (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
            if pts
            else (mcu.x, mcu.y)
        )
    free = dict(pad_pos)
    out: dict[str, str] = {}
    for net in nets:
        cx, cy = centroids[net]
        best = min(free, key=lambda n: math.hypot(free[n][0] - cx, free[n][1] - cy))
        out[best] = net
        del free[best]
    return out


def _outline(items: list[Item], convex: bool = False) -> Polygon:
    polys = []
    for it in items:
        if it.role == "trackball":
            polys.append(Point(it.x, it.y).buffer(it.size_mm[0] / 2 + CUP_WALL_MM, 64))
        elif it.on_pcb:
            polys.append(it.envelope())
        elif it.role == "battery":
            polys.append(it.footprint_poly())
    u = unary_union(polys)
    if convex:  # small daughter boards: a plain hull leaves the router room to escape
        return Polygon(u.convex_hull.buffer(SMALL_BOARD_MARGIN, join_style="round").exterior)
    closed = u.buffer(CLOSE_RADIUS, join_style="round").buffer(-CLOSE_RADIUS, join_style="round")
    out = closed.buffer(BOARD_MARGIN, join_style="round")
    if isinstance(out, MultiPolygon):
        out = unary_union([out, out.convex_hull.buffer(-1)]).buffer(0)
        if isinstance(out, MultiPolygon):
            out = max(out.geoms, key=lambda g: g.area)
    return Polygon(out.exterior).simplify(0.05)


# ---------------------------------------------------------------- sensor board

SENSOR_BOARD_CLEARANCE = 1.0  # host outline margin around the daughter board's bbox


def sensor_lens(plan: BoardPlan) -> Point:
    """Point of a sensor board that sits under the ball: the footprint's own lens cutout
    centroid, else the sensor's origin, else the board centroid."""
    sensor = next((it for it in plan.items if it.role == "sensor"), None)
    if sensor is None:
        return plan.outline.centroid
    lens = sensor.cutout_poly()
    return lens.centroid if lens is not None else Point(sensor.x, sensor.y)


def plan_sensor_board(name: str, log: list[str]) -> BoardPlan:
    items: list[Item] = []
    sensor = Item(
        "U1",
        "sensor",
        footprint_ref(R.SENSOR["footprint"]),
        0,
        0,
        0,
        pads=dict(R.SENSOR["pins"]),
        label=R.SENSOR["label"],
        height_mm=3.5,
    )
    items.append(sensor)
    blocked = [sensor.footprint_poly()]
    conn = Item(
        "J1",
        "sensor_link",
        footprint_ref(R.SENSOR_LINK["footprint"]),
        0,
        0,
        0,
        pads={str(i + 1): s for i, s in enumerate(R.SENSOR_LINK["signals"])},
        label=R.SENSOR_LINK["label"],
        height_mm=4.25,
    )
    conn.x, conn.y = _search(conn.footprint_poly(), sensor.footprint_poly(), (0.0, 1.0), blocked)
    items.append(conn)
    blocked.append(conn.footprint_poly())
    ldo = Item(
        "U2",
        "ldo",
        footprint_ref(R.LDO["footprint"]),
        0,
        0,
        0,
        pads=dict(R.LDO["pins"]),
        label=R.LDO["label"],
        height_mm=1.2,
    )
    ldo.x, ldo.y = _search(ldo.footprint_poly(), sensor.footprint_poly(), (1.0, 0.0), blocked)
    items.append(ldo)
    blocked.append(ldo.footprint_poly())
    for i, (net, direction) in enumerate(
        (("3V3", (1.0, -1.0)), ("VDD18", (1.0, 1.0)), ("VDDPIX", (-1.0, 1.0)))
    ):
        c = Item(
            f"C{i + 1}",
            "capacitor",
            footprint_ref(R.CAP["footprint"]),
            0,
            0,
            0,
            pads={"1": net, "2": "GND"},
            label=R.CAP["label"],
            height_mm=1.3,
        )
        c.x, c.y = _search(c.footprint_poly(), sensor.footprint_poly(), direction, blocked, gap=0.8)
        items.append(c)
        blocked.append(c.footprint_poly())
    outline = _outline(items, convex=True)
    log.append(f"{name}: PMW3360 sensor board with LDO, 3 caps, JST-SH link")
    return BoardPlan(name, items, outline, [], [], {}, None, None, [], log)


# ---------------------------------------------------------------- entry


def plan_boards(brief: dict) -> tuple[Brief, list[BoardPlan], list[str]]:
    b = normalize_brief(brief)
    log: list[str] = []
    plans: list[BoardPlan] = []
    counts = _split_counts(b)
    names = ["left", "right"] if b.split else ["main"]
    for name, n in zip(names, counts, strict=True):
        half_log: list[str] = []
        plans += plan_keyboard_board(name, n, b, half_log)
        log += [f"{name}: {m}" for m in half_log]
    return b, plans, log
