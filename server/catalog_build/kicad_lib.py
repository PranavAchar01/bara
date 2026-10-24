"""Deterministic readers for KiCad footprints (.kicad_mod) and symbols (.kicad_sym).

Coordinates are reported in the KiCad footprint frame (mm, +X right, +Y down) under
`at_mm`, and in the SPEC 3.2 part frame (mm, +X right, +Y away from the user, Z up)
under `xy_mm`. The conversion is a Y flip; the origin is the footprint origin.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from .sexpr import Node, child, children, floats, parse, value

COURTYARD_LAYERS = {"F.CrtYd", "B.CrtYd"}
SHAPES = ("fp_line", "fp_rect", "fp_circle", "fp_arc", "fp_poly")


@dataclass
class Pad:
    number: str
    kind: str
    shape: str
    at: tuple[float, float, float]
    size: tuple[float, float] | None
    drill: float | None
    layers: list[str]

    def as_record(self) -> dict[str, Any]:
        x, y, rot = self.at
        rec: dict[str, Any] = {
            "number": self.number,
            "type": self.kind,
            "shape": self.shape,
            "at_mm": [round(x, 4), round(y, 4)],
            "xy_mm": [round(x, 4), round(-y, 4)],
            "rotation_deg": round(rot, 3),
            "size_mm": [round(v, 4) for v in self.size] if self.size else None,
            "drill_mm": round(self.drill, 4) if self.drill is not None else None,
            "side": "bottom"
            if self.layers and all(lyr.startswith("B.") for lyr in self.layers)
            else "top"
            if self.kind == "smd"
            else "both",
        }
        return rec


@dataclass
class Model:
    path: str
    offset: tuple[float, float, float] = (0.0, 0.0, 0.0)
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
    rotate: tuple[float, float, float] = (0.0, 0.0, 0.0)
    hidden: bool = False
    node: Node | None = None

    def as_record(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "offset_mm": list(self.offset),
            "rotate_deg": list(self.rotate),
            "scale": list(self.scale),
            "hidden": self.hidden,
        }


@dataclass
class Footprint:
    name: str
    path: Path
    descr: str
    tags: str
    attrs: list[str]
    properties: dict[str, str]
    pads: list[Pad]
    courtyard: dict[str, list[float]] | None
    models: list[Model]
    node: Node = field(repr=False)

    @property
    def pin_numbers(self) -> list[str]:
        seen: list[str] = []
        for pad in self.pads:
            if pad.number and pad.number not in seen:
                seen.append(pad.number)
        return seen


def _rotate(x: float, y: float, deg: float) -> tuple[float, float]:
    if not deg:
        return x, y
    r = math.radians(-deg)  # KiCad rotation is CCW in a Y-down frame
    return x * math.cos(r) - y * math.sin(r), x * math.sin(r) + y * math.cos(r)


def _shape_points(node: Node) -> list[tuple[float, float]]:
    head = node[0]
    pts: list[tuple[float, float]] = []
    if head in ("fp_line", "fp_rect"):
        for key in ("start", "end"):
            p = floats(child(node, key), 2)
            if p:
                pts.append((p[0], p[1]))
    elif head == "fp_circle":
        c = floats(child(node, "center"), 2)
        e = floats(child(node, "end"), 2)
        if c and e:
            r = math.hypot(e[0] - c[0], e[1] - c[1])
            pts += [(c[0] - r, c[1] - r), (c[0] + r, c[1] + r)]
    elif head == "fp_arc":
        for key in ("start", "mid", "end"):
            p = floats(child(node, key), 2)
            if p:
                pts.append((p[0], p[1]))
    elif head == "fp_poly":
        pts_node = child(node, "pts")
        if pts_node:
            for xy in children(pts_node, "xy"):
                p = floats(xy, 2)
                if p:
                    pts.append((p[0], p[1]))
    return pts


def _layer_of(node: Node) -> str | None:
    lyr = child(node, "layer")
    return str(value(lyr)) if lyr else None


def _model(node: Node) -> Model:
    def xyz(head: str, default: tuple[float, float, float]) -> tuple[float, float, float]:
        sub = child(node, head)
        if sub is None:
            return default
        got = floats(child(sub, "xyz"), 3)
        return (got[0], got[1], got[2]) if got else default

    offset = xyz("offset", (0.0, 0.0, 0.0))
    if child(node, "offset") is None and child(node, "at") is not None:
        at = xyz("at", (0.0, 0.0, 0.0))  # legacy "at" is in inches
        offset = (at[0] * 25.4, at[1] * 25.4, at[2] * 25.4)
    hidden = any(item == "hide" for item in node[1:]) or value(child(node, "hide")) == "yes"
    return Model(
        path=str(node[1]),
        offset=offset,
        scale=xyz("scale", (1.0, 1.0, 1.0)),
        rotate=xyz("rotate", (0.0, 0.0, 0.0)),
        hidden=hidden,
        node=node,
    )


@lru_cache(maxsize=4096)
def read_footprint(path: Path) -> Footprint:
    node = parse(path.read_text(encoding="utf-8", errors="replace"))
    props: dict[str, str] = {}
    for prop in children(node, "property"):
        if len(prop) >= 3:
            props[str(prop[1])] = str(prop[2])
    for legacy in children(node, "fp_text"):
        if len(legacy) >= 3 and legacy[1] in ("reference", "value"):
            props.setdefault(str(legacy[1]).capitalize(), str(legacy[2]))
    pads: list[Pad] = []
    for p in children(node, "pad"):
        at = floats(child(p, "at"), 2) or [0.0, 0.0]
        at_node = child(p, "at")
        rot = float(at_node[3]) if at_node is not None and len(at_node) > 3 else 0.0
        size = floats(child(p, "size"), 2)
        drill_node = child(p, "drill")
        drill: float | None = None
        if drill_node is not None:
            nums = [x for x in drill_node[1:] if not isinstance(x, list) and x != "oval"]
            try:
                drill = float(nums[0]) if nums else None
            except ValueError:
                drill = None
        layers_node = child(p, "layers")
        layers = [str(x) for x in layers_node[1:]] if layers_node else []
        pads.append(
            Pad(
                number=str(p[1]),
                kind=str(p[2]),
                shape=str(p[3]),
                at=(at[0], at[1], rot),
                size=(size[0], size[1]) if size else None,
                drill=drill,
                layers=layers,
            )
        )
    xs: list[float] = []
    ys: list[float] = []
    for head in SHAPES:
        for shape in children(node, head):
            if _layer_of(shape) in COURTYARD_LAYERS:
                for x, y in _shape_points(shape):
                    xs.append(x)
                    ys.append(y)
    courtyard = None
    if xs:
        # Report in the SPEC part frame (Y flipped).
        courtyard = {
            "min": [round(min(xs), 4), round(-max(ys), 4)],
            "max": [round(max(xs), 4), round(-min(ys), 4)],
        }
    attr_node = child(node, "attr")
    attrs = [str(x) for x in attr_node[1:]] if attr_node else []
    descr = str(value(child(node, "descr"), default="") or props.get("Description", ""))
    tags = str(value(child(node, "tags"), default="") or "")
    return Footprint(
        name=str(node[1]).split(":")[-1],
        path=path,
        descr=descr,
        tags=tags,
        attrs=attrs,
        properties=props,
        pads=pads,
        courtyard=courtyard,
        models=[_model(m) for m in children(node, "model")],
        node=node,
    )


@dataclass
class Pin:
    number: str
    name: str
    etype: str


@dataclass
class Symbol:
    lib: str
    name: str
    properties: dict[str, str]
    pins: list[Pin]

    @property
    def lib_id(self) -> str:
        return f"{self.lib}:{self.name}"

    def pin_map(self) -> dict[str, str]:
        return {p.number: p.name for p in self.pins}


@lru_cache(maxsize=256)
def read_symbol_lib(path: Path) -> dict[str, Node]:
    root = parse(path.read_text(encoding="utf-8", errors="replace"))
    return {str(s[1]): s for s in children(root, "symbol")}


def _collect_pins(sym: Node) -> list[Pin]:
    pins: list[Pin] = []
    for unit in children(sym, "symbol"):
        for pin in children(unit, "pin"):
            name = str(value(child(pin, "name"), default=""))
            number = str(value(child(pin, "number"), default=""))
            pins.append(Pin(number=number, name=name, etype=str(pin[1])))
    for pin in children(sym, "pin"):
        pins.append(
            Pin(
                number=str(value(child(pin, "number"), default="")),
                name=str(value(child(pin, "name"), default="")),
                etype=str(pin[1]),
            )
        )
    uniq: dict[str, Pin] = {}
    for p in pins:
        uniq.setdefault(p.number, p)
    return sorted(uniq.values(), key=lambda p: _natural(p.number))


def _natural(s: str) -> list[Any]:
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


def read_symbol(path: Path, name: str) -> Symbol:
    lib = path.stem
    table = read_symbol_lib(path)
    if name not in table:
        raise KeyError(f"{lib}:{name} not found in {path}")
    sym = table[name]
    props: dict[str, str] = {}
    chain = [sym]
    seen = {name}
    while (ext := child(chain[-1], "extends")) is not None:
        base = str(ext[1])
        if base in seen or base not in table:
            break
        seen.add(base)
        chain.append(table[base])
    for node in reversed(chain):
        for prop in children(node, "property"):
            if len(prop) >= 3:
                props[str(prop[1])] = str(prop[2])
    pins: list[Pin] = []
    for node in chain:
        pins = _collect_pins(node)
        if pins:
            break
    return Symbol(lib=lib, name=name, properties=props, pins=pins)
