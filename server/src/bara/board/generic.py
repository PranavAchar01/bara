"""Any device -> one populated KiCad board from the chosen parts' own footprints.

Keyboards have their own planner (layout.py). Every other build goes through here:

1. each chosen part with a KiCad footprint in the catalog becomes a footprint on the board
   (quantity N gives N footprints);
2. the support passives the parts' datasheet circuits call for are added: input and output
   capacitors on a linear regulator, a 100 nF decoupling capacitor per bare IC, I2C pull-ups
   when no breakout module on the bus brings its own, a JST connector for a battery cell;
3. nets come from the parts' pin names (GND, 3V3, VBUS, VBAT, I2C, SPI, UART), and every
   signal a peripheral needs is given a free controller GPIO, nearest pad first;
4. parts are packed around the controller, largest first, each at the free spot that keeps
   the board smallest; the outline is the packed footprints plus a margin.

The same KiCad build, Freerouting, DRC and GLB export as the keyboard boards run on it.
"""

from __future__ import annotations

import math
import re
from typing import Any

import numpy as np
from shapely import affinity, prepared
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

from . import registry as R
from .layout import BoardPlan, Item, _assign_gpio, _search
from .libs import FootprintInfo, find_footprint, footprint_ref, symbol_pins

PART_GAP = 1.2  # courtyard to courtyard between packed parts
PASSIVE_GAP = 0.6
BOARD_MARGIN = 2.0
CORNER_R = 2.0
# hand-set support values (datasheet typicals; listed in registry.HAND_SET)
REG_CAP = "1 uF 0805"
DECOUPLE_CAP = "100 nF 0805"
PULLUP = "4.7 k 0805"
RES_FP = "kicad/Resistor_SMD:R_0805_2012Metric"
# The SMD PH footprint in the registry has no STEP in the installed KiCad 3D library, so the
# generic board uses the through-hole vertical PH header, whose model ships with KiCad.
BAT_CONN_FP = "kicad/Connector_JST:JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical"

GND = {"GND", "VSS", "GNDA", "GNDD", "AGND", "DGND", "PGND", "BAT-", "B-", "VBAT-", "-"}
V3 = {"VCC", "VDD", "3V3", "3.3V", "+3V3", "+3.3V", "VDDIO", "IOVDD", "VOUT", "VO", "3.3"}
VBUS = {"VIN", "VI", "VBUS", "5V", "+5V", "RAW", "VUSB", "USB"}
VBAT = {"BAT+", "VBAT", "VBAT+", "B+", "BAT", "BATT", "+"}
BUS = {
    "SDA": "SDA",
    "SCL": "SCL",
    "SCK": "SCK",
    "SCLK": "SCK",
    "CLK": "SCK",
    "MOSI": "MOSI",
    "SDI": "MOSI",
    "DIN": "MOSI",
    "MISO": "MISO",
    "SDO": "MISO",
    "DOUT": "MISO",
    "TX": "UART_RX",  # a peripheral's TX goes to the controller's RX
    "TXD": "UART_RX",
    "RX": "UART_TX",
    "RXD": "UART_TX",
}
PER_PART = {"CS", "NCS", "SS", "CSB", "INT", "IRQ", "RST", "RESET", "NRST", "DC", "BUSY"}
GPIO_NAME = re.compile(r"^(P\d\.\d+|P[A-H]\d+|GPIO\d+|IO\d+|GP\d+|D\d+|A\d+)(-.*)?$")
SKIP_NAME = re.compile(r"^(NC|DNC|N/?C|~|EP|SHIELD|MP|PAD)\d*$")


def _clean(name: str) -> str:
    return re.sub(r"[\s_]", "", str(name).upper()).lstrip("~{").rstrip("}")


def power_net(name: str) -> str | None:
    n = _clean(name)
    for nets, label in ((GND, "GND"), (V3, "3V3"), (VBUS, "VBUS"), (VBAT, "VBAT")):
        if n in nets:
            return label
    return None


def _role(record: dict[str, Any]) -> str:
    fns = [f["function_id"] for f in record.get("functions", [])]
    primary = next((f["function_id"] for f in record.get("functions", []) if f.get("primary")), "")
    primary = primary or (fns[0] if fns else "")
    if primary == "compute.mcu":
        return "mcu"
    if primary.startswith("display."):
        return "screen"
    if primary == "power.battery":
        return "battery"
    if primary == "power.regulator":
        return "regulator"
    return primary.split(".")[-1] or "part"


def _footprint(record: dict[str, Any]) -> FootprintInfo | None:
    ref = record.get("footprint")
    if not ref:
        return None
    try:
        return find_footprint(str(ref))
    except Exception:  # a footprint file the parser cannot read is treated as missing
        return None


def _registry_match(fp: FootprintInfo) -> dict[str, Any] | None:
    """The registry controller or screen whose footprint is this one (or its variant)."""
    for ctrl in R.CONTROLLERS:
        if footprint_name(ctrl["footprint"]) == fp.name:
            return ctrl
    base = footprint_name(R.SCREEN["footprint"]).removesuffix("_No_Mounting_Holes")
    if fp.name.startswith(base):
        return R.SCREEN
    return None


def footprint_name(ref: str) -> str:
    return ref.split(":", 1)[1]


def _pins_for(record: dict[str, Any], fp: FootprintInfo) -> dict[str, str]:
    """Pad -> pin name: the catalog record, else the registry map, else the KiCad symbol."""
    if record.get("pins"):
        return {str(k): str(v) for k, v in record["pins"].items()}
    reg = _registry_match(fp)
    if reg is not None:
        if "symbol" in reg:
            return dict(symbol_pins(*reg["symbol"]))
        return dict(reg["pins"])
    lib_id = str(record.get("lib_id") or "")
    if ":" in lib_id:
        lib, sym = lib_id.split(":", 1)
        try:
            return dict(symbol_pins("kicad", f"{lib}.kicad_sym", sym))
        except (OSError, KeyError):
            return {}
    return {}


def _model_for(fp: FootprintInfo) -> dict[str, Any] | None:
    reg = _registry_match(fp)
    return reg.get("model") if reg is not None else None


def plan_device_board(
    parts: list[dict[str, Any]], log: list[str], brief: dict[str, Any] | None = None
) -> BoardPlan:
    """parts: compose part instances, each with its catalog record under "record".

    brief["form"] ({shape, size_mm}, from the device archetype) sets the board outline: the
    parts are packed towards that aspect and the outline is that shape, grown only when the
    parts do not fit inside it.
    """
    form = (brief or {}).get("form") or None
    touch_slots = set((brief or {}).get("touch_slots") or [])
    items: list[Item] = []
    counters: dict[str, int] = {}
    skipped: list[str] = []

    def ref_for(prefix: str) -> str:
        counters[prefix] = counters.get(prefix, 0) + 1
        return f"{prefix}{counters[prefix]}"

    for part in parts:
        record = part.get("record") or {}
        fp = _footprint(record)
        role = _role(record)
        if fp is None:
            if role == "battery":
                items.append(_battery_cell(part, record, ref_for("BT")))
            elif _bbox_mm(record) is not None:  # a module with no footprint: off-board, wired
                items.append(_module_cell(part, record, ref_for("M"), touch_slots))
            else:
                skipped.append(str(part.get("label") or part["part_id"]))
            continue
        prefix = {"mcu": "U", "screen": "DS", "regulator": "U", "battery": "BT"}.get(role, "U")
        if role in ("button", "toggle_switch", "switch"):
            prefix = "SW"
        elif role in ("connector", "header", "jack", "usb_in"):
            prefix = "J"
        elif role in ("led", "indicator_led", "rgb_led"):
            prefix = "D"
        n = 1 if part.get("placement", {}).get("mode") == "layout" else int(part["quantity"] or 1)
        for _ in range(max(1, n)):
            it = Item(
                ref_for(prefix),
                role,
                fp,
                0.0,
                0.0,
                0.0,
                "top",
                label=str(record.get("display_name") or part.get("label") or fp.name)[:60],
                height_mm=_height(record),
                meta={"instance_id": part["instance_id"], "pins": _pins_for(record, fp)},
                model_override=_model_for(fp),
            )
            it.meta["slot_id"] = part.get("slot_id")
            it.meta["touch"] = part.get("slot_id") in touch_slots
            it.meta["module"] = record.get("kind") == "module"
            items.append(it)
    if skipped:
        log.append("no KiCad footprint, kept off the board: " + ", ".join(skipped[:6]))

    mcu = next((it for it in items if it.role == "mcu"), None)
    _pads_from_pins(items, log)
    items += _support_parts(items, log)
    _matrix_inputs(items, mcu, log)

    # pack: controller (or the largest part) at the origin, then largest first
    on_board = [it for it in items if it.on_pcb]
    off_board = [it for it in items if not it.on_pcb]
    first = mcu or max(on_board, key=lambda it: _area(it), default=None)
    placed: list[Item] = []
    blocked: list[Polygon] = []
    pf = (brief or {}).get("product_form")
    fitted: Polygon | None = None
    if pf and on_board:
        fitted = place_in_form(on_board, first, pf, log)
        placed = list(on_board)
        blocked = [it.footprint_poly() for it in placed]
        first = None
    if first is not None:
        placed.append(first)
        blocked.append(first.footprint_poly())
    parents = {id(it): it.meta.get("near") for it in on_board}
    order = sorted(
        (it for it in on_board if it is not first),
        key=lambda it: (parents[id(it)] is not None, -_area(it)),
    )
    for it in order if fitted is None else []:
        near = parents[id(it)]
        gap = PASSIVE_GAP if near is not None else PART_GAP
        anchor = near.footprint_poly() if near is not None and near in placed else None
        it.x, it.y = _best_spot(it, anchor, blocked, gap, form)
        placed.append(it)
        blocked.append(it.footprint_poly())
    seat = _anchor_targets(pf, off_board, 1.0) if pf and off_board else {}
    held: dict[str, list[Polygon]] = {"top": [], "bottom": []}  # envelopes already taken
    for it in sorted(off_board, key=lambda o: -(o.size_mm[0] * o.size_mm[1] if o.size_mm else 0)):
        it.side = "bottom"
        cx, cy = _centre(blocked) if fitted is None else (fitted.centroid.x, fitted.centroid.y)
        spot = seat.get(id(it))
        if it.role == "module" and spot is not None:
            cx, cy = spot[0], spot[1]
            it.side = "bottom" if spot[2] == "back" else "top"
        it.x, it.y = cx, cy
        if it.role == "module":
            _clear_of(it, held, on_board, fitted, spot is not None)
        held[it.side].append(it.footprint_poly())

    # controller GPIO for every peripheral signal, nearest pad first
    if mcu is not None:
        signals = sorted(
            {
                v
                for it in items
                if it is not mcu
                for v in it.pads.values()
                if v and power_net(v) is None and v != "RST_MCU" and not v.startswith("MX_")
            }
        )
        gpio = [num for num, name in mcu.meta["pins"].items() if GPIO_NAME.match(_clean(name))]
        gpio = [g for g in gpio if g not in mcu.pads]
        if len(signals) > len(gpio):
            log.append(f"{len(signals)} signals but {len(gpio)} free GPIO; extra left unwired")
            keep = set(signals[: len(gpio)])
            for it in items:
                it.pads = {k: v for k, v in it.pads.items() if power_net(v) or v in keep}
            signals = sorted(keep)
        mcu.pads.update(_assign_gpio(mcu, gpio, signals, items))
        log.append(f"pin budget: {len(signals)} GPIO needed, {mcu.label} has {len(gpio)} free")
    _drop_single_pad_nets(items)

    if fitted is not None:
        outline = fitted
    else:
        outline = _form_outline(placed, form, log) if form else _outline(placed)
    x0, y0, x1, y1 = outline.bounds
    log.append(
        f"board {x1 - x0:.1f} x {y1 - y0:.1f} mm, {len(placed)} footprints "
        f"({sum(1 for it in placed if it.meta.get('near') is not None)} support passives)"
    )
    ctrl = None
    if mcu is not None:
        ctrl = {"id": str(mcu.meta["instance_id"]), "label": mcu.label}
    return BoardPlan("main", items, outline, [], [], {}, ctrl, None, [], log)


# ---------------------------------------------------------------- nets


def _pads_from_pins(items: list[Item], log: list[str]) -> None:
    i2c_modules = 0
    for it in items:
        if it.fp is None:
            continue
        pins: dict[str, str] = it.meta.get("pins") or {}
        pad_numbers = {p.number for p in it.fp.pads}
        for num, name in pins.items():
            if num not in pad_numbers:
                continue
            clean = _clean(name)
            if not clean or SKIP_NAME.match(clean):
                continue
            net = power_net(clean)
            if net is None and it.role == "mcu":
                if clean in ("RST", "RESET", "NRST"):
                    net = "RST_MCU"
                else:
                    continue  # controller GPIO is assigned later
            if net is None:
                if clean in BUS:
                    net = BUS[clean]
                elif clean in PER_PART:
                    net = f"{clean}_{it.ref}"
                elif clean.isdigit():
                    continue
                else:
                    net = f"{clean[:8]}_{it.ref}"
            it.pads[num] = net
        if it.meta.get("module") and {"SDA", "SCL"} <= set(it.pads.values()):
            i2c_modules += 1
    if i2c_modules:
        log.append(f"{i2c_modules} I2C breakout(s) bring their own pull-ups")
    for it in items:
        it.meta["i2c_pullups_onboard"] = i2c_modules > 0


def _drop_single_pad_nets(items: list[Item]) -> None:
    count: dict[str, int] = {}
    for it in items:
        for v in it.pads.values():
            count[v] = count.get(v, 0) + 1
    for it in items:
        it.pads = {k: v for k, v in it.pads.items() if count.get(v, 0) > 1}


def _matrix_inputs(items: list[Item], mcu: Item | None, log: list[str]) -> None:
    """When the controller has fewer free GPIO than the signals need, wire the push buttons as a
    diode matrix (each switch to a column, a diode from the switch to its row) so n buttons cost
    rows + columns pins instead of n."""
    if mcu is None or not mcu.meta.get("pins"):
        return
    gpio = [n for n, name in mcu.meta["pins"].items() if GPIO_NAME.match(_clean(name))]
    free = len([g for g in gpio if g not in mcu.pads])

    def signals(of: list[Item]) -> set[str]:
        return {
            v
            for it in of
            if it is not mcu
            for v in it.pads.values()
            if v and power_net(v) is None and v != "RST_MCU"
        }

    need = len(signals(items))
    if need <= free:
        return
    keys = [
        it
        for it in items
        if it.role in ("button", "switch") and not it.meta.get("module") and it.fp is not None
    ]
    sig_pad = {}
    for it in keys:
        pads = [(n, v) for n, v in it.pads.items() if v and power_net(v) is None]
        if len(pads) == 1:
            sig_pad[id(it)] = pads[0]
    keys = [it for it in keys if id(it) in sig_pad]
    if len(keys) < 4:
        return
    spare = free - (need - len({sig_pad[id(it)][1] for it in keys}))
    best = None
    for rows in range(1, len(keys) + 1):
        cols = math.ceil(len(keys) / rows)
        if rows + cols <= spare and (best is None or rows + cols < best[0] + best[1]):
            best = (rows, cols)
    if best is None:
        log.append(f"{need} signals, {free} free GPIO: no matrix of {len(keys)} buttons fits")
        return
    rows, cols = best
    d_fp = footprint_ref(R.DIODE["footprint"])
    for i, it in enumerate(keys):
        num, _ = sig_pad[id(it)]
        gnd = next((n for n, v in it.pads.items() if power_net(v) is not None), None)
        it.pads[num] = f"COL{i % cols}"
        mx = f"MX_{it.ref}"
        if gnd is not None:
            it.pads[gnd] = mx
        else:  # a switch whose second pad is not wired: take any other pad of the footprint
            other = next((p.number for p in it.fp.pads if p.number != num), None)
            if other is None:
                continue
            it.pads[other] = mx
        d = Item(
            f"DM{i + 1}", "diode", d_fp, 0, 0, 0, "top", pads={"1": f"ROW{i // cols}", "2": mx}
        )
        d.label, d.height_mm, d.meta = "1N4148W SOD-123", 1.2, {"near": it}
        items.append(d)
    log.append(
        f"{need} signals, {free} free GPIO: {len(keys)} buttons wired as a {rows} x {cols} "
        f"diode matrix ({rows + cols} pins)"
    )


def _support_parts(items: list[Item], log: list[str]) -> list[Item]:
    """Datasheet support passives (and a battery connector) for the chosen parts."""
    out: list[Item] = []
    cap_fp = footprint_ref(R.CAP["footprint"])
    res_fp = footprint_ref(RES_FP)
    n = {"C": 0, "R": 0}

    def passive(kind: str, a: str, b: str, label: str, near: Item) -> Item:
        n[kind] += 1
        fp = cap_fp if kind == "C" else res_fp
        it = Item(f"{kind}{n[kind]}", "passive", fp, 0, 0, 0, "top", pads={"1": a, "2": b})
        it.label, it.height_mm, it.meta = label, 0.6, {"near": near}
        return it

    for it in items:
        nets = set(it.pads.values())
        if it.role == "regulator":
            vin = next((v for v in ("VBUS", "VBAT") if v in nets), None)
            if vin:
                out.append(passive("C", vin, "GND", REG_CAP, it))
            if "3V3" in nets:
                out.append(passive("C", "3V3", "GND", REG_CAP, it))
        elif not it.meta.get("module") and it.role not in ("mcu", "battery", "passive"):
            if "GND" in nets and "3V3" in nets:
                out.append(passive("C", "3V3", "GND", DECOUPLE_CAP, it))
    all_nets = {v for it in items for v in it.pads.values()}
    if {"SDA", "SCL"} <= all_nets and not any(it.meta.get("i2c_pullups_onboard") for it in items):
        host = next((it for it in items if "SDA" in it.pads.values()), items[0])
        out.append(passive("R", "SDA", "3V3", PULLUP, host))
        out.append(passive("R", "SCL", "3V3", PULLUP, host))
    for it in items:
        if it.role == "battery" and not it.on_pcb:
            conn = Item(
                "J_BAT",
                "battery_connector",
                footprint_ref(BAT_CONN_FP),
                0,
                0,
                0,
                "top",
                pads={"1": "VBAT", "2": "GND"},
                label="JST PH 2-pin battery connector (vertical)",
                height_mm=R.BATTERY_CONN["height_mm"],
            )
            mcu = next((m for m in items if m.role == "mcu"), None)
            conn.meta = {"near": mcu} if mcu is not None else {}
            out.append(conn)
            if mcu is not None:
                bat = next((k for k, v in mcu.meta["pins"].items() if power_net(v) == "VBAT"), None)
                if bat is not None:
                    mcu.pads[bat] = "VBAT"
    for it in items:  # an off-board module reaches the board through a power connector
        if it.role == "module" and not it.on_pcb:
            conn = Item(
                f"J_{it.ref}", "module_connector", footprint_ref(BAT_CONN_FP), 0, 0, 0, "top",
                pads={"1": "VBUS", "2": "GND"},
                label=f"JST PH 2-pin connector to {it.label}"[:60],
                height_mm=R.BATTERY_CONN["height_mm"],
            )  # fmt: skip
            mcu = next((m for m in items if m.role == "mcu"), None)
            conn.meta = {"near": mcu} if mcu is not None else {}
            out.append(conn)
    if out:
        log.append(
            "support parts: "
            + ", ".join(sorted({f"{o.label}" for o in out}))
            + f" ({len(out)} in all)"
        )
    return out


def _bbox_mm(record: dict[str, Any]) -> tuple[float, float, float] | None:
    bbox = (record.get("mechanical") or {}).get("bbox_mm") or {}
    lo, hi = bbox.get("min"), bbox.get("max")
    if not (lo and hi):
        return None
    w, h, t = (float(hi[i]) - float(lo[i]) for i in range(3))
    return (w, h, t) if min(w, h) > 0 else None


def _module_cell(part: dict[str, Any], record: dict[str, Any], ref: str, touch: set[str]) -> Item:
    """A module with its own envelope (panel, power supply, driver board): placed on the form,
    not packed on the PCB; a connector on the main board carries its supply."""
    w, h, t = _bbox_mm(record) or (1.0, 1.0, 1.0)
    return Item(
        ref, "module", None, 0, 0, 0, "bottom",
        label=str(record.get("display_name") or part.get("label") or "module")[:60],
        on_pcb=False, size_mm=(w, h), height_mm=t,
        meta={
            "instance_id": part["instance_id"],
            "pins": {},
            "slot_id": part.get("slot_id"),
            "touch": part.get("slot_id") in touch,
        },
    )  # fmt: skip


def _battery_cell(part: dict[str, Any], record: dict[str, Any], ref: str) -> Item:
    bbox = (record.get("mechanical") or {}).get("bbox_mm") or {}
    lo, hi = bbox.get("min"), bbox.get("max")
    if lo and hi:
        w, h, t = hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]
    else:
        (w, h), t = R.BATTERY_CELL["size_mm"], R.BATTERY_CELL["height_mm"]
    return Item(
        ref,
        "battery",
        None,
        0,
        0,
        0,
        "bottom",
        label=str(record.get("display_name") or R.BATTERY_CELL["label"])[:60],
        on_pcb=False,
        size_mm=(float(w), float(h)),
        height_mm=float(t),
        meta={"instance_id": part["instance_id"], "pins": {}},
    )


# ---------------------------------------------------------------- packing


def _height(record: dict[str, Any]) -> float:
    bbox = (record.get("mechanical") or {}).get("bbox_mm") or {}
    hi, lo = bbox.get("max"), bbox.get("min")
    if hi and lo:
        return round(float(hi[2]) - float(lo[2]), 2)
    return float((record.get("facets") or {}).get("height_mm") or 2.0)


def _area(it: Item) -> float:
    return it.footprint_poly().area


def _extent(it: Item) -> tuple[float, float]:
    x0, y0, x1, y1 = it.footprint_poly().bounds
    return (x1 - x0, y1 - y0)


def _centre(blocked: list[Polygon]) -> tuple[float, float]:
    if not blocked:
        return 0.0, 0.0
    c = unary_union(blocked).envelope.centroid
    return c.x, c.y


DIRECTIONS = [(1.0, 0.0), (-1.0, 0.0), (0.0, 1.0), (0.0, -1.0)]


def _shape_cost(w: float, h: float, form: dict[str, Any] | None) -> float:
    """Area of the smallest board of the target form that holds a w x h cluster."""
    if not form:
        return w * h + 0.3 * abs(w - h) ** 2  # small and near square
    if form.get("shape") == "round":
        return math.hypot(w, h) ** 2
    fw, fh = (float(v) for v in form.get("size_mm") or (1.0, 1.0))
    a = fw / fh if fh else 1.0
    return max(w, h * a) * max(w / a, h)


def _clear_of(
    it: Item,
    held: dict[str, list[Polygon]],
    on_board: list[Item],
    region: Polygon | None,
    anchored: bool,
) -> None:
    """Move an off-board module to the nearest spot, on either side, where its envelope overlaps
    no other module and, unless it is anchored to a feature, no board part on that side."""
    others = {
        side: list(held[side]) + [o.footprint_poly() for o in on_board if o.side == side]
        for side in ("top", "bottom")
    }
    x0, y0 = it.x, it.y
    shape = it.footprint_poly()
    bx0, by0, bx1, by1 = region.bounds if region is not None else shape.bounds
    best: tuple[float, float, float, str] | None = None
    step = 1.0
    reach = min(40, int(max(bx1 - bx0, by1 - by0) / step) + 1)
    for side in (it.side, "top" if it.side == "bottom" else "bottom"):
        for ring in range(reach):
            hit = None
            for i in range(-ring, ring + 1):
                for j in range(-ring, ring + 1):
                    if max(abs(i), abs(j)) != ring:
                        continue
                    dx, dy = i * step, j * step
                    moved = affinity.translate(shape, dx, dy)
                    if region is not None and not region.buffer(0.01).contains(moved):
                        continue
                    if any(moved.intersection(o).area > 0.01 for o in others[side]):
                        continue
                    d = math.hypot(dx, dy) + (0.0 if side == it.side else 2.0)
                    if hit is None or d < hit[0]:
                        hit = (d, dx, dy, side)
            if hit is not None:
                if best is None or hit[0] < best[0]:
                    best = hit
                break
    if best is not None:
        it.x, it.y, it.side = x0 + best[1], y0 + best[2], best[3]


def _best_spot(
    it: Item,
    anchor: Polygon | None,
    blocked: list[Polygon],
    gap: float,
    form: dict[str, Any] | None = None,
) -> tuple[float, float]:
    """Free spot beside the anchor (or the packed cluster) that keeps the board smallest."""
    shape = it.footprint_poly()  # item is at the origin until placed
    if not blocked:
        return 0.0, 0.0
    cluster = unary_union(blocked)
    base = anchor if anchor is not None else cluster
    best: tuple[float, tuple[float, float]] | None = None
    for d in DIRECTIONS:
        x, y = _search(shape, base, d, blocked, gap=gap, step=0.5)
        x0, y0, x1, y1 = cluster.bounds
        sx0, sy0, sx1, sy1 = shape.bounds
        bx0, by0 = min(x0, sx0 + x), min(y0, sy0 + y)
        bx1, by1 = max(x1, sx1 + x), max(y1, sy1 + y)
        w, h = bx1 - bx0, by1 - by0
        cost = _shape_cost(w, h, form)
        if anchor is not None:
            cost += 4.0 * math.hypot(x - anchor.centroid.x, y - anchor.centroid.y)
        if best is None or cost < best[0]:
            best = (cost, (x, y))
    assert best is not None
    return best[1]


CASE_ALLOWANCE_MM = 3.0  # case wall + clearance between the device outline and the board


def _form_outline(placed: list[Item], form: dict[str, Any], log: list[str]) -> Polygon:
    """Board outline in the device's own shape, inset from its size by the case allowance."""
    u = unary_union([it.footprint_poly() for it in placed])
    need = u.buffer(BOARD_MARGIN, join_style="mitre")
    c = need.envelope.centroid
    fw, fh = (float(v) for v in form.get("size_mm") or (0.0, 0.0))
    w, h = max(fw - 2 * CASE_ALLOWANCE_MM, 5.0), max(fh - 2 * CASE_ALLOWANCE_MM, 5.0)
    shape = form.get("shape") or "rect"

    def make(scale: float) -> Polygon:
        sw, sh = w * scale, h * scale
        if shape == "round":
            return Point(c.x, c.y).buffer(min(sw, sh) / 2, 128)
        r = min(sw, sh) * (0.22 if shape in ("rounded_rect", "squircle") else 0.05)
        r = max(r, CORNER_R)
        rect = box(c.x - sw / 2, c.y - sh / 2, c.x + sw / 2, c.y + sh / 2)
        return Polygon(rect.buffer(-r, join_style="mitre").buffer(r, join_style="round").exterior)

    scale = 1.0
    poly = make(scale)
    while not poly.contains(need) and scale < 6.0:
        scale *= 1.03
        poly = make(scale)
    x0, y0, x1, y1 = poly.bounds
    if scale > 1.0:
        log.append(
            f"{shape} outline grown {scale:.2f}x to {x1 - x0:.1f} x {y1 - y0:.1f} mm to fit the "
            f"parts (target {w:.0f} x {h:.0f} mm inside a {fw:.0f} x {fh:.0f} mm device)"
        )
    else:
        log.append(f"{shape} outline {x1 - x0:.1f} x {y1 - y0:.1f} mm from the device form")
    return poly.simplify(0.05)


def _outline(placed: list[Item]) -> Polygon:
    u = unary_union([it.footprint_poly() for it in placed]).envelope
    x0, y0, x1, y1 = u.bounds
    rect = box(x0 - BOARD_MARGIN, y0 - BOARD_MARGIN, x1 + BOARD_MARGIN, y1 + BOARD_MARGIN)
    rounded = rect.buffer(-CORNER_R, join_style="mitre").buffer(CORNER_R, join_style="round")
    return Polygon(rounded.exterior).simplify(0.05)


# ---------------------------------------------------------------- product form

FORM_INSET_MM = 3.5  # case wall + clearance: the board edge sits this far inside the silhouette
FORM_GRID_POINTS = 24000
FORM_TRIES = 6000


def form_region(pf: dict[str, Any], scale: float) -> Polygon:
    """The board outline: the silhouette (y up) in board coordinates (y down) inset by the case."""
    pts = [(x * scale, -y * scale) for x, y in pf["silhouette"]]
    sil = Polygon(pts)
    if not sil.is_valid:
        sil = sil.buffer(0)
    short = min(sil.bounds[2] - sil.bounds[0], sil.bounds[3] - sil.bounds[1])
    inset = min(FORM_INSET_MM, 0.12 * short)
    region = sil.buffer(-inset, join_style="round")
    if region.geom_type == "MultiPolygon":
        region = max(region.geoms, key=lambda g: g.area)
    return Polygon(region.exterior).simplify(0.05)


def _anchor_targets(
    pf: dict[str, Any], items: list[Item], scale: float
) -> dict[int, tuple[float, float, str]]:
    """Target centre (board coords) and mount for every item that has an anchor."""
    from bara.live.form import expand

    by_slot: dict[str, list[Item]] = {}
    for it in items:
        sid = it.meta.get("slot_id")
        if sid:
            by_slot.setdefault(sid, []).append(it)
    out: dict[int, tuple[float, float, str]] = {}
    used: dict[str, int] = {}
    for a in pf["anchors"]:
        group = by_slot.get(a["slot_id"], [])
        k0 = used.get(a["slot_id"], 0)
        n = max(1, int(a.get("count") or 1))
        take = group[k0 : k0 + n]
        if not take and k0 >= len(group) and group:
            take = []
        used[a["slot_id"]] = k0 + len(take)
        spots = expand(a, max(1, len(take)))
        for k, it in enumerate(take):
            x, y = spots[k % len(spots)]
            out[id(it)] = (x * scale, -y * scale, a["mount"])
    for sid, group in by_slot.items():  # instances no anchor claimed ride on the slot's last one
        last = next((a for a in reversed(pf["anchors"]) if a["slot_id"] == sid), None)
        for it in group[used.get(sid, 0) :]:
            if last is not None:
                out[id(it)] = (last["centre"][0] * scale, -last["centre"][1] * scale, last["mount"])
    return out


def _through(it: Item) -> bool:
    """A part with soldered leads through the board reaches the other side."""
    return it.fp is not None and any(p.kind == "thru_hole" for p in it.fp.pads)


def _shadow(it: Item) -> Polygon | None:
    """What a through-hole part takes from the opposite side: the hull of its lead pads, not its
    body (which sits on its own side), so small parts can sit under a display or module."""
    if it.fp is None:
        return None
    pads = [p for p in it.fp.pads if p.kind in ("thru_hole", "np_thru_hole")]
    if not pads:
        return None
    hull = unary_union(
        [box(p.x - p.w / 2, p.y - p.h / 2, p.x + p.w / 2, p.y + p.h / 2) for p in pads]
    ).convex_hull
    return it.world(hull)


def _attempt(
    order: list[Item],
    region: Polygon,
    targets: dict[int, tuple[float, float]],
    gaps: dict[int, float],
    flippable: set[int] | None = None,
) -> bool:
    """Put each item at the free spot nearest its target, on its own side first and, for a
    surface-mount part that has no spot there, on the other side; False when one cannot go."""
    prep = prepared.prep(region)
    x0, y0, x1, y1 = region.bounds
    step = max(1.0, math.sqrt(region.area / FORM_GRID_POINTS))
    gx, gy = np.meshgrid(np.arange(x0, x1, step), np.arange(y0, y1, step))
    cand = np.column_stack([gx.ravel(), gy.ravel()])
    cand = cand[[prep.contains(Point(float(a), float(b))) for a, b in cand]]
    if not len(cand):
        return False
    taken: dict[str, Polygon | None] = {"top": None, "bottom": None}

    def put(it: Item, side: str) -> bool:
        it.side = side
        it.x = it.y = 0.0
        rot0 = it.rot
        turns = (0.0, 90.0) if flippable and id(it) in flippable else (0.0,)
        other = "bottom" if side == "top" else "top"
        gap = gaps[id(it)]
        tx, ty = targets[id(it)]
        idx = np.argsort(np.hypot(cand[:, 0] - tx, cand[:, 1] - ty))[:FORM_TRIES]
        for turn in turns:
            it.rot = rot0 + turn
            it.x = it.y = 0.0
            base = it.footprint_poly()
            c0 = base.centroid
            shade = _shadow(it) if _through(it) else None
            for i in idx:
                dx, dy = float(cand[i, 0] - c0.x), float(cand[i, 1] - c0.y)
                poly = affinity.translate(base, dx, dy)
                if not prep.contains(poly):
                    continue
                under = affinity.translate(shade, dx, dy) if shade is not None else None
                if taken[side] is not None and taken[side].distance(poly) < gap:
                    continue
                if (
                    under is not None
                    and taken[other] is not None
                    and taken[other].distance(under) < gap
                ):
                    continue
                it.x, it.y = dx, dy
                taken[side] = poly if taken[side] is None else taken[side].union(poly)
                if under is not None:
                    taken[other] = under if taken[other] is None else taken[other].union(under)
                return True
        it.rot = rot0
        return False

    for it in order:
        own = it.side if it.side in ("top", "bottom") else "top"
        if put(it, own):
            continue
        if flippable and id(it) in flippable and not _through(it):
            if put(it, "bottom" if own == "top" else "top"):
                continue
        return False
    return True


def place_in_form(
    on_board: list[Item], mcu: Item | None, pf: dict[str, Any], log: list[str]
) -> Polygon:
    """Place every board item inside the product silhouette; returns the board outline.

    Items with an anchor go to the free spot nearest it (edge anchors to the rim); the controller
    sits at the centre of the free area; everything else packs outward from the controller,
    support passives beside their parent. Surface-mount parts with no room on the front go on the
    back. The product is never scaled to fit: parts that still do not fit log FORM_OVERFLOW,
    which fails the build.
    """
    scale = 1.0
    region = form_region(pf, scale)
    anchored = _anchor_targets(pf, on_board, scale)
    centre = region.representative_point()
    hub = (centre.x, centre.y)
    targets: dict[int, tuple[float, float]] = {}
    gaps: dict[int, float] = {}
    first: list[Item] = [it for it in on_board if id(it) in anchored]
    first.sort(key=lambda it: -_area(it))
    rest = [it for it in on_board if id(it) not in anchored]
    if mcu is not None and mcu in rest:
        rest.remove(mcu)
        rest.insert(0, mcu)
    rest[1 if mcu is not None else 0 :] = sorted(
        rest[1 if mcu is not None else 0 :],
        key=lambda it: (it.meta.get("near") is not None, -_area(it)),
    )
    order = first + rest
    for it in on_board:
        tgt = anchored.get(id(it))
        if tgt is not None:
            targets[id(it)] = (tgt[0], tgt[1])
            it.side = "bottom" if tgt[2] == "back" else "top"
        else:
            targets[id(it)] = hub
        gaps[id(it)] = PASSIVE_GAP if it.meta.get("near") is not None else PART_GAP
    # unanchored surface-mount parts may use the back of the board
    flippable = {id(it) for it in on_board if id(it) not in anchored and it is not mcu}
    ok = _attempt_with_follow(order, region, targets, gaps, mcu, set(anchored), flippable)
    areas = sorted(((_area(it), it) for it in on_board), key=lambda a: -a[0])
    widest = max(on_board, key=lambda it: max(_extent(it)), default=None)
    pf["fit_report"] = {
        "ok": ok,
        "footprints": len(on_board),
        "silhouette_mm2": round(Polygon([(x, y) for x, y in pf["silhouette"]]).area),
        "usable_mm2": round(region.area),
        "parts_mm2": round(sum(a for a, _ in areas)),
        "largest": [
            {"part": it.label or it.ref, "mm": [round(v, 1) for v in _extent(it)]}
            for _, it in areas[:3]
        ],
        "widest_mm": round(max(_extent(widest)), 1) if widest is not None else 0.0,
    }
    if not ok:
        r = pf["fit_report"]
        log.append(
            f"FORM_OVERFLOW: the parts do not fit the product silhouette on both board sides "
            f"({len(on_board)} footprints, {r['parts_mm2']} mm2 of footprints against "
            f"{r['usable_mm2']} mm2 usable per side); the product is never scaled to fit"
        )
        _attempt_loose(order, region)
        return region
    x0, y0, x1, y1 = region.bounds
    bottom = sum(1 for it in on_board if it.side == "bottom")
    log.append(
        f"board follows the product silhouette: {x1 - x0:.1f} x {y1 - y0:.1f} mm outline, "
        f"{sum(1 for it in on_board if id(it) in anchored)} parts snapped to anchors, "
        f"{bottom} on the back"
    )
    pf["scale"] = scale
    return region


def _attempt_with_follow(
    order: list[Item],
    region: Polygon,
    targets: dict[int, tuple[float, float]],
    gaps: dict[int, float],
    mcu: Item | None,
    anchored: set[int],
    flippable: set[int] | None = None,
) -> bool:
    """Run _attempt with followers retargeted: a support part at its parent, any other
    unanchored part at the controller, both read when the part is placed (parents come first)."""
    by_id = {id(it): it for it in order}

    class Follow(dict):
        def __getitem__(self, key: int) -> tuple[float, float]:
            it = by_id[key]
            near = it.meta.get("near")
            if near is not None:
                return near.centre()
            if mcu is not None and it is not mcu and key not in anchored:
                return mcu.centre()
            return super().__getitem__(key)

    return _attempt(order, region, Follow(targets), gaps, flippable)


def _attempt_loose(order: list[Item], region: Polygon) -> None:
    """Overflow: lay the unplaced parts in a row below the silhouette so the build still has a
    board to report on; the FORM_OVERFLOW log line turns into a failing check."""
    x0, _, _, y1 = region.bounds
    x = x0
    for it in order:
        it.x = it.y = 0.0
        b = it.footprint_poly().bounds
        it.x, it.y = x - b[0], y1 + 3.0 - b[1]
        x += (b[2] - b[0]) + PART_GAP
