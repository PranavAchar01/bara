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
- reference: the real overall width x height x thickness in mm of well-known products of this
  class (give the product names you are drawing on) and use those numbers for the silhouette's
  bounding box and for thickness_mm. Do not shrink the product to fit parts.
- thickness_mm: maximum body thickness; edge_thickness_mm: thickness at the thinnest edge.
- anchors: every touch slot gets one or more anchors; a slot made of several groups (listed
  after "groups") gets one anchor per group, and the anchors' counts add up to the slot's
  count. Each anchor says where its instances sit: mount front (on the
  main face), back (on the rear face), or edge (on the rim, with edge_normal_deg the outward
  direction, 0 = +x, 90 = +y); a pattern (single, row, column, grid, diamond, ring) with its
  centre, pitch_mm between instances and cols for a grid; and what it is for. Place controls
  where a hand rests (thumbs on the front, fingers on the back or top edge), ports on an edge,
  a screen filling its bay. Positions must be inside the silhouette.
- silhouette_description: two sentences a person could use to recognise the outline.
- Use only slot_id values from the list."""


@dataclass
class Touch:
    slot_id: str
    label: str
    function_id: str
    count: int
    groups: tuple[str, ...] = ()


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
            "anchors",
        ],
        "properties": {
            "device_class": {"type": "string"},
            "reference": {
                "type": "object",
                "additionalProperties": False,
                "required": ["products", "width_mm", "height_mm", "thickness_mm"],
                "properties": {
                    "products": {"type": "array", "items": {"type": "string"}},
                    "width_mm": {"type": "number"},
                    "height_mm": {"type": "number"},
                    "thickness_mm": {"type": "number"},
                },
            },
            "silhouette": {"type": "array", "items": pt},
            "thickness_mm": {"type": "number"},
            "edge_thickness_mm": {"type": "number"},
            "silhouette_description": {"type": "string"},
            "anchors": {"type": "array", "items": anchor},
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
    )
    return form


def centre_on_origin(form: Form) -> None:
    """Move the silhouette and anchors so the bounding box centre is the origin."""
    x0, y0, x1, y1 = Polygon(form.silhouette).bounds
    dx, dy = (x0 + x1) / 2, (y0 + y1) / 2
    form.silhouette = [(x - dx, y - dy) for x, y in form.silhouette]
    for a in form.anchors:
        a["centre"] = [a["centre"][0] - dx, a["centre"][1] - dy]


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
    if min(w, h) < MIN_SIDE_MM or max(w, h) > MAX_SIDE_MM:
        problems.append(f"{w:.0f} x {h:.0f} mm is outside the range of any real product")
    if max(w, h) / max(min(w, h), 1e-6) > MAX_ASPECT:
        problems.append(f"aspect ratio {max(w, h) / min(w, h):.0f}:1 is not a product outline")
    ref = form.reference
    rw, rh = float(ref.get("width_mm") or 0), float(ref.get("height_mm") or 0)
    if rw > 0 and rh > 0:
        direct = max(abs(w / rw - 1), abs(h / rh - 1))
        turned = max(abs(w / rh - 1), abs(h / rw - 1))
        if min(direct, turned) > SIZE_TOLERANCE:
            problems.append(
                f"the silhouette is {w:.0f} x {h:.0f} mm but your reference products are "
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
    return problems


def _prompt(prompt: str, touches: list[Touch], refs: list[dict[str, Any]], note: str) -> str:
    slots = "\n".join(
        f"- {t.slot_id}: {t.label} x{t.count} ({t.function_id})"
        + (f", groups: {'; '.join(t.groups)}" if len(t.groups) > 1 else "")
        for t in touches
    )
    return (
        f"Device request: {prompt}\n\nTouch slots (each needs anchors):\n{slots or '- none'}\n\n"
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


async def derive(
    prompt: str,
    touches: list[Touch],
    previous: Form | None = None,
    critique: str = "",
    fit: dict | None = None,
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
    form: Form | None = previous
    for attempt in (0, 1):
        data, why = await ask_json(
            SYSTEM, _prompt(prompt, touches, refs, note), sch, name="form", timeout_s=90,
            max_tokens=6000,
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
