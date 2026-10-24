"""Compose stage: slots from the spec, faceted filtering, constraint propagation, picks.

Each slot is narrowed by filters (requirement, compatibility with parts already chosen,
logic level, GPIO budget, I2C address room, KiCad footprint availability). The model
only ever picks among the survivors, by enum id C1..C8. With no key set, or a single
survivor, the deterministic default (highest score) is used and the decision says so.
"""

from __future__ import annotations

import copy
import logging
import math
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

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
from bara.live.layout import PITCH_MM, KeyboardPlan, feature_sides, pin_need
from bara.live.llm_json import call_json

log = logging.getLogger(__name__)

Emit = Callable[..., dict[str, Any]]

MAX_SURVIVORS = 8
HALF_GAP_MM = 40.0  # inner-edge gap between split halves in the first placement guess

# function id -> (slot id, label, instance prefix, feature kind for side assignment)
SLOT_KINDS: dict[str, tuple[str, str, str, str | None]] = {
    "input.key": ("switches", "Switches", "sw", None),
    "mech.keycap": ("keycaps", "Keycaps", "cap", None),
    "input.rotary_encoder": ("encoder", "Rotary encoder", "enc", "knob"),
    "mech.knob": ("knob", "Knob", "knob", "knob"),
    "input.trackball": ("trackball", "Trackball", "tb", "trackball"),
    "compute.mcu": ("controller", "Controller", "mcu", None),
    "power.battery": ("battery", "Battery", "bat", None),
    "interconnect.jack": ("jack", "TRRS jack", "jack", None),
    "interconnect.cable": ("cable", "Split cable", "cable", None),
}
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
}
PERIPHERAL_KIND = {
    "encoder": "knob",
    "trackball": "trackball",
}
COMPAT_PARAMS = ("family", "stem", "form_factor", "chemistry")


@dataclass
class Instance:
    instance_id: str
    side: str
    quantity: int
    layout_id: str | None = None


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


def _side_suffix(side: str) -> str:
    return {"left": "_l", "right": "_r", "center": "_c"}.get(side, "")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", text.lower()).strip("_")[:40] or "x"


def derive_slots(
    spec: dict[str, Any], brief: dict[str, Any], plan: KeyboardPlan | None
) -> list[Slot]:
    split = brief.get("layout_style") == "split"
    halves = ["left", "right"] if split else ["none"]
    functions = [f["function_id"] for f in spec.get("functions", [])]
    required = {f["function_id"]: f.get("required", True) for f in spec.get("functions", [])}
    if split and brief.get("wireless") == "none":
        functions += ["interconnect.jack", "interconnect.cable"]
        required["interconnect.jack"] = required["interconnect.cable"] = True
    slots: list[Slot] = []
    seen: set[str] = set()
    for fid in functions:
        if fid in NO_SLOT or fid.startswith(NO_SLOT_PREFIX) or fid in seen:
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
        if fid in ("input.key", "mech.keycap") and plan is not None:
            for half in plan.halves:
                lay = (
                    f"lay_{'l' if half.side == 'left' else 'r' if half.side == 'right' else 'main'}"
                )
                instances.append(
                    Instance(
                        f"u_{prefix}{_side_suffix(half.side)}",
                        half.side,
                        len(half.keys),
                        layout_id=lay,
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
                suffix = _side_suffix(s) + (f"_{counter[s]}" if per[s] > 1 else "")
                instances.append(Instance(f"u_{prefix}{suffix}", s, 1))
        elif fid == "mech.wheel":
            instances = [Instance(f"u_{prefix}_{i}", "none", 1) for i in (1, 2)]
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
    rank = {"switches": 0, "keycaps": 1, "controller": 80, "battery": 81, "jack": 82, "cable": 83}
    slots.sort(key=lambda s: rank.get(s.slot_id, 10))
    for i, slot in enumerate(slots):
        slot.order = i
    return slots


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


class Composer:
    def __init__(
        self,
        source: PartSource,
        spec: dict[str, Any],
        brief: dict[str, Any],
        plan: KeyboardPlan | None,
        settings: Any,
        board_controllers: dict[str, int] | None = None,
    ) -> None:
        self.source = source
        self.spec = spec
        self.brief = brief
        self.plan = plan
        self.settings = settings
        # registry controller id -> GPIO count the KiCad board library offers
        self.board_controllers = board_controllers or {}
        self.slots = derive_slots(spec, brief, plan)
        self.result = ComposeResult(slots=self.slots)
        self.decision_n = 0
        self.warning_n = 0
        self.use_model = bool(
            os.environ.get("CEREBRAS_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
        )

    # ---- candidates ---------------------------------------------------------------
    def base(self, slot: Slot) -> list[dict[str, Any]]:
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
        return gpio_count(part)

    def pin_need_for(self, side: str) -> tuple[int, list[str]]:
        half = None
        if self.plan is not None:
            half = next(
                (h for h in self.plan.halves if h.side == side or side == "none"),
                self.plan.halves[0],
            )
        peripherals = []
        for slot in self.slots:
            if slot.slot_id in ("switches", "keycaps", "controller", "battery", "cable", "knob"):
                continue
            for inst in slot.instances:
                if inst.side != side and side != "none":
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
                peripherals.append({"kind": kind, "label": slot.label, "part": slot.chosen or {}})
        wired = self.brief.get("layout_style") == "split" and self.brief.get("wireless") == "none"
        return pin_need(half, peripherals, wired)

    def filters_for(self, slot: Slot, cands: list[dict[str, Any]]) -> list[Filter]:
        filters: list[Filter] = []
        present = {k for p in cands for k in (p.get("facets") or {})}
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
            op_ = "eq" if op in ("has", "in") else op
            filters.append(
                Filter(
                    facet,
                    op,
                    value,
                    "requirement",
                    req.get("label") or f"{facet} {value}",
                    lambda p, f=facet, o=op_, v=value: facet_match(p, f, o, v),
                    req_id=req["req_id"],
                    relaxable=soft,
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
        st = self.brief.get("switch_type")
        if slot.slot_id == "switches" and st and st in name:
            s += 0.2
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
            "Pick the best fit for the request.\n" + "\n".join(lines)
        )
        schema = {
            "type": "object",
            "properties": {
                "choice": {"type": "string", "enum": ids},
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
        idx = ids.index(result.data["choice"])
        model = {
            "provider": result.provider,
            "model": result.model,
            "latency_ms": result.latency_ms,
            "cached": False,
            "fallback": result.fallback,
        }
        return idx, "model_pick", str(result.data["reason"])[:280], model, notes

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
            placement["explode_offset_mm"] = [0.0, 0.0, 25.0 if slot.slot_id == "keycaps" else 12.0]
        label = slot.label + (f" {inst.side}" if inst.side not in ("none", "") else "")
        assets = [copy.deepcopy(a) for a in part.get("assets", []) if a.get("url")]
        return {
            "instance_id": inst.instance_id,
            "part_id": part["part_id"],
            "slot_id": slot.slot_id,
            "label": label[:60],
            "quantity": inst.quantity,
            "side": inst.side if inst.side in ("left", "right", "center") else "none",
            "color": self.colour_for(slot),
            "placement": placement,
            "card": card_for(part),
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
        for step, slot in enumerate(self.slots, start=1):
            cover = self.covering_slot(slot)
            if cover is not None:
                self.mark_covered(slot, cover, step, emit)
                continue
            slot.state = "narrowing"
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
            if idx is None:
                slot.state = "none"
                if not cands and slot.function_id not in SLOT_KINDS:
                    # nothing in the catalog serves this function at all: an extra the brief
                    # asked for (feet, a strap), not part of the electrical build
                    slot.criticality = "optional"
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
                            "severity": "info" if slot.criticality == "optional" else "warning",
                            "message": reason[:300],
                            "subjects": [{"slot_id": slot.slot_id}],
                            "stage": "compose",
                        }
                    },
                    stage="compose",
                )
            else:
                part = ranked[idx]
                slot.chosen = part
                self.result.chosen_parts[slot.slot_id] = part
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
                    bp = self.build_part(slot, inst, part)
                    new_parts.append(bp)
                    emit("part.added", {"part": bp}, stage="compose")
                self.result.parts += new_parts
                emit("slot.updated", {"slot": slot.json()}, stage="compose")
                for conn in self.connections_for(slot, new_parts):
                    emit("connection.added", {"connection": conn}, stage="compose")
                self.result.log.append(f"{slot.slot_id}: {part['part_id']} ({method})")
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
        return self.result

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

    def covering_slot(self, slot: Slot) -> Slot | None:
        """An already decided slot whose part also provides this slot's function.

        A BME280 measures temperature and humidity: one part, not two of them.
        """
        sides = {i.side for i in slot.instances}
        for other in self.slots:
            if other is slot or other.chosen is None or other.covered_by:
                continue
            if slot.function_id not in part_functions(other.chosen):
                continue
            if sides <= ({i.side for i in other.instances} | {"none"}):
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
    def checks(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for slot in self.slots:
            ok = slot.chosen is not None or slot.covered_by is not None
            if slot.criticality == "critical" or not ok:
                rule = (
                    "slot.critical_filled"
                    if slot.criticality == "critical"
                    else "slot.optional_missing"
                )
                out.append(
                    {
                        "check_key": f"{rule}:{slot.slot_id}",
                        "rule_id": rule,
                        "status": "pass" if ok else "fail",
                        "severity": "critical" if slot.criticality == "critical" else "info",
                        "message": (
                            f"{slot.label}: {slot.chosen.get('display_name')}"
                            if ok and slot.chosen
                            else f"{slot.label}: covered by the {slot.covered_by} part"
                            if ok
                            else f"{slot.label}: no catalog part passes the filters"
                        )[:300],
                        "subjects": [{"slot_id": slot.slot_id}],
                        "stage": "compose",
                    }
                )
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
                charger = "power.charger" in part_functions(ctrl.chosen)
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
