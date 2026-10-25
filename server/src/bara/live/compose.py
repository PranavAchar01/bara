"""Compose stage: slots from the spec, faceted filtering, constraint propagation, picks.

Each slot is narrowed by filters (requirement, compatibility with parts already chosen,
logic level, GPIO budget, I2C address room, KiCad footprint availability). The model
only ever picks among the survivors, by enum id C1..C8. With no key set, or a single
survivor, the deterministic default (highest score) is used and the decision says so.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import math
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from bara.board.generic import gpio_pins
from bara.kicad_generated import GLB_URL, SERVER, KicadIndex, glb_stem
from bara.live import completeness as cp
from bara.live import seven_seg
from bara.live.ask import ask_json
from bara.live.brief import DISPLAY_TYPES
from bara.live.catalog_source import (
    PartSource,
    card_for,
    facet_match,
    gpio_count,
    i2c_addresses,
    interface_of,
    logic_voltage,
    model_asset,
    part_functions,
)
from bara.live.completeness import Completeness, Need
from bara.live.fetch import (
    BUDGET_PER_NEED_S,
    TOTAL_BUDGET_S,
    Resolver,
    as_overlay,
    stock_primitive,
    typed_mpns,
)
from bara.live.layout import PITCH_MM, KeyboardPlan, feature_sides, pin_need, stab_size
from bara.live.llm_json import call_json

log = logging.getLogger(__name__)

Emit = Callable[..., dict[str, Any]]

MAX_SURVIVORS = 8
# function ids that name no electrical job: the block is housing material, made by the case
NON_ELECTRICAL = frozenset({"other", "mech.enclosure"})
# the served asset tree, wherever BARA_DATA_DIR puts it (as Settings.assets_dir reads it)
ASSETS_DIR = Path(os.environ.get("BARA_DATA_DIR", SERVER / "data")) / "assets"
HALF_GAP_MM = 40.0  # inner-edge gap between split halves in the first placement guess

# function id -> (slot id, label, instance prefix, feature kind for side assignment)
SLOT_KINDS: dict[str, tuple[str, str, str, str | None]] = {
    "input.key": ("switches", "Switches", "sw", None),
    "mech.keycap": ("keycaps", "Keycaps", "cap", None),
    "mech.stabilizer": ("stabilizers", "Stabilizers", "stab", None),
    "input.rotary_encoder": ("encoder", "Rotary encoder", "enc", "knob"),
    "mech.knob": ("knob", "Knob", "knob", "knob"),
    "input.trackball": ("trackball", "Trackball", "tb", "trackball"),
    "compute.mcu": ("controller", "Controller", "mcu", None),
    "power.battery": ("battery", "Battery", "bat", None),
    "interconnect.jack": ("jack", "TRRS jack", "jack", None),
    "interconnect.cable": ("cable", "Split cable", "cable", None),
}
# one per key on each half: the board puts a matrix diode under every switch
PER_KEY = ("input.key", "component.diode")
# a hot-swap socket is one per switch too, though its slot is a generic connector until picked
HOTSWAP_PREFIX = "hs:"
# Functions that are not a part slot: the controller covers comms and USB, the generated
# case is the enclosure, the KiCad board is the PCB.
NO_SLOT_PREFIX = ("comms.",)
NO_SLOT = {
    "power.usb_in",
    "power.charger",
    "mech.enclosure",
    "mech.chassis",
    "interconnect.pcb",
    "input.key_matrix",
    "mech.plate",
    "mech.foam",
    "mech.foot",  # stick-on pads under the finished case
}
PERIPHERAL_KIND = {
    "encoder": "knob",
    "trackball": "trackball",
}
COMPAT_PARAMS = ("family", "stem", "form_factor", "chemistry")


# LCSC category in the product URL: a driver, controller or bridge chip, never a panel
DRIVER_CATEGORY = re.compile(
    r"lcsc\.com/product-detail/[^/_]*(Driver|Controller|Interface|Bridge)", re.I
)
# a panel is glass on a ribbon or a module board, never sold in a chip package
IC_PACKAGE = re.compile(
    r"^(SOIC|SOP|SSOP|TSSOP|MSOP|QFN|VQFN|WQFN|DFN|QFP|LQFP|TQFP|BGA|LGA|SOT|TSOT|SC-?70|WLCSP)",
    re.I,
)


CONNECTOR_PACKAGE = re.compile(r"^(FPC|FFC|CONN|HDR|PinHeader|PinSocket)|connector", re.I)
PANEL_MIN_MM = 6.0  # the smallest glass (a 0.42 in OLED, a 0.28 in digit) is wider than this


def not_a_panel(part: dict[str, Any]) -> bool:
    """A display slot's candidate that cannot be glass: a ribbon connector or header (it is
    what a panel plugs into), or a body too narrow to hold any viewing area."""
    facets = part.get("facets") or {}
    if CONNECTOR_PACKAGE.search(str(facets.get("package") or "")):
        return True
    bbox = (part.get("mechanical") or {}).get("bbox_mm") or {}
    lo, hi = bbox.get("min"), bbox.get("max")
    if lo and hi:
        w, d = sorted((abs(float(hi[0]) - float(lo[0])), abs(float(hi[1]) - float(lo[1]))))
        return w < PANEL_MIN_MM
    return False


SCREEN_TOLERANCE = 0.35  # a 2.8 in ask takes 2.4 to 3.5 in glass, never a 4.3 in panel


def wrong_size(part: dict[str, Any], want_in: float | None) -> bool:
    """A panel whose stated diagonal is far from the asked size: it would regrow the case."""
    have_in = cp.display_inches(part)
    return bool(want_in and have_in and abs(have_in - want_in) / want_in > SCREEN_TOLERANCE)


def is_screen_fn(function_id: str) -> bool:
    """A display function that frames a viewing area (not an indicator light)."""
    return function_id.startswith("display.") and function_id != "display.indicator_led"


def closest_size(parts: list[dict[str, Any]], want_in: float | None) -> dict[str, Any]:
    """The panel whose stated diagonal is nearest the asked size (the first when none is asked
    or none states one): a 2.4 in ask takes 3.2 in glass before 4.3 in glass."""
    if not want_in:
        return parts[0]

    def gap(p: dict[str, Any]) -> float:
        have = cp.display_inches(p)
        return abs(have - want_in) if have else float("inf")

    return min(parts, key=gap)


def _function_names(part: dict[str, Any], facet: str, op: str, value: Any) -> bool:
    """A part with no value for a typed facet whose own primary function names it: a
    seven-segment digit from the KiCad library is display_type seven_segment by what it is."""
    if op != "eq" or (part.get("facets") or {}).get(facet) is not None:
        return False
    kind = facet.removesuffix("_type")
    return any(
        f.get("primary") and f.get("function_id") == f"{kind}.{value}"
        for f in part.get("functions") or []
    )


def names_typed_mpn(part: dict[str, Any], typed: set[str]) -> bool:
    mpn = re.sub(r"[^a-z0-9]", "", str(part.get("mpn") or part.get("display_name") or "").lower())
    return bool(mpn) and any(mpn.startswith(t) for t in typed)


def is_chip(part: dict[str, Any]) -> bool:
    """A part whose datasheet category or package says it is an IC, whatever it was tagged."""
    package = str((part.get("facets") or {}).get("package") or "")
    return bool(
        DRIVER_CATEGORY.search(str(part.get("datasheet") or "")) or IC_PACKAGE.match(package)
    )


def _model_from_footprint(part: dict[str, Any], assets: list[dict[str, Any]]) -> None:
    """A catalog model that was never made (no file on disk) is replaced by the 3D model of
    the part's own KiCad footprint, converted on first request, so the part is drawn as
    itself instead of as a box."""
    fp = str(part.get("footprint") or "")
    if ":" not in fp:
        return
    package = str((part.get("facets") or {}).get("package") or "")
    models = [a for a in assets if a.get("kind") == "glb" and a.get("role", "model") == "model"]
    for a in models:
        url = str(a.get("url") or "")
        if not url.startswith("/assets/") or "/kicad_gen/" in url:
            if a.get("status") != "missing":
                return  # remote, or converted on first request
            continue
        if a.get("status") != "missing" and (ASSETS_DIR / url.removeprefix("/assets/")).is_file():
            return
    index = KicadIndex.open()
    lender = index.model_footprint(fp) if index is not None else None
    if lender is None and index is not None and fp.startswith("easyeda:"):
        # an EasyEDA footprint names no KiCad one; its package (SOIC-16, 7.5 x 10.3 mm,
        # 1.27 mm pitch) still finds the library footprint with the same outline
        lender = index.package_lender(package)
    if lender is None:
        return
    url = f"{GLB_URL}/{glb_stem(lender)}.glb"
    if not models:  # a part that never had a model is drawn from its footprint's own
        models = [
            {
                "asset_id": f"a_{glb_stem(lender)}_glb",
                "kind": "glb",
                "role": "model",
                "content_type": "model/gltf-binary",
            }
        ]
        assets.append(models[0])
    for a in models:
        a["url"] = url
        a["origin"] = "generated"
        a["status"] = "pending"


CELL_FUNCTIONS = ("power.battery", "power.coin_cell")
LI_ION = {"lipo", "liion", "li-ion", "li_ion", "lithium_ion", "li-po", "lithium_polymer"}


def _chemistry_of(part: dict[str, Any]) -> str:
    """The cell chemistry a part holds, charges or runs from ("" when it says nothing); the
    lithium-ion family is one kind (a pouch cell and an 18650 take the same charger)."""
    iface = interface_of(part, "battery", "requires") or {}
    chem = (iface.get("params") or {}).get("chemistry") or (part.get("facets") or {}).get(
        "chemistry"
    )
    chem = str(chem or "").strip().lower()
    return "li_ion" if chem in LI_ION else chem


def _holds_cell(part: dict[str, Any]) -> bool:
    """A cell or cell holder (its primary function is a battery), not a part that runs from one."""
    return any(
        f.get("primary") and f.get("function_id") in CELL_FUNCTIONS
        for f in part.get("functions") or []
    )


def _chemistry_fits(part: dict[str, Any], want: str) -> bool:
    """A part of the wanted chemistry, or a plain connector that wires the cell off the board;
    a holder whose chemistry is unknown is not assumed to fit."""
    chem = _chemistry_of(part)
    return chem == want if chem else not _holds_cell(part)


@dataclass
class Instance:
    instance_id: str
    side: str
    quantity: int
    layout_id: str | None = None
    # layout keys this instance covers, by key width (u); None = every key
    key_widths: tuple[float, ...] | None = None


@dataclass
class Slot:
    slot_id: str
    label: str
    function_id: str
    criticality: str
    order: int
    instances: list[Instance]
    feature: str | None = None
    state: str = "pending"
    candidates_total: int | None = None
    candidates_left: int | None = None
    chosen: dict[str, Any] | None = None
    covered_by: str | None = None  # slot_id whose chosen part also provides this function
    need: Need | None = None  # set when the completeness invariant added this slot
    unresolved: str | None = None  # why a required slot has no part
    drives: str | None = None  # a segment driver: slot_id of the bare display it multiplexes

    @property
    def quantity(self) -> int:
        return sum(i.quantity for i in self.instances)

    def json(self) -> dict[str, Any]:
        sides = {i.side for i in self.instances}
        return {
            "slot_id": self.slot_id,
            "label": self.label[:60],
            "function_id": self.function_id,
            "criticality": self.criticality,
            "quantity": max(1, self.quantity),
            "side": sides.pop() if len(sides) == 1 else "none",
            "order": self.order,
            "state": self.state,
            "candidates_total": self.candidates_total,
            "candidates_left": self.candidates_left,
            "chosen_part_id": (self.chosen or {}).get("part_id"),
            "instance_ids": (
                [i.instance_id for i in self.instances] if self.state == "decided" else []
            ),
            "from_design": False,
        }


@dataclass
class Filter:
    facet: str
    op: str
    value: Any
    reason: str
    label: str
    test: Callable[[dict[str, Any]], bool]
    from_slot_id: str | None = None
    req_id: str | None = None
    relaxable: bool = False


@dataclass
class ComposeResult:
    slots: list[Slot]
    parts: list[dict[str, Any]] = field(default_factory=list)
    chosen_parts: dict[str, dict[str, Any]] = field(default_factory=dict)  # slot -> part
    pin_budget: dict[str, Any] = field(default_factory=dict)
    log: list[str] = field(default_factory=list)
    error: str | None = None  # why nothing could be composed


def _side_suffix(side: str) -> str:
    return {"left": "_l", "right": "_r", "center": "_c"}.get(side, "")


def _is_hotswap(part: dict[str, Any] | None) -> bool:
    return bool(part) and str(part.get("part_id", "")).startswith(HOTSWAP_PREFIX)


def _per_key(base_id: str, plan: KeyboardPlan) -> list[Instance]:
    """One BOM line per half, as many as that half has keys."""
    return [Instance(f"{base_id}{_side_suffix(h.side)}", h.side, len(h.keys)) for h in plan.halves]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", text.lower()).strip("_")[:40] or "x"


def derive_slots(
    spec: dict[str, Any],
    brief: dict[str, Any],
    plan: KeyboardPlan | None,
    comp: Completeness | None = None,
) -> list[Slot]:
    split = brief.get("layout_style") == "split"
    halves = ["left", "right"] if split else ["none"]
    functions = [f["function_id"] for f in spec.get("functions", [])]
    required = {f["function_id"]: f.get("required", True) for f in spec.get("functions", [])}
    counts = {f["function_id"]: int(f.get("count") or 1) for f in spec.get("functions", [])}
    if (
        plan is not None
        and not str(brief.get("switch_family") or "mx").startswith("choc")
        and any(h.stabilized for h in plan.halves)
    ):
        # wide keys need stabilizers; the board places one footprint under each
        functions.append("mech.stabilizer")
        required["mech.stabilizer"] = True
    if split and brief.get("wireless") == "none":
        functions += ["interconnect.jack", "interconnect.cable"]
        required["interconnect.jack"] = required["interconnect.cable"] = True
    slots: list[Slot] = []
    seen: set[str] = set()
    need_fids = {n.function_id for n in (comp.needs.values() if comp else [])}
    for fid in functions:
        if fid in NO_SLOT or fid.startswith(NO_SLOT_PREFIX) or fid in seen:
            continue
        if fid in need_fids:  # the device's own slot (below) replaces the generic one
            continue
        seen.add(fid)
        if fid in SLOT_KINDS:
            slot_id, label, prefix, feature = SLOT_KINDS[fid]
        elif fid.startswith("display."):
            slot_id, label, prefix, feature = "display", "Display", "disp", "screen"
        else:
            tail = fid.split(".", 1)[-1]
            slot_id = _slug(tail)
            label = tail.replace("_", " ").capitalize()
            prefix = _slug(tail)[:10]
            feature = None
        instances: list[Instance] = []
        if fid in (*PER_KEY, "mech.keycap", "mech.stabilizer") and plan is not None:
            for half in plan.halves:
                lay = (
                    f"lay_{'l' if half.side == 'left' else 'r' if half.side == 'right' else 'main'}"
                )
                base_id = f"u_{prefix}{_side_suffix(half.side)}"
                if fid in PER_KEY:
                    # switches sit on the layout's keys; diodes are counted, the board places them
                    on = lay if fid == "input.key" else None
                    instances.append(Instance(base_id, half.side, len(half.keys), layout_id=on))
                    continue
                # one BOM line per physical size: a 6.25u spacebar is not a 1u cap
                groups: dict[float, list[float]] = {}
                keys = half.stabilized if fid == "mech.stabilizer" else half.keys
                for k in keys:
                    w = float(k.get("w_u", 1.0))
                    size = stab_size(w) if fid == "mech.stabilizer" else w
                    groups.setdefault(size, []).append(w)
                for size, ws in sorted(groups.items()):
                    instances.append(
                        Instance(
                            base_id if size == 1.0 else f"{base_id}_{size:g}u".replace(".", "_"),
                            half.side,
                            len(ws),
                            layout_id=lay,
                            key_widths=tuple(sorted(set(ws))),
                        )
                    )
        elif fid in ("compute.mcu", "power.battery", "interconnect.jack"):
            instances = [Instance(f"u_{prefix}{_side_suffix(s)}", s, 1) for s in halves]
        elif feature is not None:
            sides = feature_sides(brief, feature, split) or [halves[0]]
            per: dict[str, int] = {}
            for s in sides:
                per[s] = per.get(s, 0) + 1
            counter: dict[str, int] = {}
            for s in sides:
                counter[s] = counter.get(s, 0) + 1
                if plan is None:  # identical copies on one side are one BOM line, qty N
                    if counter[s] == 1:
                        instances.append(Instance(f"u_{prefix}{_side_suffix(s)}", s, per[s]))
                    continue
                suffix = _side_suffix(s) + (f"_{counter[s]}" if per[s] > 1 else "")
                instances.append(Instance(f"u_{prefix}{suffix}", s, 1))
        elif fid == "mech.wheel":
            instances = [Instance(f"u_{prefix}_{i}", "none", 1) for i in (1, 2)]
        elif counts.get(fid, 1) > 1:
            # identical copies are one BOM line with a quantity; the board places N footprints
            instances = [Instance(f"u_{prefix}", "none", counts[fid])]
        else:
            instances = [Instance(f"u_{prefix}", "none", 1)]
        critical = required.get(fid, True)
        slots.append(
            Slot(
                slot_id=slot_id,
                label=label,
                function_id=fid,
                criticality="critical" if critical else "optional",
                order=0,
                instances=instances,
                feature=feature,
            )
        )
    seen: list[Any] = []
    for need in comp.needs.values() if comp else []:
        if any(
            n.function_id == need.function_id
            and (n.key.startswith(need.key) or need.key.startswith(n.key))
            for n in seen
        ):  # one block named twice ("scroll_wheel" and "scroll_wheel_encoder_with...")
            continue
        seen.append(need)
        slots.append(
            Slot(
                slot_id=need.key,
                label=cp.short_label(need.label),
                function_id=need.function_id,
                criticality="critical",
                order=0,
                instances=[Instance(f"u_{need.inst_prefix}", "none", max(1, need.count))],
                need=need,
            )
        )
    ids: set[str] = set()
    for slot in slots:  # ten-letter prefixes can collide; every instance id is unique
        for inst in slot.instances:
            base, n = inst.instance_id, 2
            while inst.instance_id in ids:
                inst.instance_id, n = f"{base}{n}", n + 1
            ids.add(inst.instance_id)
    rank = {
        "charger": 84,
        "switches": 0,
        "keycaps": 1,
        "stabilizers": 2,
        "controller": 80,
        "battery": 81,
        "jack": 82,
        "cable": 83,
    }
    slots.sort(key=lambda s: rank.get(s.slot_id, 10))
    for i, slot in enumerate(slots):
        slot.order = i
    return slots


def _mah(part: dict[str, Any]) -> float | None:
    v = (part.get("facets") or {}).get("capacity_mah")
    return float(v) if isinstance(v, int | float) else None


def _compat_label(params: dict[str, Any]) -> str:
    for key in COMPAT_PARAMS:
        if key in params:
            return f"{str(params[key]).replace('_', ' ')} {key.replace('_', ' ')}"
    return "compatible"


def _mates(cand: dict[str, Any], chosen: dict[str, Any]) -> tuple[bool, str | None]:
    """Whether cand mates with chosen on every shared mechanical interface type."""
    label = None
    for a, b in ((cand, chosen), (chosen, cand)):
        for req in a.get("interfaces", []):
            if req.get("role") != "requires":
                continue
            for prov in b.get("interfaces", []):
                if prov.get("role") != "provides" or prov.get("type") != req.get("type"):
                    continue
                rp, pp = req.get("params") or {}, prov.get("params") or {}
                keys = [k for k in COMPAT_PARAMS if k in rp and k in pp]
                if not keys:
                    continue
                label = prov.get("label") or _compat_label(pp)
                if any(str(rp[k]).lower() != str(pp[k]).lower() for k in keys):
                    return False, label
    return True, label


def _shares_typed_interface(cand: dict[str, Any], chosen: dict[str, Any]) -> bool:
    for a, b in ((cand, chosen), (chosen, cand)):
        for req in a.get("interfaces", []):
            if req.get("role") != "requires":
                continue
            for prov in b.get("interfaces", []):
                if prov.get("role") == "provides" and prov.get("type") == req.get("type"):
                    rp, pp = req.get("params") or {}, prov.get("params") or {}
                    if any(k in rp and k in pp for k in COMPAT_PARAMS):
                        return True
    return False


def slot_check(slot: Slot) -> dict[str, Any] | None:
    """The check row for one slot: a critical slot must be filled; an optional one that cannot
    be filled is left out with a note (unknown), never a failure."""
    ok = slot.chosen is not None or slot.covered_by is not None
    critical = slot.criticality == "critical"
    if not critical and ok:
        return None
    rule = "slot.critical_filled" if critical else "slot.optional_missing"
    if ok and slot.chosen:
        message = f"{slot.label}: {slot.chosen.get('display_name')}"
    elif ok:
        message = (
            f"{slot.label}: made by the case"
            if slot.covered_by == "case"
            else f"{slot.label}: covered by the {slot.covered_by} part"
        )
    elif slot.unresolved:
        message = f"{slot.label}: REQUIRED, no part ({slot.unresolved})"
    elif not critical:
        message = f"{slot.label}: optional, left out (no catalog part passes)"
    else:
        message = f"{slot.label}: no catalog part passes the filters"
    return {
        "check_key": f"{rule}:{slot.slot_id}",
        "rule_id": rule,
        "status": "pass" if ok else ("fail" if critical else "unknown"),
        "severity": "critical" if critical else "info",
        "message": message[:300],
        "subjects": [{"slot_id": slot.slot_id}],
        "stage": "compose",
    }


class Composer:
    def __init__(
        self,
        source: PartSource,
        spec: dict[str, Any],
        brief: dict[str, Any],
        plan: KeyboardPlan | None,
        settings: Any,
        board_controllers: dict[str, int] | None = None,
        blocks: dict[str, Any] | None = None,
    ) -> None:
        self.source = as_overlay(source)
        self.spec = spec
        self.brief = brief
        self.plan = plan
        self.settings = settings
        # registry controller id -> GPIO count the KiCad board library offers
        self.board_controllers = board_controllers or {}
        # completeness invariant: controller, power path and the I/O the device implies
        self.comp = cp.apply(
            spec,
            brief,
            lambda fid: bool(self.source.query(function=fid, limit=1)),
            blocks,
            keyboard=plan is not None,
        )
        self.resolver = Resolver(
            self.source, budget_s=max(TOTAL_BUDGET_S, BUDGET_PER_NEED_S * len(self.comp.needs))
        )
        self.fetched: list[dict[str, Any]] = []  # rows added during this build
        self.extra: dict[str, list[dict[str, Any]]] = {}  # slot id -> parts found for it
        self.near_miss: dict[str, list[dict[str, Any]]] = {}  # slot id -> parts vet turned down
        self.slots = derive_slots(spec, brief, plan, self.comp)
        self.result = ComposeResult(slots=self.slots)
        self.decision_n = 0
        self.warning_n = 0
        self.use_model = bool(
            os.environ.get("CEREBRAS_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
        )

    # ---- candidates ---------------------------------------------------------------
    def base(self, slot: Slot) -> list[dict[str, Any]]:
        if slot.need is not None:
            pool = self.resolver.pool(slot.need)
            have = {p["part_id"] for p in pool}
            pool += [p for p in self.extra.get(slot.slot_id, []) if p["part_id"] not in have]
            if slot.slot_id == "charger":  # a charger, not a second controller that has one
                pool = [p for p in pool if "compute.mcu" not in part_functions(p)]
            return pool
        return self.source.query(function=slot.function_id, limit=500)

    def board_controller_for(self, part: dict[str, Any]) -> str | None:
        pid = part["part_id"].lower()
        name = str(part.get("display_name", "")).lower()
        for cid in self.board_controllers:
            if cid in pid or cid.replace("_", "") in re.sub(r"[^a-z0-9]", "", name):
                return cid
        return None

    def controller_gpio(self, part: dict[str, Any]) -> int | None:
        cid = self.board_controller_for(part)
        if cid is not None:
            return self.board_controllers[cid]
        return gpio_count(part) or gpio_pins(part)  # no typed gpio interface: its KiCad pins

    def pin_need_for(self, side: str) -> tuple[int, list[str]]:
        half = None
        if self.plan is not None:
            half = next(
                (h for h in self.plan.halves if h.side == side or side == "none"),
                self.plan.halves[0],
            )
        peripherals = []
        for slot in self.slots:
            if slot.slot_id in (
                "switches",
                "keycaps",
                "stabilizers",
                "controller",
                "battery",
                "cable",
                "knob",
            ):
                continue
            if slot.function_id.startswith(("mech.", "power.")) and slot.need is None:
                continue  # feet, mounts and power parts cost no controller pins
            if slot.function_id in PER_KEY or _is_hotswap(slot.chosen):
                continue  # matrix diodes and sockets ride on the key matrix's own pins
            if any(o.drives == slot.slot_id for o in self.slots):
                continue  # a bare display behind its driver chip: the chip's wires are the cost
            for inst in slot.instances:
                if inst.side != side and side != "none":
                    continue
                if slot.need is not None:
                    if slot.need.pin_kind:
                        n = max(1, inst.quantity) * slot.need.pin_mult
                        for _ in range(n):
                            peripherals.append(
                                {
                                    "kind": slot.need.pin_kind,
                                    "label": slot.label,
                                    "part": slot.chosen or {},
                                }
                            )
                    continue
                kind = PERIPHERAL_KIND.get(slot.slot_id)
                if slot.slot_id == "display":
                    kind = "screen_epaper" if "epaper" in slot.function_id else "screen"
                elif slot.function_id.startswith("sense."):
                    kind = "sensor"
                elif slot.function_id.startswith("output.motor"):
                    kind = "motor"
                elif slot.slot_id == "jack":
                    kind = None
                kind = kind or "button"
                for _ in range(max(1, inst.quantity)):
                    peripherals.append(
                        {"kind": kind, "label": slot.label, "part": slot.chosen or {}}
                    )
        wired = self.brief.get("layout_style") == "split" and self.brief.get("wireless") == "none"
        return pin_need(half, peripherals, wired)

    def filters_for(self, slot: Slot, cands: list[dict[str, Any]]) -> list[Filter]:
        filters: list[Filter] = []
        # a device requirement describes the parts whose own function this slot is: a speaker
        # slot offered an audio MCU (a speaker only as a side function) takes no radio filter
        own = [
            p
            for p in cands
            if any(
                f.get("primary") and f.get("function_id") == slot.function_id
                for f in p.get("functions") or []
            )
        ] or cands
        present = {k for p in own for k in (p.get("facets") or {})}
        # 1. requirements from the spec, where the slot's parts carry that facet
        for req in self.spec.get("hard_requirements", []) + self.spec.get("soft_requirements", []):
            facet, op, value = req["facet"], req["op"], req["value"]
            soft = req in self.spec.get("soft_requirements", [])
            if facet == "wireless" and slot.slot_id == "controller":
                fn = f"comms.{value}"
                filters.append(
                    Filter(
                        facet,
                        "has",
                        value,
                        "requirement",
                        req.get("label") or fn,
                        lambda p, fn=fn, v=value: (
                            fn in part_functions(p) or facet_match(p, "wireless", "eq", v)
                        ),
                        req_id=req["req_id"],
                    )
                )
                continue
            if facet == "power_source" and value == "battery" and slot.slot_id == "controller":
                if any(s.function_id == "power.charger" for s in self.slots if s is not slot):
                    continue  # the design charges its own cell: a bare module runs off its rail
                filters.append(
                    Filter(
                        facet,
                        "has",
                        "battery",
                        "requirement",
                        "Runs on battery",
                        lambda p: (
                            interface_of(p, "battery", "requires") is not None
                            or "power.charger" in part_functions(p)
                        ),
                        req_id=req["req_id"],
                    )
                )
                continue
            if facet not in present or facet in ("split", "key_count"):
                continue
            # how the device is powered filters the parts that power it, not a speaker module
            if facet == "power_source" and not slot.function_id.startswith("power."):
                continue
            # the screen type names the device's screen; an indicator LED is no screen
            screen = slot.function_id.removeprefix("display.")
            if facet == "display_type" and screen not in DISPLAY_TYPES:
                continue
            op_ = "eq" if op in ("has", "in") else op
            filters.append(
                Filter(
                    facet,
                    op,
                    value,
                    "requirement",
                    req.get("label") or f"{facet} {value}",
                    lambda p, f=facet, o=op_, v=value: (
                        facet_match(p, f, o, v) or _function_names(p, f, o, v)
                    ),
                    req_id=req["req_id"],
                    relaxable=soft,
                )
            )
        # 1a. a screen slot takes glass: a driver chip or ribbon connector tagged with the
        # display's function is what the panel plugs into, not the panel
        if slot.function_id.startswith("display.") and slot.function_id not in (
            "display.indicator_led",
        ):
            filters.append(
                Filter(
                    "kind",
                    "eq",
                    "panel",
                    "requirement",
                    "A panel, not its driver chip",
                    lambda p: not (is_chip(p) or not_a_panel(p)),
                )
            )
        # 1b. spec numbers: battery size from the mass target and battery life
        if slot.slot_id == "battery" and slot.need is None:
            lo, hi = cp.battery_limits(self.comp)
            mass = self.comp.numbers.get("mass_g")
            if hi is not None:
                filters.append(
                    Filter(
                        "capacity_mah",
                        "lte",
                        hi,
                        "requirement",
                        f"Battery <= {hi:.0f} mAh ({mass:g} g device)",
                        lambda p, hi=hi: _mah(p) is not None and _mah(p) <= hi,
                        relaxable=True,
                    )
                )
            if lo is not None:
                filters.append(
                    Filter(
                        "capacity_mah",
                        "gte",
                        lo,
                        "requirement",
                        f"Battery >= {lo:.0f} mAh for the stated life",
                        lambda p, lo=lo: _mah(p) is not None and _mah(p) >= lo,
                        relaxable=True,
                    )
                )
        # 2. compatibility with every part already chosen
        for other in self.slots:
            if other.chosen is None or other is slot:
                continue
            chosen = other.chosen
            if not any(_shares_typed_interface(c, chosen) for c in cands):
                continue
            _, label = next(
                (_mates(c, chosen) for c in cands if _shares_typed_interface(c, chosen)),
                (True, None),
            )
            filters.append(
                Filter(
                    "interface",
                    "eq",
                    label or "compatible",
                    "compatibility",
                    (label or "Mates with " + other.label)[:60],
                    lambda p, ch=chosen: _mates(p, ch)[0],
                    from_slot_id=other.slot_id,
                )
            )
        # 2b. a part that charges or runs from the main cell names its chemistry; the cell
        # has to be that kind (and the other way round for the charger). Another cell holder
        # (a backup coin cell) holds its own cell and says nothing about this one.
        if slot.function_id in ("power.battery", "power.charger"):
            for other in self.slots:
                want = _chemistry_of(other.chosen) if other.chosen else ""
                if other is slot or not want:
                    continue
                if slot.function_id == "power.battery" and _holds_cell(other.chosen):
                    continue
                if slot.function_id == "power.charger" and other.function_id != "power.battery":
                    continue
                filters.append(
                    Filter(
                        "chemistry",
                        "eq",
                        want,
                        "compatibility",
                        f"{want} cell ({other.label})"[:60],
                        lambda p, w=want: _chemistry_fits(p, w),
                        from_slot_id=other.slot_id,
                        relaxable=True,
                    )
                )
        # 3. logic level and I2C address room against parts on the same controller
        if slot.slot_id == "controller":
            for other in self.slots:
                part = other.chosen
                if part is None:
                    continue
                for itype in ("i2c", "spi"):
                    iface = interface_of(part, itype, "requires")
                    v = (iface or {}).get("params", {}).get("v_logic_v") if iface else None
                    if isinstance(v, int | float):
                        filters.append(
                            Filter(
                                "v_logic_v",
                                "eq",
                                float(v),
                                "propagated",
                                f"{v:g} V logic ({other.label})"[:60],
                                lambda p, v=float(v): (logic_voltage(p) or v) == v,
                                from_slot_id=other.slot_id,
                            )
                        )
            for side in sorted({i.side for i in slot.instances}):
                need, items = self.pin_need_for(side)
                self.result.pin_budget[side] = {"needed": need, "items": items}
                filters.append(
                    Filter(
                        "gpio_count",
                        "gte",
                        need,
                        "propagated",
                        f"{need} GPIO free" + (f" ({side})" if side != "none" else ""),
                        lambda p, n=need: (self.controller_gpio(p) or n) >= n,
                    )
                )
            for fid in [f["function_id"] for f in self.spec.get("functions", [])]:
                radio = fid.startswith("comms.") and "usb" not in fid
                offered = any(fid in part_functions(c) for c in cands)
                if radio and offered and not any(f.facet == "wireless" for f in filters):
                    filters.append(
                        Filter(
                            "function",
                            "has",
                            fid,
                            "requirement",
                            fid.split(".")[1].upper() + " radio",
                            lambda p, fid=fid: fid in part_functions(p),
                        )
                    )
            if self.board_controllers and self.plan is not None:
                filters.append(
                    Filter(
                        "kicad_footprint",
                        "has",
                        True,
                        "compatibility",
                        "Footprint in the KiCad board library",
                        lambda p: self.board_controller_for(p) is not None,
                        relaxable=True,
                    )
                )
        if any(interface_of(c, "i2c", "requires") for c in cands):
            used = self._used_i2c(slot)
            if used:
                filters.append(
                    Filter(
                        "i2c_address",
                        "neq",
                        sorted(used),
                        "propagated",
                        "Free I2C address",
                        lambda p, u=used: self._i2c_free(p, u),
                    )
                )
        return filters

    def _used_i2c(self, slot: Slot) -> set[int]:
        used: set[int] = set()
        for other in self.slots:
            if other.chosen is not None and other is not slot:
                used.update(i2c_addresses(other.chosen)[:1])
        return used

    @staticmethod
    def _i2c_free(part: dict[str, Any], used: set[int]) -> bool:
        iface = interface_of(part, "i2c", "requires")
        if iface is None:
            return True
        options = (iface.get("params") or {}).get("address_options") or i2c_addresses(part)
        return not options or any(a not in used for a in options)

    def score(self, slot: Slot, part: dict[str, Any], relaxed: list[Filter]) -> float:
        s = 0.3
        prov = part.get("provenance") or {}
        if prov.get("verified") not in (None, "none"):
            s += 0.1
        if (part.get("licence") or {}).get("commercial_ok") == "yes":
            s += 0.1
        if model_asset(part):
            s += 0.2
        pop = part.get("popularity") or {}
        if isinstance(pop, dict):  # SPEC part.popularity {stars, designs_using}
            s += 0.1 * min(1.0, math.log10(1 + int(pop.get("stars") or 0)) / 4)
        else:
            s += 0.1 * float(pop)
        for f in relaxed:
            if f.test(part):
                s += 0.05
        name = (str(part.get("display_name")) + " " + str(part.get("summary"))).lower()
        hint = (self.brief.get("mcu") or "").lower()
        if slot.slot_id == "controller":
            if hint and any(w in name for w in hint.split()):
                s += 0.4
            gpio = self.controller_gpio(part)
            need = max((b["needed"] for b in self.result.pin_budget.values()), default=0)
            if gpio is not None and gpio >= need:
                s += 0.15 - min(0.15, (gpio - need) * 0.01)  # smallest controller that fits
            if self.board_controller_for(part):
                s += 0.05
        # a footprint the matched open reference design used for this function
        ref = getattr(self, "reference_fps", None) or {}
        if str(part.get("footprint") or "") in ref.get(slot.function_id, ()):
            s += 0.25
        st = self.brief.get("switch_type")
        if slot.slot_id == "switches" and st and st in name:
            s += 0.2
        if slot.slot_id == "battery":
            _, hi = cp.battery_limits(self.comp)
            mah = _mah(part)
            if hi is not None and mah is not None:
                s += 0.15 * min(1.0, mah / hi)  # the biggest cell that still fits the mass
        want_in = self.comp.numbers.get("screen_in")
        if want_in and slot.function_id.startswith("display."):
            have_in = cp.display_inches(part)
            if have_in:
                s += 0.3 * max(0.0, 1 - abs(have_in - want_in) / want_in)
        return round(min(1.0, s), 3)

    # ---- one slot -----------------------------------------------------------------
    def narrow(self, slot: Slot) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list]:
        cands = self.base(slot)
        total = len(cands)
        slot.candidates_total = total
        applied: list[dict[str, Any]] = []
        relaxed: list[Filter] = []
        current = cands
        for f in self.filters_for(slot, cands):
            after = [p for p in current if f.test(p)]
            if not after and f.relaxable and current:
                relaxed.append(f)
                applied.append(self._filter_json(f, len(current), len(current), "relaxed"))
                continue
            applied.append(self._filter_json(f, len(current), len(after)))
            current = after
        slot.candidates_left = len(current)
        ranked = sorted(current, key=lambda p: -self.score(slot, p, relaxed))
        return cands, ranked, applied

    @staticmethod
    def _filter_json(f: Filter, before: int, after: int, reason: str | None = None) -> dict:
        value = f.value
        if not isinstance(value, str | int | float | bool | list) or value is None:
            value = str(value)
        return {
            "facet": f.facet,
            "op": f.op,
            "value": value,
            "reason": reason or f.reason,
            "from_slot_id": f.from_slot_id,
            "req_id": f.req_id,
            "count_before": before,
            "count_after": after,
            "label": f.label[:60],
        }

    async def pick(
        self, slot: Slot, ranked: list[dict[str, Any]]
    ) -> tuple[int | None, str, str, dict[str, Any] | None, list[str]]:
        """(index into ranked, method, reason, model info, notes)."""
        if not ranked:
            return None, "none", "", None, []
        if len(ranked) == 1:
            return 0, "only_survivor", "Only part left after the filters.", None, []
        top = ranked[:MAX_SURVIVORS]
        if not self.use_model:
            return 0, "default", "Highest score among the survivors.", None, []
        ids = [f"C{i + 1}" for i in range(len(top))]
        lines = [
            f"{sid}: {p.get('display_name')} - {str(p.get('summary') or '')[:120]}"
            for sid, p in zip(ids, top, strict=True)
        ]
        prompt = (
            f"Build request: {self.spec.get('prompt')}\n"
            f"Brief: {self.brief.get('summary')}\n"
            f"Slot: {slot.label} ({slot.function_id}), quantity {slot.quantity}.\n"
            "Every candidate below already passed the compatibility filters. "
            "Pick the best fit for the request. Answer NONE when no candidate is the part the "
            "slot names (a screw terminal is not an HDMI receptacle).\n" + "\n".join(lines)
        )
        schema = {
            "type": "object",
            "properties": {
                "choice": {"type": "string", "enum": [*ids, "NONE"]},
                "reason": {"type": "string"},
            },
            "required": ["choice", "reason"],
            "additionalProperties": False,
        }
        result, notes = await call_json(
            "You pick one hardware part from a short list for a build. Answer only with JSON.",
            prompt,
            schema,
            name="pick",
            cerebras_model=self.settings.cerebras_model,
            anthropic_model=self.settings.anthropic_model,
            timeout_s=self.settings.llm_timeout_s,
        )
        if result is None:
            return 0, "default", "No model answered; used the highest score.", None, notes
        none = result.data["choice"] == "NONE"
        idx = 0 if none else ids.index(result.data["choice"])
        model = {
            "provider": result.provider,
            "model": result.model,
            "latency_ms": result.latency_ms,
            "cached": False,
            "fallback": result.fallback,
        }
        method = "model_none" if none else "model_pick"
        return idx, method, str(result.data["reason"])[:280], model, notes

    # ---- events -------------------------------------------------------------------
    def next_decision(self) -> str:
        self.decision_n += 1
        return f"d{self.decision_n}"

    def next_warning(self, prefix: str = "w_c") -> str:
        self.warning_n += 1
        return f"{prefix}{self.warning_n}"

    def colour_for(self, slot: Slot) -> dict[str, Any] | None:
        target = {
            "keycaps": "keycaps",
            "trackball": "trackball",
            "knob": "knob",
        }.get(slot.slot_id)
        colours = self.brief.get("colours") or []
        hit = next((c for c in colours if c.get("target") == target), None)
        if hit is None and slot.slot_id == "knob":
            hit = next((c for c in colours if c.get("target") == "accent"), None)
        if hit is None and target is not None:
            hit = next((c for c in colours if c.get("target") == "all"), None)
        if hit is None:
            return None
        return {"hex": hit["hex"], "material": "plastic", "node": None}

    def initial_position(self, inst: Instance) -> list[float]:
        if self.plan is None:
            return [0.0, 0.0, 0.0]
        half = next((h for h in self.plan.halves if h.side == inst.side), self.plan.halves[0])
        w = half.width_u * PITCH_MM
        h = half.height_u * PITCH_MM
        if inst.side == "left":
            return [round(-(HALF_GAP_MM / 2 + w), 2), round(h / 2, 2), 0.0]
        if inst.side == "right":
            return [HALF_GAP_MM / 2, round(h / 2, 2), 0.0]
        return [round(-w / 2, 2), round(h / 2, 2), 0.0]

    def sized_part(self, slot: Slot, inst: Instance, part: dict[str, Any]) -> dict[str, Any]:
        """The same family as the chosen part, in the key size this instance covers."""
        if inst.key_widths is None or not inst.key_widths:
            return part
        size = max(inst.key_widths)
        if slot.function_id == "mech.stabilizer":
            size = stab_size(size)
        facets = part.get("facets") or {}
        if abs(float(facets.get("key_units") or 1.0) - size) < 1e-6 and not facets.get("homing"):
            return part
        # homing caps are for F and J only, never a whole group
        same = [
            c
            for c in self.base(slot)
            if abs(float((c.get("facets") or {}).get("key_units") or 1.0) - size) < 1e-6
            and (c.get("facets") or {}).get("switch_family") == facets.get("switch_family")
            and not (c.get("facets") or {}).get("homing")
        ]
        same.sort(key=lambda c: (c.get("facets") or {}).get("profile") != facets.get("profile"))
        return same[0] if same else part

    def build_part(self, slot: Slot, inst: Instance, part: dict[str, Any]) -> dict[str, Any]:
        placement: dict[str, Any] = {
            "mode": "layout" if inst.layout_id else "single",
            "position_mm": self.initial_position(inst) if inst.layout_id else [0.0, 0.0, 0.0],
            "rotation_deg": [0.0, 0.0, 0.0],
            "explode_offset_mm": [0.0, 0.0, 0.0],
            "source": "solver",
            "locked": False,
        }
        if inst.layout_id:
            placement["layout_id"] = inst.layout_id
        if inst.key_widths is not None:
            placement["key_widths_u"] = list(inst.key_widths)
            placement["explode_offset_mm"] = [0.0, 0.0, 25.0 if slot.slot_id == "keycaps" else 12.0]
        label = (slot.label or slot.slot_id) + (
            f" {inst.side}" if inst.side not in ("none", "") else ""
        )
        assets = [copy.deepcopy(a) for a in part.get("assets", []) if a.get("url")]
        for a in assets:  # fetched parts carry an origin the build schema does not list
            if a.get("origin") not in ("design", "generated", "catalog", "unknown"):
                a["origin"] = "catalog"
            if a.get("status") not in ("ready", "pending", "missing", "unknown"):
                a["status"] = "pending"
        _model_from_footprint(part, assets)
        card = card_for(part)
        if not str(card.get("display_name") or "").strip():
            card["display_name"] = str(part.get("mpn") or part.get("part_id") or slot.label)[:120]
        return {
            "instance_id": inst.instance_id,
            "part_id": part["part_id"],
            "slot_id": slot.slot_id,
            "label": label[:60],
            "quantity": inst.quantity,
            "side": inst.side if inst.side in ("left", "right", "center") else "none",
            "color": self.colour_for(slot),
            "placement": placement,
            "card": card,
            "assets": assets,
            "origin": "compose",
            "status": "ok",
        }

    def propagated(self, slot: Slot) -> list[dict[str, Any]]:
        out = []
        for other in self.slots:
            if other.chosen is not None or other is slot:
                continue
            base = self.base(other)
            chosen = slot.chosen or {}
            if not base or not any(_shares_typed_interface(c, chosen) for c in base):
                continue
            after = [c for c in base if _mates(c, chosen)[0]]
            if len(after) == len(base):
                continue
            label = next(
                (
                    _mates(c, slot.chosen or {})[1]
                    for c in base
                    if _shares_typed_interface(c, slot.chosen or {})
                ),
                None,
            )
            out.append(
                {
                    "slot_id": other.slot_id,
                    "count_before": len(base),
                    "count_after": len(after),
                    "constraint": (label or f"mates with the {slot.label.lower()}")[:120],
                }
            )
        return out

    def connections_for(self, slot: Slot, parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Typed connections between this slot's instances and earlier ones on the same side."""
        out: list[dict[str, Any]] = []
        by_slot = {s.slot_id: s for s in self.slots}
        part = slot.chosen or {}
        for inst in slot.instances:
            for other in self.slots:
                if other is slot or other.chosen is None or other.state != "decided":
                    continue
                for oinst in other.instances:
                    if oinst.side != inst.side and "none" not in (oinst.side, inst.side):
                        continue
                    conn = self._connect(slot, inst, part, other, oinst, other.chosen)
                    if conn is not None:
                        out.append(conn)
                    if conn is not None and oinst.side == inst.side:
                        break
        del by_slot, parts
        return out

    def _connect(
        self,
        slot: Slot,
        inst: Instance,
        part: dict[str, Any],
        other: Slot,
        oinst: Instance,
        opart: dict[str, Any],
    ) -> dict[str, Any] | None:
        for a_slot, a_inst, a, b_slot, b_inst, b in (
            (other, oinst, opart, slot, inst, part),
            (slot, inst, part, other, oinst, opart),
        ):
            for prov in a.get("interfaces", []):
                if prov.get("role") != "provides":
                    continue
                req = next(
                    (
                        r
                        for r in b.get("interfaces", [])
                        if r.get("role") == "requires" and r.get("type") == prov.get("type")
                    ),
                    None,
                )
                if req is None:
                    continue
                itype = prov["type"]
                kind = (
                    "mechanical"
                    if itype in ("switch_stem", "switch_socket", "module_footprint", "plate_cutout")
                    else "electrical"
                )
                nets = []
                for sig, pin in (prov.get("signals") or {}).items():
                    nets.append(
                        {
                            "signal": sig,
                            "from_pin": pin,
                            "to_pin": (req.get("signals") or {}).get(sig),
                        }
                    )
                cid = f"c_{_slug(a_inst.instance_id[2:])}_{_slug(b_inst.instance_id[2:])}"[:65]
                return {
                    "connection_id": cid,
                    "type": itype,
                    "kind": kind,
                    "from": {
                        "instance_id": a_inst.instance_id,
                        "interface_id": prov.get("id") or itype,
                        "index": None,
                    },
                    "to": {
                        "instance_id": b_inst.instance_id,
                        "interface_id": req.get("id") or itype,
                        "index": None,
                    },
                    "via_instance_id": None,
                    "nets": nets,
                    "resolved": {},
                    "origin": "compose",
                    "status": "ok",
                    "label": f"{b_slot.label} on {a_slot.label}"[:60],
                }
        return None

    async def run(self, emit: Emit, progress: Callable[[str, float | None], None]) -> ComposeResult:
        n_slots = len(self.slots)
        # every block's spec check at once: each is independent of the picks that follow
        ahead = [s for s in self.slots if s.need is not None and s.need.requirement]
        await asyncio.gather(*(self.vet(s, self.base(s)) for s in ahead))
        for step, slot in enumerate(self.slots, start=1):
            cover = self.covering_slot(slot)
            if cover is not None:
                self.mark_covered(slot, cover, step, emit)
                continue
            slot.state = "narrowing"
            if slot.need is not None and not self.base(slot):
                await self.resolve_missing(slot, emit)
            if slot.need is not None and slot.criticality != "optional" and not self.base(slot):
                self.take_closest(slot, emit)
            cands, ranked, applied = self.narrow(slot)
            emit("slot.updated", {"slot": slot.json()}, stage="compose")
            top = ranked[:MAX_SURVIVORS]
            survivors = [
                {
                    "short_id": f"C{i + 1}",
                    "card": card_for(p),
                    "score": self.score(slot, p, []),
                    "is_default": i == 0,
                }
                for i, p in enumerate(top)
            ]
            emit(
                "candidates.ready",
                {
                    "slot_id": slot.slot_id,
                    "step": step,
                    "filters": applied,
                    "count_before": len(cands),
                    "count_after": len(ranked),
                    "survivors": survivors,
                },
                stage="compose",
            )
            idx, method, reason, model, notes = await self.pick(slot, ranked)
            if method == "model_none" or (method == "none" and slot.need is not None):
                # nothing in the catalog is the named part, or none passes the filters: look
                # further (KiCad, LCSC) before settling for the closest catalog part
                had = len(self.extra.get(slot.slot_id, []))
                before = ranked[idx]["part_id"] if idx is not None and idx < len(ranked) else None
                await self.resolve_missing(slot, emit)
                new = self.extra.get(slot.slot_id, [])[had:]
                cands, ranked, applied = self.narrow(slot)
                hit = next(
                    (i for i, p in enumerate(ranked) for n in new if p["part_id"] == n["part_id"]),
                    None,
                )
                if hit is not None:
                    idx, reason = hit, f"No catalog part is a {slot.label.lower()}; looked further."
                else:  # the list was narrowed again: the earlier index points into the old one
                    idx = next((i for i, p in enumerate(ranked) if p["part_id"] == before), None)
                method = "model_pick"
            if notes and method != "model_pick" and self.use_model:
                emit(
                    "warning",
                    {
                        "warning": {
                            "warning_id": self.next_warning("w_llm_pick"),
                            "code": "llm_degraded",
                            "severity": "info",
                            "message": f"{slot.label}: {'; '.join(notes)}"[:300],
                            "subjects": [{"slot_id": slot.slot_id}],
                            "stage": "compose",
                        }
                    },
                    stage="compose",
                )
            if (
                idx is None
                and slot.need is not None
                and (slot.need.mechanical or slot.function_id in NON_ELECTRICAL)
            ):
                # caps, levers and wells the case geometry grows from the form's anchors; a
                # block with no electrical function (a lens, a window, a gasket) is the
                # case's own material, not something an electronics library sells
                slot.state, slot.covered_by = "none", "case"
                reason = f"{slot.label}: made by the case, not a catalog part."
            elif idx is None:
                slot.state = "none"
                if slot.need is not None:
                    slot.unresolved = self.resolver.notes.get(slot.slot_id) or (
                        "nothing in the catalog, the KiCad library or LCSC"
                    )
                    reason = f"REQUIRED {slot.label.lower()} unresolved: {slot.unresolved}"
                elif not cands and slot.function_id not in SLOT_KINDS:
                    # nothing in the catalog serves this function at all: an extra the brief
                    # asked for (feet, a strap), not part of the electrical build
                    slot.criticality = "optional"
                if slot.unresolved is None:
                    why = "; ".join(f"{f['label']} left {f['count_after']}" for f in applied)
                    reason = (
                        f"No {slot.label.lower()} in the catalog"
                        + (f" passes the filters ({why})" if applied and cands else "")
                        + "."
                    )
                emit(
                    "decision.made",
                    {
                        "decision": {
                            "decision_id": self.next_decision(),
                            "slot_id": slot.slot_id,
                            "step": step,
                            "method": "none",
                            "chosen_part_id": None,
                            "chosen_short_id": None,
                            "survivors": 0,
                            "reason": reason[:240],
                            "model": None,
                            "propagated": [],
                        }
                    },
                    stage="compose",
                )
                emit("slot.updated", {"slot": slot.json()}, stage="compose")
                self.result.log.append(f"{slot.slot_id}: no part ({reason})")
                emit(
                    "warning",
                    {
                        "warning": {
                            "warning_id": self.next_warning(),
                            "code": "optional_part_missing"
                            if slot.criticality == "optional"
                            else "other",
                            "severity": "info"
                            if slot.criticality == "optional"
                            else "error"
                            if slot.unresolved
                            else "warning",
                            "message": reason[:300],
                            "subjects": [{"slot_id": slot.slot_id}],
                            "stage": "compose",
                        }
                    },
                    stage="compose",
                )
            else:
                part = ranked[idx]
                twin = self.twin_slot(slot, part)
                if twin is not None:
                    self.mark_covered(slot, twin, step, emit)
                    continue
                slot.chosen = part
                self.result.chosen_parts[slot.slot_id] = part
                if _is_hotswap(part) and self.plan is not None:
                    slot.label = "Hot-swap socket"
                    slot.instances = _per_key(slot.instances[0].instance_id, self.plan)
                if method == "default":
                    reason = self._default_reason(slot, part, applied)
                emit(
                    "decision.made",
                    {
                        "decision": {
                            "decision_id": self.next_decision(),
                            "slot_id": slot.slot_id,
                            "step": step,
                            "method": method,
                            "chosen_part_id": part["part_id"],
                            "chosen_short_id": f"C{idx + 1}" if idx < MAX_SURVIVORS else None,
                            "survivors": len(ranked),
                            "reason": reason[:240],
                            "model": model,
                            "propagated": self.propagated(slot),
                        }
                    },
                    stage="compose",
                )
                slot.state = "decided"
                new_parts = []
                for inst in slot.instances:
                    bp = self.build_part(slot, inst, self.sized_part(slot, inst, part))
                    new_parts.append(bp)
                    emit("part.added", {"part": bp}, stage="compose")
                self.result.parts += new_parts
                emit("slot.updated", {"slot": slot.json()}, stage="compose")
                for conn in self.connections_for(slot, new_parts):
                    emit("connection.added", {"connection": conn}, stage="compose")
                self.result.log.append(f"{slot.slot_id}: {part['part_id']} ({method})")
                if self.add_segment_driver(slot, emit):
                    n_slots += 1
                lic = card_for(part)
                if lic["commercial_ok"] != "yes":
                    emit(
                        "check.result",
                        {
                            "results": [
                                {
                                    "check_key": "lic.commercial_ok:"
                                    + slot.instances[0].instance_id,
                                    "rule_id": "lic.commercial_ok",
                                    "status": "unknown",
                                    "severity": "warning",
                                    "message": (
                                        f"{lic['display_name']}: licence {lic['licence_spdx']}, "
                                        "commercial use not confirmed."
                                    )[:300],
                                    "subjects": [
                                        {
                                            "instance_id": slot.instances[0].instance_id,
                                            "part_id": part["part_id"],
                                        }
                                    ],
                                    "stage": "compose",
                                }
                            ]
                        },
                        stage="compose",
                    )
            progress(f"{step} of {n_slots} slots decided", step / max(1, n_slots))
        self.cover_generic(emit)
        return self.result

    def add_segment_driver(self, slot: Slot, emit: Emit) -> bool:
        """A bare multiplexed display (eight segment lines and a common per digit, no driver
        chip) cannot hang off a few controller pins, and no firmware framework has a platform
        for raw multiplexing. The display gets a driver slot right behind it: a TM1637 for
        common-anode glass, a MAX7219 for common-cathode, found like any other named part."""
        part = slot.chosen
        if (
            part is None
            or slot.function_id != seven_seg.FUNCTION_ID
            or not seven_seg.needs_driver(part)
            or any(o.drives == slot.slot_id for o in self.slots)
        ):
            return False
        # the device's own block diagram may already name the driver chip: that slot is it
        named = next(
            (
                o
                for o in self.slots
                if o is not slot
                and o.drives is None
                and o.function_id == "component.ic"
                and seven_seg.names_driver_chip(o.need, o.chosen)
            ),
            None,
        )
        if named is not None:
            named.drives = slot.slot_id
            return False
        chip = seven_seg.driver_for(part)
        need = Need(
            key=f"{slot.slot_id}_driver"[:40],
            function_id="component.ic",
            label=chip.label,
            count=max(1, slot.quantity),
            names=chip.names,
            terms=chip.terms,
            pin_kind=chip.pin_kind,
            prefix="segdrv",
            why=f"{part.get('display_name')} has no driver of its own",
        )
        taken = {i.instance_id for o in self.slots for i in o.instances}
        inst_id = "u_segdrv"
        while inst_id in taken:
            inst_id += "2"
        driver = Slot(
            slot_id=need.key,
            label=chip.label,
            function_id=need.function_id,
            criticality="critical",
            order=0,
            instances=[Instance(inst_id, "none", need.count)],
            need=need,
            drives=slot.slot_id,
        )
        self.slots.insert(self.slots.index(slot) + 1, driver)
        for i, o in enumerate(self.slots):
            o.order = i
        emit("slot.updated", {"slot": driver.json()}, stage="compose")
        self.result.log.append(f"{driver.slot_id}: added, {part['part_id']} has no driver")
        return True

    def cover_generic(self, emit: Emit) -> None:
        """A generic slot the brief implied (a display) that found nothing is the same block as a
        named slot of that function decided after it (the 1.3 in segment display the device
        concept asked for): one part, not a missing one."""
        for slot in self.slots:
            if slot.need is not None or slot.chosen is not None or slot.covered_by:
                continue
            if slot.criticality == "optional":
                continue
            other = next(
                (
                    o
                    for o in self.slots
                    if o is not slot
                    and o.chosen is not None
                    and not o.covered_by
                    and (
                        o.function_id == slot.function_id
                        or slot.function_id in part_functions(o.chosen)
                        or (is_screen_fn(slot.function_id) and is_screen_fn(o.function_id))
                    )
                ),
                None,
            )
            if other is not None:
                self.mark_covered(slot, other, self.slots.index(slot) + 1, emit)

    async def vet(self, slot: Slot, parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Parts that meet the block's key numbers (size, connector standard, rating). The ones
        that do not are rejected for good, so the next lookup moves on."""
        if slot.function_id == seven_seg.FUNCTION_ID:
            # digits, colour and polarity are read from words; nothing here is glass to size
            want = (
                seven_seg.want_from(f"{slot.need.label} {slot.need.requirement}")
                if slot.need
                else None
            )
            if want is not None:
                for p in parts:
                    if not seven_seg.meets_digits(p, want):
                        self.resolver.rejected.add(p["part_id"])
                return [p for p in parts if seven_seg.meets_digits(p, want)]
            return parts
        if slot.function_id.startswith("display.") and slot.function_id != "display.indicator_led":
            # the typed size, else the size the brief wrote into this block's requirement
            need_text = f"{slot.need.label} {slot.need.requirement}" if slot.need else ""
            want_in = self.comp.numbers.get("screen_in") or cp.parse_numbers(need_text).get(
                "screen_in"
            )
            chips = [p for p in parts if is_chip(p) or not_a_panel(p) or wrong_size(p, want_in)]
            for p in chips:  # a driver chip, ribbon connector or other-size glass is not it
                self.resolver.rejected.add(p["part_id"])
                if not (is_chip(p) or not_a_panel(p)):  # real glass of another size: close
                    self.near_miss.setdefault(slot.slot_id, []).append(p)
            parts = [p for p in parts if p not in chips]
        need = slot.need
        if need is None or not need.requirement or not parts:
            return parts
        typed = typed_mpns(str(self.spec.get("prompt") or ""))
        if any(names_typed_mpn(p, typed) for p in parts):
            # the part number the person typed is the part they asked for, whatever function
            # the block was filed under
            return [p for p in parts if names_typed_mpn(p, typed)]
        shown = parts[:12]
        lines = "\n".join(
            f"{i}: {p.get('display_name')} [{p.get('part_id')}] "
            f"{str(p.get('description') or p.get('summary') or '')[:140]}"
            for i, p in enumerate(shown)
        )
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["meets"],
            "properties": {"meets": {"type": "array", "items": {"type": "integer"}}},
        }
        data, note = await ask_json(
            "You check parts against a requirement. Return the indexes of the candidates that "
            "clearly meet every number in the requirement (size, resolution, connector "
            "standard, rating). A part whose name shows a different size, standard or rating "
            "does not meet it. When a candidate gives no evidence either way, include it.",
            f"Product block: {need.label}\nRequirement: {need.requirement}\nCandidates:\n{lines}",
            schema,
            name="spec_check",
            fast=True,
            timeout_s=40,
        )
        if data is None:
            return parts
        keep = {i for i in data["meets"] if 0 <= i < len(shown)}
        for i, p in enumerate(shown):
            if i not in keep:
                self.resolver.rejected.add(p["part_id"])
                self.near_miss.setdefault(slot.slot_id, []).append(p)
        out = [p for i, p in enumerate(shown) if i in keep] + parts[12:]
        if not out:
            self.resolver.notes[slot.slot_id] = (
                f"no candidate meets '{need.requirement}' (rejected: "
                + ", ".join(str(p.get("display_name"))[:30] for p in shown[:4])
                + ")"
            )
        return out

    def take_closest(self, slot: Slot, emit: Emit) -> None:
        """A required block nothing meets takes the first part its spec check turned down: a
        real part that falls short of one number beats a device missing the function."""
        near = self.near_miss.get(slot.slot_id, [])
        if not near or slot.need is None:
            return
        part = near[0]
        typed = typed_mpns(str(self.spec.get("prompt") or ""))
        label = re.sub(r"[^a-z0-9]", "", slot.need.label.lower())
        if any(t in label for t in typed) and not names_typed_mpn(part, typed):
            return  # a part the person named by number: another chip is a different device
        if slot.function_id.startswith("display."):
            want_in = self.comp.numbers.get("screen_in") or cp.parse_numbers(
                f"{slot.need.label} {slot.need.requirement}"
            ).get("screen_in")
            part = closest_size(near, want_in)
        self.resolver.rejected.discard(part["part_id"])
        self.extra.setdefault(slot.slot_id, []).append(part)
        emit(
            "warning",
            {
                "warning": {
                    "warning_id": self.next_warning(),
                    "code": "other",
                    "severity": "warning",
                    "message": (
                        f"{slot.label}: no part found meets '{slot.need.requirement}'; "
                        f"{part.get('display_name')} is the closest and falls short of it."
                    )[:300],
                    "subjects": [{"slot_id": slot.slot_id}],
                    "stage": "compose",
                }
            },
            stage="compose",
        )

    RELAX_ROUNDS = 2

    async def relax(self, slot: Slot) -> bool:
        """The names tried found nothing usable: ask for other real parts and library families that
        serve the same function and requirement, and widen the need with them."""
        need = slot.need
        if need is None:
            return False
        tried = list(need.terms) + list(need.kicad)
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["search_terms", "kicad_names"],
            "properties": {
                "search_terms": {"type": "array", "items": {"type": "string"}},
                "kicad_names": {"type": "array", "items": {"type": "string"}},
            },
        }
        why = self.resolver.notes.get(slot.slot_id, "")
        data, _ = await ask_json(
            "You find substitute parts. Earlier lookups for a product block found nothing "
            "usable. Give up to four other real manufacturer part numbers sold on LCSC that do "
            "the same job (same function, meeting the requirement; alternative driver ICs, "
            "pin-compatible modules, a different vendor, or, for a module-scale function such "
            "as a panel scaler, PSU or driver, a ready-made module or driver board that does "
            "the whole job and mounts off the main board) and up to four KiCad library symbol or "
            "footprint names or family words that fit (for example the connector family or the "
            "IC's generic name). Never repeat a name already tried. Never invent a part number.",
            f"Block: {need.label}\nFunction: {need.function_id}\n"
            f"Requirement: {need.requirement or 'none'}\nAlready tried: {', '.join(tried)}\n"
            f"Why they failed: {why or 'no match'}",
            schema,
            name="relax_names",
            fast=True,
            timeout_s=45,
        )
        if data is None:
            return False
        terms = [t for t in data["search_terms"] if t and t not in need.terms][:4]
        kicad = [t for t in data["kicad_names"] if t and t not in need.kicad][:4]
        if not terms and not kicad:
            return False
        slot.need = replace(need, terms=need.terms + tuple(terms), kicad=need.kicad + tuple(kicad))
        self.resolver.notes.pop(slot.slot_id, None)
        return True

    async def _find(self, slot: Slot) -> tuple[dict[str, Any] | None, str]:
        need = slot.need
        assert need is not None
        for _ in range(3):  # a part that fails the spec check is rejected and the next tried
            part = self.resolver.generated(need)
            via = "the KiCad library"
            if part is None:
                part = await asyncio.to_thread(self.resolver.fetch, need)
                via = "LCSC"
                if part is not None:
                    self.fetched.append(part)
            if part is None:
                return None, via
            if await self.vet(slot, [part]):
                return part, via
        return None, "the KiCad library"

    async def resolve_missing(self, slot: Slot, emit: Emit) -> None:
        """A required need with no curated part: KiCad generated tier, then an LCSC fetch, then
        the same with relaxed names (other drivers, library families) before it fails."""
        if slot.need is None:
            return
        part, via = None, ""
        if stock_primitive(slot.need):
            # a plain LED, button or fuse: the KiCad library part, not an LCSC download
            part = self.resolver.composed(slot.need)
            if part is not None and not await self.vet(slot, [part]):
                part = None
            via = f"a composed {part['composed']} (KiCad library)" if part else ""
        if part is None:
            part, via = await self._find(slot)
        for _ in range(self.RELAX_ROUNDS):
            if part is not None or not await self.relax(slot):
                break
            part, via = await self._find(slot)
        if part is None:
            part = self.resolver.composed(slot.need)
            if part is not None and not await self.vet(slot, [part]):
                part = None
            via = f"a composed {part['composed']} (KiCad library)" if part else ""
        typed = typed_mpns(str(self.spec.get("prompt") or ""))
        label = re.sub(r"[^a-z0-9]", "", slot.need.label.lower())
        if part is None and any(t in label for t in typed):
            # the block is a part the person named: another part filed under the same
            # function (a trackball for an optical sensor) would be a different device
            return
        if part is None:
            # nothing by name: a catalog part serving the function, spec-checked (a near miss
            # is still taken later) beats a device missing it
            pool = [
                p
                for p in self.source.query(function=slot.function_id, limit=500)
                if p["part_id"] not in self.resolver.rejected
            ]
            part = None
            for i in range(0, min(len(pool), 48), 12):  # only parts the spec check saw
                batch = pool[i : i + 12]
                kept = [p for p in await self.vet(slot, batch) if p in batch]
                if kept:
                    part = kept[0]
                    break
            if part is None:
                return
            via = "the catalog, by function"
        self.extra.setdefault(slot.slot_id, []).append(part)
        emit(
            "warning",
            {
                "warning": {
                    "warning_id": self.next_warning("w_fetch"),
                    "code": "other",
                    "severity": "info",
                    "message": (
                        f"{slot.label}: no curated part, used {part.get('display_name')} from "
                        f"{via}."
                    )[:300],
                    "subjects": [{"slot_id": slot.slot_id}],
                    "stage": "compose",
                }
            },
            stage="compose",
        )

    def _default_reason(self, slot: Slot, part: dict[str, Any], applied: list[dict]) -> str:
        bits = [f["label"] for f in applied if f["reason"] != "relaxed"][:3]
        name = part.get("display_name") or part["part_id"]
        if slot.slot_id == "controller" and self.result.pin_budget:
            need = max(b["needed"] for b in self.result.pin_budget.values())
            have = self.controller_gpio(part)
            return (
                f"{name}: smallest controller that fits {need} GPIO"
                + (f" ({have} free)" if have else "")
                + (", " + ", ".join(bits) if bits else "")
                + "."
            )
        return f"{name}: highest score" + (" after " + ", ".join(bits) if bits else "") + "."

    def resize(
        self, instance_id: str, fits: Callable[[dict[str, Any]], bool], why: str, emit: Emit
    ) -> dict[str, Any] | None:
        """Re-pick the slot that owns instance_id with its best-ranked candidate that fits (a
        part too big for the product swapped for a smaller one serving the same function);
        returns the new part, None when no other candidate fits."""
        slot = next(
            (s for s in self.slots if any(i.instance_id == instance_id for i in s.instances)),
            None,
        )
        if slot is None or slot.chosen is None:
            return None
        old = slot.chosen
        _, ranked, _ = self.narrow(slot)
        part = next((p for p in ranked if p["part_id"] != old["part_id"] and fits(p)), None)
        if part is None:
            return None
        slot.chosen = part
        self.result.chosen_parts[slot.slot_id] = part
        reason = f"{card_for(old)['display_name']} does not fit: {why}"
        emit(
            "decision.made",
            {
                "decision": {
                    "decision_id": self.next_decision(),
                    "slot_id": slot.slot_id,
                    "step": slot.order,
                    "method": "solver",
                    "chosen_part_id": part["part_id"],
                    "chosen_short_id": None,
                    "survivors": len(ranked),
                    "reason": reason[:240],
                    "model": None,
                    "propagated": self.propagated(slot),
                }
            },
            stage="compose",
        )
        built = {
            inst.instance_id: self.build_part(slot, inst, self.sized_part(slot, inst, part))
            for inst in slot.instances
        }
        self.result.parts = [built.get(p["instance_id"], p) for p in self.result.parts]
        for bp in built.values():
            emit("part.updated", {"part": bp}, stage="compose")
        emit("slot.updated", {"slot": slot.json()}, stage="compose")
        for conn in self.connections_for(slot, list(built.values())):
            emit("connection.added", {"connection": conn}, stage="compose")
        self.result.log.append(f"{slot.slot_id}: {part['part_id']} (resized: {why})")
        return part

    def covering_slot(self, slot: Slot) -> Slot | None:
        """An already decided slot whose part also provides this slot's function.

        A BME280 measures temperature and humidity: one part, not two of them.
        """
        if slot.need is not None and slot.slot_id != "charger":
            return None
        sides = {i.side for i in slot.instances}
        for other in self.slots:
            if other is slot or other.chosen is None or other.covered_by:
                continue
            if other.need is not None and other.function_id == "component.ic":
                continue
            if slot.function_id not in part_functions(other.chosen):
                continue
            if sides <= ({i.side for i in other.instances} | {"none"}):
                return other
        return None

    def twin_slot(self, slot: Slot, part: dict[str, Any]) -> Slot | None:
        """A decided catch-all slot that already holds this very part.

        A block with no function in the taxonomy is found by its names alone; when two such
        blocks land on one part (an optical sensor, and its lens "matched to" that sensor),
        the second named the first's part, so it is one part, not two."""
        if slot.function_id != "other":
            return None
        for other in self.slots:
            if other is slot or other.chosen is None or other.covered_by:
                continue
            if other.function_id == "other" and other.chosen["part_id"] == part["part_id"]:
                return other
        return None

    def mark_covered(self, slot: Slot, cover: Slot, step: int, emit: Emit) -> None:
        part = cover.chosen or {}
        slot.state, slot.covered_by = "none", cover.slot_id
        emit("slot.updated", {"slot": slot.json()}, stage="compose")
        reason = (
            f"{part.get('display_name')} (chosen for {cover.label.lower()}) also provides "
            f"{slot.label.lower()}, so no second part."
        )
        emit(
            "decision.made",
            {
                "decision": {
                    "decision_id": self.next_decision(),
                    "slot_id": slot.slot_id,
                    "step": step,
                    "method": "none",
                    "chosen_part_id": None,
                    "chosen_short_id": None,
                    "survivors": 0,
                    "reason": reason[:240],
                    "model": None,
                    "propagated": [],
                }
            },
            stage="compose",
        )

    # ---- checks ---------------------------------------------------------------------
    def invariant_checks(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        ok_slot = lambda s: s.chosen is not None or s.covered_by is not None  # noqa: E731
        ctrl_ids = ("controller", *self.comp.controller_keys)
        ctrl = [s for s in self.slots if s.slot_id in ctrl_ids]
        power_ids = ("battery", "ac_dc", "power_in")
        power = [s for s in self.slots if s.slot_id in power_ids]
        usb = any(f["function_id"] == "power.usb_in" for f in self.spec.get("functions", []))
        problems = []
        if not ctrl or not all(ok_slot(s) for s in ctrl):
            problems.append("no controller")
        if not (all(ok_slot(s) for s in power) if power else usb):
            problems.append("no power path")
        problems += [s.label.lower() for s in self.slots if s.need is not None and not ok_slot(s)]
        out.append(
            {
                "check_key": "device.complete",
                "rule_id": "device.complete",
                "status": "fail" if problems else "pass",
                "severity": "critical",
                "message": (
                    "Required parts missing: " + ", ".join(problems)
                    if problems
                    else "Controller, power path and the I/O this device implies are all present"
                )[:300],
                "subjects": [{"slot_id": s.slot_id} for s in self.slots if s.unresolved][:8],
                "stage": "compose",
            }
        )
        n = self.comp.numbers
        chosen = [(s.chosen, max(1, s.quantity)) for s in self.slots if s.chosen is not None]
        if "mass_g" in n and chosen:
            est = cp.estimate_mass(self.comp, chosen)
            out.append(
                {
                    "check_key": "spec.mass_target",
                    "rule_id": "spec.mass_target",
                    "status": "pass" if est["total_g"] <= n["mass_g"] else "fail",
                    "severity": "warning",
                    "message": (
                        f"ESTIMATED mass {est['total_g']:g} g (parts {est['electronics_g']:g}, "
                        f"board {est['pcb_g']:g}, case {est['shell_g']:g}; most part masses are "
                        f"category guesses) against the {n['mass_g']:g} g target"
                    )[:300],
                    "measured": est["total_g"],
                    "limit": n["mass_g"],
                    "unit": "g",
                    "subjects": [],
                    "stage": "compose",
                }
            )
        disp = next((s for s in self.slots if s.function_id.startswith("display.")), None)
        if "screen_in" in n and disp is not None and disp.chosen is not None:
            have = cp.display_inches(disp.chosen)
            want = n["screen_in"]
            close = have is not None and abs(have - want) <= 0.25 * want
            out.append(
                {
                    "check_key": "spec.screen_size",
                    "rule_id": "spec.screen_size",
                    "status": "pass" if close else ("unknown" if have is None else "fail"),
                    "severity": "warning",
                    "message": (
                        f"Asked for a {want:g} in screen; the catalog panel is "
                        + (f"{have:g} in" if have else "of unknown size")
                    )[:300],
                    "measured": have,
                    "limit": want,
                    "unit": "in",
                    "subjects": [{"slot_id": disp.slot_id}],
                    "stage": "compose",
                }
            )
        if self.comp.mains:
            out.append(
                {
                    "check_key": "safety.mains_wiring",
                    "rule_id": "safety.mains_wiring",
                    "status": "unknown",
                    "severity": "critical",
                    "message": (
                        "MAINS WIRING NOT VERIFIED: only a certified, enclosed AC-DC module may "
                        "touch mains; this board carries low voltage only. The enclosure must be "
                        "rated and not user-serviceable. Mains sockets, fusing and creepage are "
                        "the module's and a certified enclosure's job."
                    ),
                    "subjects": [{"slot_id": "ac_dc"}],
                    "stage": "compose",
                }
            )
        return out

    def checks(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        out.extend(c for slot in self.slots if (c := slot_check(slot)) is not None)
        ctrl = next((s for s in self.slots if s.slot_id == "controller"), None)
        if ctrl is not None and ctrl.chosen is not None:
            have = self.controller_gpio(ctrl.chosen)
            for side, budget in self.result.pin_budget.items():
                need = budget["needed"]
                inst = next((i for i in ctrl.instances if i.side == side), ctrl.instances[0])
                status = "unknown" if have is None else ("pass" if have >= need else "fail")
                out.append(
                    {
                        "check_key": f"elec.gpio.pins_available:{inst.instance_id}",
                        "rule_id": "elec.gpio.pins_available",
                        "status": status,
                        "severity": "error",
                        "message": (
                            f"{need} GPIO needed ({', '.join(budget['items'])}); "
                            + (f"{have} free" if have is not None else "free count unknown")
                        )[:300],
                        "subjects": [{"instance_id": inst.instance_id}],
                        "measured": need,
                        "limit": have,
                        "unit": "pins",
                        "stage": "compose",
                    }
                )
            v_mcu = logic_voltage(ctrl.chosen)
            for slot in self.slots:
                if slot.chosen is None or slot is ctrl:
                    continue
                for itype in ("i2c", "spi"):
                    iface = interface_of(slot.chosen, itype, "requires")
                    if iface is None:
                        continue
                    v = (iface.get("params") or {}).get("v_logic_v")
                    inst = slot.instances[0]
                    status = (
                        "unknown"
                        if v is None or v_mcu is None
                        else ("pass" if abs(float(v) - v_mcu) < 0.05 else "fail")
                    )
                    out.append(
                        {
                            "check_key": f"elec.logic.level_mismatch:{inst.instance_id}",
                            "rule_id": "elec.logic.level_mismatch",
                            "status": status,
                            "severity": "error",
                            "message": f"{slot.label} {v} V logic, controller {v_mcu} V"[:300],
                            "subjects": [{"instance_id": inst.instance_id}],
                            "measured": v,
                            "limit": v_mcu,
                            "unit": "V",
                            "stage": "compose",
                        }
                    )
            addrs: dict[int, list[str]] = {}
            for slot in self.slots:
                if slot.chosen is not None:
                    for a in i2c_addresses(slot.chosen)[:1]:
                        addrs.setdefault(a, []).append(slot.label)
            if addrs:
                clash = {a: n for a, n in addrs.items() if len(n) > 1}
                out.append(
                    {
                        "check_key": f"elec.i2c.address_clash:{ctrl.instances[0].instance_id}",
                        "rule_id": "elec.i2c.address_clash",
                        "status": "fail" if clash else "pass",
                        "severity": "error",
                        "message": (
                            "I2C addresses "
                            + ", ".join(
                                f"0x{a:02X} {'/'.join(n)}" for a, n in sorted(addrs.items())
                            )
                        )[:300],
                        "subjects": [{"instance_id": ctrl.instances[0].instance_id}],
                        "stage": "compose",
                    }
                )
            bat = next((s for s in self.slots if s.slot_id == "battery"), None)
            if bat is not None:
                charger = "power.charger" in part_functions(ctrl.chosen) or any(
                    s.slot_id == "charger" and s.chosen is not None for s in self.slots
                )
                out.append(
                    {
                        "check_key": "elec.battery.charger_present:"
                        + ctrl.instances[0].instance_id,
                        "rule_id": "elec.battery.charger_present",
                        "status": "pass" if charger else "unknown",
                        "severity": "error",
                        "message": (
                            f"{ctrl.chosen.get('display_name')} has an on-board LiPo charger"
                            if charger
                            else "No charger listed on the controller; check its datasheet."
                        )[:300],
                        "subjects": [{"instance_id": ctrl.instances[0].instance_id}],
                        "stage": "compose",
                    }
                )
        out += self.invariant_checks()
        sw = next((s for s in self.slots if s.slot_id == "switches"), None)
        caps = next((s for s in self.slots if s.slot_id == "keycaps"), None)
        if sw is not None and sw.chosen is not None:
            fam = (sw.chosen.get("facets") or {}).get("switch_family")
            want = self.brief.get("switch_family")
            out.append(
                {
                    "check_key": f"mech.switch.family_match:{sw.instances[0].instance_id}",
                    "rule_id": "mech.switch.family_match",
                    "status": "pass" if fam == want else ("unknown" if fam is None else "fail"),
                    "severity": "error",
                    "message": f"Switches {fam}, board footprints {want}"[:300],
                    "subjects": [{"instance_id": sw.instances[0].instance_id}],
                    "stage": "compose",
                }
            )
            if caps is not None and caps.chosen is not None:
                ok, label = _mates(caps.chosen, sw.chosen)
                out.append(
                    {
                        "check_key": f"mech.keycap.stem_match:{caps.instances[0].instance_id}",
                        "rule_id": "mech.keycap.stem_match",
                        "status": "pass" if ok else "fail",
                        "severity": "error",
                        "message": (
                            "Keycap stem "
                            + ("matches " if ok else "does not match ")
                            + (label or "the switch stem")
                        )[:300],
                        "subjects": [{"instance_id": caps.instances[0].instance_id}],
                        "stage": "compose",
                    }
                )
        return out
