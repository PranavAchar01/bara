"""Product form: what the device looks like and where a hand, eye or cable meets it.

The board and case used to be built inside-out (parts packed around the controller, a case
wrapped around that hull), so nothing knew the product's shape. This stage runs first. The model
is given the nearest reference designs in the catalog and asked for a top-view silhouette in
millimetres, a thickness, and named anchors (where each user-facing slot sits and which way it
faces). Code then checks the answer: a closed simple polygon, a size that agrees with the real
product dimensions the model itself cites and with the archetype references, every user-facing
slot mapped to an anchor. One repair pass goes back to the model with the list of problems; if
the form still fails, the build gets a failing check naming them. Nothing is defaulted.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shapely.errors import GEOSException
from shapely.geometry import Point, Polygon
from shapely.validation import explain_validity

from bara.live.ask import ask_json

ARCHETYPES = Path(__file__).resolve().parents[3] / "data/archetypes.json"
PATTERNS = ["single", "row", "column", "grid", "diamond", "ring"]
MOUNTS = ["front", "back", "edge"]
REST_POSES = ["face_up", "upright"]
# what makes a product recognisable beyond its outline and thickness; a generic vocabulary the
# model composes from what the device is, never a template per device
FEATURE_KINDS = ["appendage", "wedge", "panel_grid", "recess", "raised", "lens"]
MAX_FEATURES = 8
SIZE_TOLERANCE = 0.35  # silhouette vs the model's own cited real dimensions
MIN_SIDE_MM, MAX_SIDE_MM = 12.0, 900.0
MAX_ASPECT = 14.0

SYSTEM = """You are the industrial designer on a hardware design tool. Given a device request,
its function blocks and a few reference designs, describe the physical form of a real product of
this kind, as a person would recognise it in a photo.

Coordinates: millimetres, origin at the centre of the product, +x to the right and +y toward
the top of the product when you look at the face a person looks at or touches (the face with
the screen, keys or controls; for a product with none, the face a person holds or the side it
rests on). The silhouette is that face's outline.

Rules:
- silhouette: a closed outline as 8 to 60 points, counter-clockwise, no repeated or crossing
  edges. Draw the real shape: grips, notches, rounded ends, ears, an L or a pill, not a
  rectangle unless the real product is one. Use enough points on curves to read as curved.
- reference: the typical real overall width x height x thickness in mm of products of this
  class, and the generic kinds of product you are drawing on (plain descriptions such as
  "portrait handheld game console with a d-pad", never a brand, product or model name, even
  when the request names one). Use those numbers for the silhouette's bounding box and for
  thickness_mm. Do not shrink the product to fit parts.
- thickness_mm: maximum body thickness; edge_thickness_mm: thickness at the thinnest edge.
  The silhouette and thickness are the body only: a stick, handle, lever or knob standing up
  from the body is a control at an anchor, never folded into the outline or the thickness.
- anchors: every touch slot gets one or more anchors; a slot made of several groups (listed
  after "groups") gets one anchor per group, and the anchors' counts add up to the slot's
  count. Each anchor says where its instances sit: mount front (on the
  main face), back (on the rear face), or edge (on the rim, with edge_normal_deg the outward
  direction, 0 = +x, 90 = +y); a pattern (single, row, column, grid, diamond, ring) with its
  centre, pitch_mm between instances and cols for a grid; and what it is for. Place controls
  where a hand rests (thumbs on the front, fingers on the back or top edge), ports on an edge,
  a screen filling its bay. Positions must be inside the silhouette. Parts on one face never
  share area: a display window sits clear of the key grid, each control clear of the others.
- silhouette_description: two sentences a person could use to recognise the outline.
- rest_pose: how the product sits in use. face_up when it lies on a surface or in a hand
  with that face toward the sky (phone, keyboard, remote, scale); upright when it stands with
  that face toward the person (monitor, speaker, clock, router on its stand).
- features: the form details a person recognises the product by beyond its outline, taken
  from what the device is (the concept's identity cues, the reference products). Use none
  when the outline and thickness already say it. Kinds:
  appendage: a thin solid part of the body reaching out past the silhouette from its rim (a
  stake pushed into soil, a hanging tab or lug with a hole, a hook, an ear, a handle tab),
  given as its own outline that touches the silhouette and lies outside it, with
  thickness_mm and hole_mm (0 = no hole) at centre;
  wedge: the body is thicker toward axis_deg (0 = +x, 90 = +y) and thinnest, thickness_mm,
  at the opposite edge (a desk calculator, a keyboard, a doorstop);
  panel_grid: cols x rows lids, tiles or compartments marked as grooves on the main face over
  width_mm x height_mm at centre (a weekly pill box, a tile keypad);
  recess: a shallow pocket in the main face (a finger scoop, a label well, a display bay);
  raised: a low pad standing on the main face (a grip pad, a lens bezel, a nameplate);
  lens: a clear dome on the main face width_mm x height_mm, thickness_mm tall (a tail light,
  a sensor eye, an indicator lens).
  Fields a kind does not use are 0 or empty. Surface features sit inside the silhouette.
- A product made of separate bodies joined by a thin link (headphones: two cups on a band;
  glasses: two lenses and temples; a wearable with a strap) is drawn flat, as laid out on a
  table. The silhouette is the one body that holds the electronics (one ear cup, the front of
  the frame, the watch case), thickness_mm is that body's thickness. Every other body is an
  appendage: the link (a headband arc, a strap) with its own thin thickness_mm, and each
  further body (the second cup) as an appendage of the body's full thickness that touches the
  previous appendage's end. The reference width and height are the whole product including its
  appendages. Never draw such a product as one slab with notches.
- Use only slot_id values from the list."""


@dataclass
class Touch:
    slot_id: str
    label: str
    function_id: str
    count: int
    groups: tuple[str, ...] = ()
    size_mm: tuple[float, float] | None = None  # the chosen part's footprint, width x depth


@dataclass
class Form:
    device_class: str
    silhouette: list[tuple[float, float]]
    thickness_mm: float
    edge_thickness_mm: float
    anchors: list[dict[str, Any]]
    reference: dict[str, Any]
    description: str
    problems: list[str] = field(default_factory=list)
    repaired: bool = False
    scale: float = 1.0
    rest_pose: str = "face_up"  # REST_POSES: upright stands with the main face toward the person
    features: list[dict[str, Any]] = field(default_factory=list)  # FEATURE_KINDS, form frame

    @property
    def polygon(self) -> Polygon:
        return Polygon(self.silhouette)

    @property
    def size_mm(self) -> tuple[float, float]:
        x0, y0, x1, y1 = self.polygon.bounds
        return round(x1 - x0, 1), round(y1 - y0, 1)

    def json(self) -> dict[str, Any]:
        return {
            "device_class": self.device_class,
            "silhouette": [[round(x, 2), round(y, 2)] for x, y in self.silhouette],
            "thickness_mm": self.thickness_mm,
            "edge_thickness_mm": self.edge_thickness_mm,
            "anchors": self.anchors,
            "reference": self.reference,
            "description": self.description,
            "size_mm": list(self.size_mm),
            "repaired": self.repaired,
            "rest_pose": self.rest_pose,
            "features": self.features,
        }

    def summary(self) -> str:
        w, h = self.size_mm
        names = ", ".join(a["name"] for a in self.anchors)
        return f"{w:g} x {h:g} x {self.thickness_mm:g} mm, {len(self.silhouette)} points; {names}"


def schema(slot_ids: list[str]) -> dict[str, Any]:
    pt = {
        "type": "object",
        "additionalProperties": False,
        "required": ["x", "y"],
        "properties": {"x": {"type": "number"}, "y": {"type": "number"}},
    }
    anchor = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "name",
            "slot_id",
            "purpose",
            "mount",
            "edge_normal_deg",
            "pattern",
            "centre",
            "pitch_mm",
            "cols",
            "count",
        ],
        "properties": {
            "name": {"type": "string"},
            "slot_id": {"type": "string", "enum": slot_ids or ["none"]},
            "purpose": {"type": "string"},
            "mount": {"type": "string", "enum": MOUNTS},
            "edge_normal_deg": {"type": "number"},
            "pattern": {"type": "string", "enum": PATTERNS},
            "centre": pt,
            "pitch_mm": {"type": "number"},
            "cols": {"type": "integer"},
            "count": {"type": "integer"},
        },
    }
    feature = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "kind",
            "purpose",
            "outline",
            "centre",
            "width_mm",
            "height_mm",
            "cols",
            "rows",
            "thickness_mm",
            "hole_mm",
            "axis_deg",
        ],
        "properties": {
            "kind": {"type": "string", "enum": FEATURE_KINDS},
            "purpose": {"type": "string"},
            "outline": {"type": "array", "items": pt},
            "centre": pt,
            "width_mm": {"type": "number"},
            "height_mm": {"type": "number"},
            "cols": {"type": "integer"},
            "rows": {"type": "integer"},
            "thickness_mm": {"type": "number"},
            "hole_mm": {"type": "number"},
            "axis_deg": {"type": "number"},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "device_class",
            "reference",
            "silhouette",
            "thickness_mm",
            "edge_thickness_mm",
            "silhouette_description",
            "rest_pose",
            "anchors",
            "features",
        ],
        "properties": {
            "device_class": {"type": "string"},
            "reference": {
                "type": "object",
                "additionalProperties": False,
                "required": ["kinds", "width_mm", "height_mm", "thickness_mm"],
                "properties": {
                    "kinds": {"type": "array", "items": {"type": "string"}},
                    "width_mm": {"type": "number"},
                    "height_mm": {"type": "number"},
                    "thickness_mm": {"type": "number"},
                },
            },
            "silhouette": {"type": "array", "items": pt},
            "thickness_mm": {"type": "number"},
            "edge_thickness_mm": {"type": "number"},
            "silhouette_description": {"type": "string"},
            "rest_pose": {"type": "string", "enum": REST_POSES},
            "anchors": {"type": "array", "items": anchor},
            "features": {"type": "array", "items": feature},
        },
    }


# ---------------------------------------------------------------- references


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def references(prompt: str, limit: int = 4) -> list[dict[str, Any]]:
    """The archetypes whose words and name overlap the request most, with their real form."""
    try:
        data = json.loads(ARCHETYPES.read_text())
    except (OSError, ValueError):
        return []
    want = _words(prompt)
    scored = []
    for a in data.get("archetypes", []):
        have = _words(" ".join([a.get("name", ""), *a.get("words", []), *a.get("default_for", [])]))
        score = len(want & have)
        if score and a.get("form"):
            scored.append((score, a))
    scored.sort(key=lambda t: -t[0])
    return [
        {
            "name": a["name"],
            "source": (a.get("source") or {}).get("url"),
            "shape": a["form"].get("shape"),
            "size_mm": a["form"].get("size_mm"),
            "thickness_mm": a["form"].get("thickness_mm"),
        }
        for _, a in scored[:limit]
    ]


# ---------------------------------------------------------------- build and check


def expand(anchor: dict[str, Any], count: int) -> list[tuple[float, float]]:
    """The centre of each instance of an anchor, from its pattern."""
    cx, cy = (float(v) for v in anchor["centre"])
    pitch = max(float(anchor.get("pitch_mm") or 0.0), 1.0)
    n = max(1, count)
    pat = anchor["pattern"]
    if pat == "single" or n == 1:
        return [(cx, cy)] * n
    if pat == "row":
        return [(cx + (i - (n - 1) / 2) * pitch, cy) for i in range(n)]
    if pat == "column":
        return [(cx, cy + (i - (n - 1) / 2) * pitch) for i in range(n)]
    if pat == "grid":
        cols = max(1, int(anchor.get("cols") or math.ceil(math.sqrt(n))))
        rows = math.ceil(n / cols)
        return [
            (
                cx + ((i % cols) - (cols - 1) / 2) * pitch,
                cy + ((rows - 1) / 2 - (i // cols)) * pitch,
            )
            for i in range(n)
        ]
    if pat == "diamond":
        base = [(0.0, 1.0), (1.0, 0.0), (0.0, -1.0), (-1.0, 0.0)]
        return [
            (cx + base[i % 4][0] * pitch * (1 + i // 4), cy + base[i % 4][1] * pitch * (1 + i // 4))
            for i in range(n)
        ]
    ang = 2 * math.pi / n  # ring: the pitch is the chord between neighbours
    r = pitch / (2 * math.sin(ang / 2)) if n > 1 else 0.0
    return [(cx + r * math.cos(i * ang), cy + r * math.sin(i * ang)) for i in range(n)]


def build(data: dict[str, Any]) -> Form | None:
    try:
        pts = [(float(p["x"]), float(p["y"])) for p in data["silhouette"]]
        for a in data.get("anchors") or []:
            a["centre"] = [float(a["centre"]["x"]), float(a["centre"]["y"])]
        features = [_feature(f) for f in data.get("features") or []]
    except (KeyError, TypeError, ValueError):
        return None
    poly = Polygon(pts)
    if not poly.is_valid:
        fixed = poly.buffer(0)
        poly = fixed if isinstance(fixed, Polygon) and not fixed.is_empty else poly
    form = Form(
        device_class=str(data.get("device_class") or ""),
        silhouette=pts,
        thickness_mm=float(data.get("thickness_mm") or 0.0),
        edge_thickness_mm=float(data.get("edge_thickness_mm") or 0.0),
        anchors=list(data.get("anchors") or []),
        reference=dict(data.get("reference") or {}),
        description=str(data.get("silhouette_description") or ""),
        rest_pose=data["rest_pose"] if data.get("rest_pose") in REST_POSES else "face_up",
        features=features,
    )
    return form


def _feature(f: dict[str, Any]) -> dict[str, Any]:
    c = f.get("centre") or {}
    return {
        "kind": str(f["kind"]),
        "purpose": str(f.get("purpose") or ""),
        "outline": [[float(p["x"]), float(p["y"])] for p in f.get("outline") or []],
        "centre": [float(c.get("x") or 0.0), float(c.get("y") or 0.0)],
        **{k: float(f.get(k) or 0.0) for k in ("width_mm", "height_mm", "thickness_mm")},
        **{k: float(f.get(k) or 0.0) for k in ("hole_mm", "axis_deg")},
        "cols": max(1, int(f.get("cols") or 1)),
        "rows": max(1, int(f.get("rows") or 1)),
    }


def move_features(form: Form, k: float = 1.0, dx: float = 0.0, dy: float = 0.0) -> None:
    """Scale the features about the origin by k, then shift them by (-dx, -dy), as the outline."""
    for f in form.features:
        f["outline"] = [[x * k - dx, y * k - dy] for x, y in f["outline"]]
        f["centre"] = [f["centre"][0] * k - dx, f["centre"][1] * k - dy]
        f["width_mm"], f["height_mm"] = f["width_mm"] * k, f["height_mm"] * k


def centre_on_origin(form: Form) -> None:
    """Move the silhouette and anchors so the bounding box centre is the origin."""
    x0, y0, x1, y1 = Polygon(form.silhouette).bounds
    dx, dy = (x0 + x1) / 2, (y0 + y1) / 2
    form.silhouette = [(x - dx, y - dy) for x, y in form.silhouette]
    for a in form.anchors:
        a["centre"] = [a["centre"][0] - dx, a["centre"][1] - dy]
    move_features(form, 1.0, dx, dy)


FACE_GAP_MM = 2.0  # clear space between two anchors' parts on one face
SCREEN_LONG_MM = 20.0  # the board's rule: a screen this long lies along the body's long side
DEFAULT_PART_MM = 10.0  # a slot with no chosen part yet: a finger-sized control


def _part_box(form: Form, t: Touch | None) -> tuple[float, float]:
    """Width and depth one instance takes on the face, turned the way the board will lay it."""
    if t is None or not t.size_mm:
        return DEFAULT_PART_MM, DEFAULT_PART_MM
    w, d = (max(float(v), 1.0) for v in t.size_mm)
    if t.function_id.startswith("display.") and max(w, d) >= SCREEN_LONG_MM:
        x0, y0, x1, y1 = Polygon(form.silhouette).bounds
        long, short = max(w, d), min(w, d)
        return (long, short) if x1 - x0 >= y1 - y0 else (short, long)
    if max(w, d) < 25.0:  # a small part may be turned either way when placed
        return max(w, d), max(w, d)
    return w, d


def _anchor_box(a: dict[str, Any], size: tuple[float, float]) -> tuple[float, float, float, float]:
    pts = expand(a, max(1, int(a.get("count") or 1)))
    hw, hd = size[0] / 2, size[1] / 2
    return (
        min(p[0] for p in pts) - hw,
        min(p[1] for p in pts) - hd,
        max(p[0] for p in pts) + hw,
        max(p[1] for p in pts) + hd,
    )


def _face_anchors(
    form: Form, touches: list[Touch]
) -> list[tuple[dict[str, Any], tuple[float, float]]]:
    by_slot = {t.slot_id: t for t in touches}
    return [
        (a, _part_box(form, by_slot.get(a.get("slot_id"))))
        for a in form.anchors
        if a.get("mount") in ("front", "back") and a.get("centre") is not None
    ]


def _overlap(
    b1: tuple[float, float, float, float], b2: tuple[float, float, float, float], gap: float
) -> tuple[float, float]:
    ox = min(b1[2], b2[2]) - max(b1[0], b2[0]) + gap
    oy = min(b1[3], b2[3]) - max(b1[1], b2[1]) + gap
    return ox, oy


def separate(form: Form, touches: list[Touch], rounds: int = 60) -> None:
    """Pull apart anchors whose parts would share area on the same face (a display window over
    the top rows of a key grid). Each anchor moves as a rigid group, along the axis that frees
    it soonest, and stays inside the silhouette; a pattern whose pitch is tighter than its part
    is opened up to the part's size first. Whatever cannot be freed is left for validate()."""
    poly = Polygon(form.silhouette)
    if not poly.is_valid or poly.area <= 0:
        return
    items = _face_anchors(form, touches)
    for a, size in items:
        n = max(1, int(a.get("count") or 1))
        if n > 1 and a.get("pattern") != "single":
            a["pitch_mm"] = max(float(a.get("pitch_mm") or 0.0), max(size) + 1.0)
    inner = poly.buffer(-1.0)

    def inside(a: dict[str, Any], size: tuple[float, float]) -> bool:
        bx0, by0, bx1, by1 = _anchor_box(a, size)
        return all(
            inner.contains(Point(p)) for p in ((bx0, by0), (bx1, by0), (bx1, by1), (bx0, by1))
        )

    def shift(a: dict[str, Any], size: tuple[float, float], dx: float, dy: float) -> float:
        """Move by (dx, dy) as far as the silhouette allows; the fraction moved."""
        was_inside = inside(a, size)
        cx, cy = a["centre"]
        for k in (1.0, 0.75, 0.5, 0.25):
            a["centre"] = [cx + k * dx, cy + k * dy]
            if inside(a, size) or not was_inside:
                return k
        a["centre"] = [cx, cy]
        return 0.0

    for _ in range(rounds):
        moved = False
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                (a, sa), (b, sb) = items[i], items[j]
                if a["mount"] != b["mount"]:
                    continue
                ba, bb = _anchor_box(a, sa), _anchor_box(b, sb)
                ox, oy = _overlap(ba, bb, FACE_GAP_MM)
                if ox <= 0 or oy <= 0:
                    continue
                sy = 1.0 if (bb[1] + bb[3]) >= (ba[1] + ba[3]) else -1.0
                sx = 1.0 if (bb[0] + bb[2]) >= (ba[0] + ba[2]) else -1.0
                along_y = ((0.0, -sy * oy / 2), (0.0, sy * oy / 2))
                along_x = ((-sx * ox / 2, 0.0), (sx * ox / 2, 0.0))
                # the cheaper axis first; when the silhouette blocks both anchors on it, the other
                for da, db in (along_y, along_x) if oy <= ox else (along_x, along_y):
                    got = shift(a, sa, *da) + shift(b, sb, *db)
                    if got > 0:
                        moved = True
                        break
        if not moved:
            break


def face_overlaps(form: Form, touches: list[Touch]) -> list[str]:
    """Anchors whose parts still share area on one face, as problems the model can act on."""
    items = _face_anchors(form, touches)
    out = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            (a, sa), (b, sb) = items[i], items[j]
            if a["mount"] != b["mount"]:
                continue
            ox, oy = _overlap(_anchor_box(a, sa), _anchor_box(b, sb), 0.0)
            if ox > 0.5 and oy > 0.5:
                out.append(
                    f"anchors {a['name']} and {b['name']} overlap by {ox:.0f} x {oy:.0f} mm on "
                    f"the {a['mount']} face: two controls, or a display window and a key grid, "
                    f"cannot share area; move one or make room"
                )
    return out


def validate(form: Form, touches: list[Touch]) -> list[str]:
    """Everything wrong with the form, as sentences the model can act on."""
    problems: list[str] = []
    poly = Polygon(form.silhouette)
    if len(form.silhouette) < 3 or poly.area <= 0:
        return ["the silhouette has no area"]
    if not 8 <= len(form.silhouette) <= 60:
        problems.append(f"the silhouette has {len(form.silhouette)} points, use 8 to 60")
    if not poly.is_valid:
        problems.append(f"the silhouette is not a simple closed polygon ({explain_validity(poly)})")
        return problems
    x0, y0, x1, y1 = poly.bounds
    w, h = x1 - x0, y1 - y0
    ex0, ey0, ex1, ey1 = overall_bounds(form)
    if min(w, h) < MIN_SIDE_MM or max(w, h) > MAX_SIDE_MM:
        problems.append(f"{w:.0f} x {h:.0f} mm is outside the range of any real product")
    if max(w, h) / max(min(w, h), 1e-6) > MAX_ASPECT:
        problems.append(f"aspect ratio {max(w, h) / min(w, h):.0f}:1 is not a product outline")
    ref = form.reference
    rw, rh = float(ref.get("width_mm") or 0), float(ref.get("height_mm") or 0)
    if rw > 0 and rh > 0:
        ow, oh = ex1 - ex0, ey1 - ey0
        direct = max(abs(ow / rw - 1), abs(oh / rh - 1))
        turned = max(abs(ow / rh - 1), abs(oh / rw - 1))
        if min(direct, turned) > SIZE_TOLERANCE:
            problems.append(
                f"the silhouette with its appendages is {ow:.0f} x {oh:.0f} mm but your reference size is "
                f"{rw:.0f} x {rh:.0f} mm: use the real size"
            )
    else:
        problems.append("the reference gives no real width and height")
    rt = float(ref.get("thickness_mm") or 0)
    if form.thickness_mm <= 0 or form.edge_thickness_mm <= 0:
        problems.append("thickness_mm and edge_thickness_mm must be positive")
    elif form.edge_thickness_mm > form.thickness_mm + 1e-6:
        problems.append("edge_thickness_mm cannot exceed thickness_mm")
    elif rt > 0 and abs(form.thickness_mm / rt - 1) > 0.5:
        problems.append(f"thickness {form.thickness_mm:g} mm disagrees with reference {rt:g} mm")
    by_slot: dict[str, list[dict[str, Any]]] = {}
    for a in form.anchors:
        by_slot.setdefault(a["slot_id"], []).append(a)
    for t in touches:
        if t.slot_id not in by_slot:
            problems.append(f"no anchor for {t.slot_id} ({t.label})")
    for t in touches:
        given = sum(max(1, int(a.get("count") or 1)) for a in by_slot.get(t.slot_id, []))
        if t.slot_id in by_slot and given != t.count:
            problems.append(f"anchors for {t.slot_id} place {given} but the slot has {t.count}")
    for a in form.anchors:
        if a["slot_id"] not in {t.slot_id for t in touches}:
            problems.append(f"anchor {a['name']} names unknown slot {a['slot_id']}")
            continue
        pts = expand(a, max(1, int(a.get("count") or 1)))
        inside = poly.buffer(1.0)
        if a["mount"] == "edge":
            near = min(Point(p).distance(poly.exterior) for p in pts)
            if near > 0.15 * min(w, h) + 4:
                problems.append(f"edge anchor {a['name']} is {near:.0f} mm from the rim")
        elif not all(inside.contains(Point(p)) for p in pts):
            problems.append(f"anchor {a['name']} has instances outside the silhouette")
    problems.extend(face_overlaps(form, touches))
    problems.extend(feature_problems(form))
    if form.rest_pose == "face_up" and form.thickness_mm > min(w, h) + 1e-6:
        problems.append(
            f"thickness {form.thickness_mm:g} mm is more than the silhouette's short side "
            f"{min(w, h):.0f} mm: the silhouette and thickness are the body only; a stick, "
            f"handle or knob standing on it is a control at an anchor, not part of the body"
        )
    return problems


def overall_bounds(form: Form) -> tuple[float, float, float, float]:
    """Bounds of the silhouette and every appendage: the whole product laid flat."""
    x0, y0, x1, y1 = Polygon(form.silhouette).bounds
    for f in form.features:
        if f["kind"] == "appendage" and len(f["outline"]) >= 3:
            ax0, ay0, ax1, ay1 = Polygon(f["outline"]).buffer(0).bounds
            x0, y0, x1, y1 = min(x0, ax0), min(y0, ay0), max(x1, ax1), max(y1, ay1)
    return x0, y0, x1, y1


def feature_problems(form: Form) -> list[str]:
    """Each form feature must be buildable: an appendage reaches out from the rim, a surface
    feature sits on the face, sizes and thicknesses are those of a real product."""
    poly = Polygon(form.silhouette)
    x0, y0, x1, y1 = poly.bounds
    short = min(x1 - x0, y1 - y0)
    out: list[str] = []
    body = poly  # the silhouette plus the appendages already placed: a chain may continue
    if len(form.features) > MAX_FEATURES:
        out.append(f"{len(form.features)} features: keep the {MAX_FEATURES} that matter most")
    for i, f in enumerate(form.features):
        name = f"feature {i + 1} ({f['kind']}, {f['purpose'][:40]})"
        t = f["thickness_mm"]
        if f["kind"] == "appendage":
            ap = Polygon(f["outline"]) if len(f["outline"]) >= 3 else Polygon()
            if ap.is_empty or not ap.is_valid or ap.area < 4.0:
                out.append(f"{name}: its outline is not a simple closed shape with area")
                continue
            if ap.distance(body) > 1.0:
                out.append(f"{name}: its outline must touch the silhouette's rim or the appendage before it")
            elif ap.difference(body).area < 0.5 * ap.area:
                out.append(f"{name}: most of it must lie outside the silhouette")
            if not 0.8 <= t <= form.thickness_mm + 1e-6:
                out.append(f"{name}: thickness_mm {t:g} must be 0.8 to {form.thickness_mm:g}")
            body = body.union(ap)
            if f["hole_mm"] and not ap.buffer(-0.8 * max(f["hole_mm"], 0.0)).contains(
                Point(f["centre"])
            ):
                out.append(f"{name}: its hole at centre must lie inside the appendage")
        elif f["kind"] == "wedge":
            if not 0.5 <= t < form.thickness_mm:
                out.append(f"{name}: thickness_mm is the thin edge, below {form.thickness_mm:g}")
        else:
            w, h = f["width_mm"], f["height_mm"]
            if w <= 0 or h <= 0:
                out.append(f"{name}: width_mm and height_mm must be positive")
            elif not poly.buffer(1.0).contains(Point(f["centre"])) or max(w, h) > 1.05 * max(
                x1 - x0, y1 - y0
            ):
                out.append(f"{name}: it must sit on the main face, inside the silhouette")
            if f["kind"] == "lens" and not 0.5 <= t <= 0.5 * short:
                out.append(f"{name}: a lens dome is 0.5 to {0.5 * short:.0f} mm tall")
    return out


def _prompt(prompt: str, touches: list[Touch], refs: list[dict[str, Any]], note: str) -> str:
    slots = "\n".join(
        f"- {t.slot_id}: {t.label} x{t.count} ({t.function_id})"
        + (f", each {t.size_mm[0]:.0f} x {t.size_mm[1]:.0f} mm" if t.size_mm else "")
        + (f", groups: {'; '.join(t.groups)}" if len(t.groups) > 1 else "")
        for t in touches
    )
    return (
        f"Device request: {prompt}\n\nTouch slots (each needs anchors; sizes are the real parts "
        f"chosen, so every anchor must leave room for its part and none may overlap):\n"
        f"{slots or '- none'}\n\n"
        f"Reference designs from the catalog (real dimensions, use as evidence):\n"
        f"{json.dumps(refs, indent=1) if refs else 'none close to this request'}\n{note}"
    )


_SIZE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:x|×|by)\s*(\d+(?:\.\d+)?)(?:\s*(?:x|×|by)\s*\d+(?:\.\d+)?)?\s*(mm|cm)\b",
    re.I,
)


def declared_size(prompt: str) -> tuple[float, float] | None:
    """Width and height in mm when the request states them ("120 x 60 mm", "12 x 6 cm")."""
    m = _SIZE.search(prompt)
    if m is None:
        return None
    k = 10.0 if m.group(3).lower() == "cm" else 1.0
    return float(m.group(1)) * k, float(m.group(2)) * k


def fit_note(report: dict) -> str:
    """The numbers a form needs to be sized to hold the parts it was drawn for."""
    declared = report.get("declared_mm")
    if declared:
        return (
            f"The parts chosen do not fit your silhouette ({report['parts_mm2']} mm2 of "
            f"footprints against {report['usable_mm2']} mm2 usable per side). The request states "
            f"the product size as {declared[0]:g} x {declared[1]:g} mm: keep the silhouette at "
            f"that size, and change only its shape or thickness if that helps."
        )
    big = "; ".join(f"{p['part']} {p['mm'][0]} x {p['mm'][1]} mm" for p in report["largest"])
    return (
        f"The parts chosen for this product do not fit your silhouette. Footprints total "
        f"{report['parts_mm2']} mm2 (largest: {big}); your silhouette is "
        f"{report['silhouette_mm2']} mm2 and only {report['usable_mm2']} mm2 of it is usable per "
        f"board side once the case wall is taken off. Redraw the SAME product, keeping every "
        f"anchor's role and layout, at a "
        f"realistic size that holds them: the usable area per side should be at least twice the "
        f"footprint total and no silhouette dimension below {report['widest_mm'] + 8:.0f} mm."
    )


MAX_FIT_SCALE = 2.0


def scaled_to_fit(form: Form, report: dict, touches: list[Touch]) -> Form | None:
    """The form grown uniformly until the parts fit: twice the footprint area usable per side
    and no side below the widest part plus margin. A free redraw at a new size used to stretch
    the outline (a joystick base turned into a tall slab); scaling keeps the proportions, the
    anchors' layout and their pitch. None when the growth needed is not plausible."""
    poly = Polygon(form.silhouette)
    x0, y0, x1, y1 = poly.bounds
    short = max(min(x1 - x0, y1 - y0), 1e-6)
    usable = max(float(report.get("usable_mm2") or 0.0), 1.0)
    k_area = math.sqrt(2.0 * float(report.get("parts_mm2") or 0.0) / usable)
    k_side = (float(report.get("widest_mm") or 0.0) + 8.0) / short
    k = max(k_area, k_side, 1.1)
    if k > MAX_FIT_SCALE or max(x1 - x0, y1 - y0) * k > MAX_SIDE_MM:
        return None
    ref = dict(form.reference)
    for key in ("width_mm", "height_mm"):
        if ref.get(key):
            ref[key] = round(float(ref[key]) * k, 1)
    anchors = []
    for a in form.anchors:
        b = dict(a)
        b["centre"] = [a["centre"][0] * k, a["centre"][1] * k]
        anchors.append(b)
    grown = Form(
        device_class=form.device_class,
        silhouette=[(x * k, y * k) for x, y in form.silhouette],
        thickness_mm=form.thickness_mm,
        edge_thickness_mm=form.edge_thickness_mm,
        anchors=anchors,
        reference=ref,
        description=form.description,
        scale=form.scale * k,
        rest_pose=form.rest_pose,
        features=[{**f, "outline": list(f["outline"])} for f in form.features],
    )
    move_features(grown, k)
    centre_on_origin(grown)
    separate(grown, touches)
    grown.problems = validate(grown, touches)
    return None if grown.problems else grown


async def derive(
    prompt: str,
    touches: list[Touch],
    previous: Form | None = None,
    critique: str = "",
    fit: dict | None = None,
    photos: list[bytes] | None = None,
    concept: str = "",
) -> tuple[Form | None, str]:
    """Ask for the form, check it, and make one repair pass. A form that still fails keeps its
    problems on the object so the caller can fail loudly."""
    refs = references(prompt)
    slot_ids = [t.slot_id for t in touches]
    sch = schema(slot_ids)
    note = ""
    if critique and previous is not None:
        note = (
            "\nThe form you proposed earlier was built and reviewed from a render. Redraw it "
            "so the product is recognisable.\n"
            + critique
            + "\nEarlier silhouette: "
            + json.dumps([[round(x), round(y)] for x, y in previous.silhouette])
        )
    if fit and previous is not None:
        note = (
            "\n"
            + fit_note(fit)
            + "\nEarlier silhouette: "
            + json.dumps([[round(x), round(y)] for x, y in previous.silhouette])
        )
    if concept:  # what the device is, written from retrieved references before any part
        note += (
            "\n" + concept + "\nDraw this product: its canonical orientation, proportions, "
            "layout of the face and thickness come from the concept above."
        )
    if photos:
        note += (
            f"\nThe {len(photos)} attached image(s) are photos of devices of this kind found by a "
            "generic web search, for visual reference only. Take the general silhouette, "
            "proportions, corner shapes and where controls sit; never copy a brand's styling, "
            "logo or colours, and ignore anything in them that is not the device."
        )
    if fit and previous is not None and not fit.get("declared_mm"):
        grown = scaled_to_fit(previous, fit, touches)
        if grown is not None:  # the same product, larger: proportions and layout kept
            return grown, ""
    form: Form | None = previous
    for attempt in (0, 1):
        data, why = await ask_json(
            SYSTEM, _prompt(prompt, touches, refs, note), sch, name="form", timeout_s=90,
            max_tokens=6000, images=photos,
        )  # fmt: skip
        if data is None:
            return form, why
        try:
            got = build(data)
        except (GEOSException, ValueError) as exc:
            got, why = None, str(exc)
        if got is None:
            return form, why or "unreadable form"
        centre_on_origin(got)
        separate(got, touches)
        got.problems = validate(got, touches)
        got.repaired = attempt == 1
        form = got
        if not got.problems:
            return got, ""
        note = (
            "\nYour previous answer had these problems, fix all of them:\n- "
            + "\n- ".join(got.problems)
            + "\nPrevious silhouette: "
            + json.dumps([[round(x), round(y)] for x, y in got.silhouette])
        )
    return form, "form still failing after the repair pass"


def diff(before: Form, after: Form) -> str:
    """What a repair pass changed, in words: size, outline detail, thickness, anchor moves."""

    def box(form: Form) -> tuple[float, float]:
        xs = [p[0] for p in form.silhouette]
        ys = [p[1] for p in form.silhouette]
        return max(xs) - min(xs), max(ys) - min(ys)

    (bw, bh), (aw, ah) = box(before), box(after)
    old = {a["name"]: a for a in before.anchors}
    moved = []
    for a in after.anchors:
        o = old.get(a["name"])
        if o is None:
            moved.append(f"{a['name']} added")
        elif max(abs(o["centre"][0] - a["centre"][0]), abs(o["centre"][1] - a["centre"][1])) > 2:
            moved.append(f"{a['name']} moved")
    return (
        f"outline {bw:.0f}x{bh:.0f} -> {aw:.0f}x{ah:.0f} mm, "
        f"{len(before.silhouette)} -> {len(after.silhouette)} points, "
        f"thickness {before.thickness_mm:.0f} -> {after.thickness_mm:.0f} mm, "
        f"anchors: {', '.join(moved) or 'unchanged'}"
    )
