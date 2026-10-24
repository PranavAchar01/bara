"""Completeness invariant: what every device must have, whatever the prompt left unsaid.

A device has a controller (MCU, SBC or a dedicated controller IC), a power path (battery plus
charger, or a mains/USB input) and the I/O its function implies. The prompt and the brief only
say what the person typed; this module adds the rest as *required* needs, each with the search
terms used to find a part (curated catalog, KiCad generated tier, then an LCSC fetch).

Needs are recorded on the spec as functions with ``source == "assumed"`` so nothing here is a
silent default: compose reports each one as a slot, and an unresolved one is a failing check.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

Number = float


@dataclass(frozen=True)
class Need:
    key: str  # slot id
    function_id: str  # a SPEC vocab function id
    label: str
    count: int = 1
    by_function: bool = False  # curated candidates = every catalog part with function_id
    names: tuple[str, ...] = ()  # words that identify a curated part by name
    terms: tuple[str, ...] = ()  # MPNs to search on LCSC, best first
    kicad: tuple[str, ...] = ()  # generated KiCad tier symbol names
    pin_kind: str | None = None  # how many controller pins it costs (layout.pin_need kinds)
    pin_mult: int = 1
    prefix: str = ""
    touch: bool = False  # a person touches, sees or plugs into it (the form stage anchors it)
    groups: tuple[str, ...] = ()  # the merged blocks, "label xN", so the form can place each
    requirement: str = ""  # key numbers the part must meet (size, connector standard, rating)

    @property
    def inst_prefix(self) -> str:
        return self.prefix or re.sub(r"[^a-z0-9]", "", self.key)[:10]


@dataclass
class Completeness:
    needs: dict[str, Need] = field(default_factory=dict)  # slot id -> need
    notes: list[str] = field(default_factory=list)  # what was added or substituted, and why
    numbers: dict[str, Number] = field(default_factory=dict)  # mass_g, screen_in, hours, mah
    kind: str | None = None
    mains: bool = False
    controller_keys: tuple[str, ...] = ()  # needs that are the device's controller


# ---- numbers in the prompt -------------------------------------------------------------
_NUM = r"(\d+(?:\.\d+)?)"


def parse_numbers(text: str) -> dict[str, Number]:
    """Spec numbers the person typed: mass_g, screen_in, hours (battery life), mah."""
    t = text.lower()
    out: dict[str, Number] = {}
    m = re.search(_NUM + r"\s*-?\s*(kg|kilograms?)\b", t)
    if m:
        out["mass_g"] = float(m.group(1)) * 1000
    else:
        m = re.search(_NUM + r"\s*-?\s*(g|grams?|gram)\b", t)
        if m:
            out["mass_g"] = float(m.group(1))
    m = re.search(_NUM + r"\s*-?\s*(inch(?:es)?|in|\")(?![a-z])", t)
    if m:
        out["screen_in"] = float(m.group(1))
    m = re.search(
        r"(?:battery(?: life)?|lasts?|runtime|playback)[^0-9]{0,18}"
        + _NUM
        + r"\s*-?\s*(?:hour|hr|h)\b",
        t,
    ) or re.search(_NUM + r"\s*-?\s*(?:hour|hr|h)s?\b\s*(?:of\s+)?(?:battery|playback|runtime)", t)
    if m:
        out["hours"] = float(m.group(1))
    m = re.search(_NUM + r"\s*mah\b", t)
    if m:
        out["mah"] = float(m.group(1))
    return out


# ---- the mains scope gate (a model judgement, no device list) ----------------------------
KEYBOARD_ONLY = ("input.key", "input.key_matrix", "mech.keycap", "mech.stabilizer", "mech.plate")
# functions served by the device's controller or by the generic slots, never a block of their own
PLAIN = ("compute.mcu", "power.battery", "power.usb_in", "power.coin_cell", "power.solar")
# a block of one of these functions needs a named part (an MPN), not "any part of the function"
# blocks the case, the board and the support-part rules already provide
SKIP = (
    "mech.enclosure", "mech.chassis", "interconnect.pcb", "interconnect.cable", "mech.fastener",
    "mech.foam", "mech.standoff", "component.resistor", "component.capacitor",
    "component.inductor", "component.diode", "component.transistor", "component.crystal",
    "power.charger",
)  # fmt: skip
SPECIFIC = ("component.ic", "component.other", "other", "unknown", "mech.mount", "mech.chassis")
ACDC = dict(
    key="ac_dc",
    function_id="power.regulator",
    label="AC-DC module (certified, enclosed)",
    names=("hlk", "ac-dc"),
    terms=("HLK-PM12", "HLK-5M12", "HLK-PM01"),
    prefix="acdc",
)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:24] or "block"


def need_from_block(block: dict[str, Any], taken: set[str]) -> Need:
    """A function-block-diagram block -> a required slot with its search terms."""
    fid = block["function_id"]
    key = _slug(block.get("label") or fid)
    if not key[0].isalpha():
        key = "b_" + key
    while key in taken:
        key += "_2"
    taken.add(key)
    terms = tuple(str(x) for x in block.get("search_terms") or [])
    kicad = tuple(str(x) for x in block.get("kicad_names") or [])
    return Need(
        key=key,
        function_id=fid,
        label=str(block.get("label") or fid)[:40],
        count=max(1, int(block.get("count") or 1)),
        by_function=fid not in SPECIFIC and not terms,
        names=tuple(x.lower() for x in terms),
        terms=terms,
        kicad=kicad,
        pin_kind=_PIN_KIND.get(fid.split(".")[0], "sensor") if fid != "power.regulator" else None,
        prefix=re.sub(r"[^a-z0-9]", "", key)[:10],
        touch=bool(block.get("touchpoint")),
        groups=tuple(block.get("groups") or ()),
        requirement=str(block.get("requirement") or "")[:160],
    )


_PIN_KIND = {"input": "button", "sense": "sensor", "output": "motor", "comms": "sensor"}


MAINS_SYSTEM = """Decide whether a hardware request can be built as a LOW-VOLTAGE board behind
a certified, enclosed AC-DC module. Answer low_voltage_half=true only when the product's job is
to convert or distribute power or to charge things (its own electronics run at low voltage and
the mains side is just the module). Answer false when the product itself switches, dims or
heats mains-powered loads, or when mains is otherwise part of its function. One-sentence reason."""

MAINS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["low_voltage_half", "reason"],
    "properties": {"low_voltage_half": {"type": "boolean"}, "reason": {"type": "string"}},
}


async def low_voltage_mains(prompt: str) -> bool:
    """True when the request is a mains device whose electronics are a low-voltage half behind a
    certified AC-DC module. The call is made only for requests the classifier put out of scope."""
    if re.search(UNSAFE, prompt.lower()):
        return False
    from bara.live.ask import ask_json

    data, _ = await ask_json(MAINS_SYSTEM, prompt, MAINS_SCHEMA, name="mains_scope", timeout_s=30)
    return bool(data and data["low_voltage_half"])


CHARGER = Need(
    "charger",
    "power.charger",
    "Battery charger",
    1,
    True,
    terms=("TP4056",),
    prefix="chg",
)


def apply(
    spec: dict[str, Any],
    brief: dict[str, Any],
    has_parts: Any = None,
    blocks: dict[str, Any] | None = None,
    keyboard: bool = False,
) -> Completeness:
    """Add the required functions to the spec in place and return what was added.

    ``blocks`` is the device's function block diagram (see blocks.py): every block becomes a
    required slot that must resolve to a part or fail loudly. Without it only the general
    invariants run: a controller, a power path and a charger for a battery.
    """
    text = " ".join(
        str(x) for x in (spec.get("prompt"), brief.get("device"), brief.get("summary")) if x
    )
    out = Completeness(numbers=parse_numbers(str(spec.get("prompt") or text)))
    functions: list[dict[str, Any]] = spec.setdefault("functions", [])
    have = {f["function_id"]: f for f in functions}

    def add(fid: str, why: str, count: int = 1) -> None:
        if fid in have:
            have[fid]["count"] = max(int(have[fid].get("count") or 1), count)
            return
        row = {"function_id": fid, "required": True, "count": count, "source": "assumed"}
        functions.append(row)
        have[fid] = row
        out.notes.append(f"{fid}: {why}")

    if blocks:
        out.kind = str(blocks.get("device_class") or "") or None
        for key in ("avg_current_ma", "shell_g"):
            if isinstance(blocks.get(key), int | float):
                out.numbers[key] = float(blocks[key])
        taken: set[str] = set()
        listed = list(blocks.get("blocks") or [])
        if blocks.get("mains_input"):
            # one certified AC-DC module is the mains input; a second one the model listed
            # is the same job twice
            listed = [
                b
                for b in listed
                if not (
                    b.get("function_id") == ACDC["function_id"]
                    and re.search(r"ac[\s_/-]*dc|mains|isolated", str(b.get("label")).lower())
                )
            ]
        if blocks.get("mains_input"):
            acdc = Need(
                ACDC["key"], ACDC["function_id"], ACDC["label"], 1, False,
                names=ACDC["names"], terms=ACDC["terms"], prefix=ACDC["prefix"],
            )  # fmt: skip
            out.needs[acdc.key] = acdc
            taken.add(acdc.key)
            out.mains = True
            out.notes.append("mains input: low-voltage half behind a certified AC-DC module")
        if blocks.get("mains_input"):
            out.mains = True
        merged: dict[tuple[str, tuple[str, ...]], dict[str, Any]] = {}
        for block in listed:
            fid = block.get("function_id")
            terms = tuple(block.get("search_terms") or [])
            if fid in SKIP:
                continue
            if not terms and (fid.startswith("comms.") or fid in ("mech.mount", "mech.foot")):
                continue  # the controller module carries the radio; a bare mount has no part
            if fid in PLAIN:
                add(fid, f"block {block.get('label')}", max(1, int(block.get("count") or 1)))
                continue
            # identical parts are one block with a quantity
            row = merged.setdefault((fid, terms), {**block, "count": 0, "groups": []})
            row["count"] += max(1, int(block.get("count") or 1))
            row["groups"].append(f"{block.get('label')} x{max(1, int(block.get('count') or 1))}")
        for block in merged.values():
            need = need_from_block(block, taken)
            out.needs[need.key] = need
            if need.function_id == "compute.sbc":
                out.controller_keys += (need.key,)
        if not keyboard:  # no keys or plates on a gadget that is not a keyboard
            for fid in KEYBOARD_ONLY:
                if fid in have:
                    functions.remove(have.pop(fid))
        # the block diagram is authoritative: functions the brief only guessed are dropped
        covered = {n.function_id for n in out.needs.values()}
        for f in list(functions):
            if (
                not keyboard
                and f.get("source") not in ("explicit", "clarified")
                and f["function_id"] in covered
                or (f["function_id"] == "component.ic" and "component.ic" in covered)
            ):
                functions.remove(f)
                have.pop(f["function_id"], None)
        out.notes.append("block diagram: " + ", ".join(n.label for n in out.needs.values()))

    # controller: MCU, SBC, or a dedicated controller IC
    has_sbc = any(n.function_id == "compute.sbc" for n in out.needs.values())
    if "compute.sbc" in have and has_parts is not None and not has_parts("compute.sbc"):
        functions.remove(have.pop("compute.sbc"))
        add("compute.mcu", "no single-board computer in the catalog; an MCU module does the job")
    if "compute.mcu" not in have and "compute.sbc" not in have and not has_sbc and not out.mains:
        add("compute.mcu", "every device needs a controller")
    if out.mains and not has_sbc and "compute.mcu" not in have:
        out.controller_keys += tuple(
            n.key for n in out.needs.values() if n.function_id == "component.ic"
        )[:1]

    # power path
    power = ("power.battery", "power.usb_in", "power.coin_cell", "power.solar")
    portable = bool((blocks or {}).get("portable")) or brief.get("power_source") == "battery"
    if not any(f in have for f in power) and not out.mains:
        if portable:
            add("power.battery", "a portable device needs a battery")
        else:
            add("power.usb_in", "every device needs a power input")
    if "power.battery" in have:
        if "power.charger" in have:  # a listed charger is a slot of its own, never dropped
            functions.remove(have.pop("power.charger"))
        out.needs[CHARGER.key] = CHARGER
        out.notes.append("charger: a battery needs a charger (the controller's own counts)")
    return out


# ---- spec numbers: battery sizing and mass ---------------------------------------------
LIPO_G_PER_MAH = 0.022  # a small LiPo weighs about 22 g per Ah
BATTERY_MASS_SHARE = 0.20  # of the whole-device mass target
PCB_G = 5.0
DEFAULT_PART_G = {
    "compute.mcu": 3.0,
    "input.button": 0.3,
    "input.rotary_encoder": 2.0,
    "input.joystick": 6.0,
    "output.haptic": 3.0,
    "display.oled": 2.0,
    "display.tft": 25.0,
    "storage.sd_card": 1.0,
    "interconnect.jack": 1.5,
    "component.ic": 0.3,
}


def battery_limits(c: Completeness) -> tuple[float | None, float | None]:
    """(minimum mAh, maximum mAh) the spec numbers imply for the battery."""
    lo = hi = None
    n = c.numbers
    if "mah" in n:
        lo = n["mah"]
    if "hours" in n:
        need = n["hours"] * n.get("avg_current_ma", 30.0) * 1.2
        lo = max(lo or 0.0, need)
    if "mass_g" in n:
        hi = n["mass_g"] * BATTERY_MASS_SHARE / LIPO_G_PER_MAH
    return lo, hi


def part_mass_g(part: dict[str, Any], quantity: int = 1) -> tuple[float, bool]:
    """(grams, measured). A part's own mass when its record has one, else a category guess."""
    mech = part.get("mechanical") or {}
    if isinstance(mech.get("mass_g"), int | float):
        return float(mech["mass_g"]) * quantity, True
    facets = part.get("facets") or {}
    mah = facets.get("capacity_mah")
    if isinstance(mah, int | float):
        return float(mah) * LIPO_G_PER_MAH * quantity, False
    fids = [f.get("function_id") for f in part.get("functions", [])]
    if "power.battery" in fids:
        return 20.0 * quantity, False
    for fid in fids:
        if fid in DEFAULT_PART_G:
            return DEFAULT_PART_G[fid] * quantity, False
    return 1.0 * quantity, False


def estimate_mass(c: Completeness, parts: list[tuple[dict[str, Any], int]]) -> dict[str, Any]:
    electronics = sum(part_mass_g(p, q)[0] for p, q in parts)
    shell = c.numbers.get("shell_g", 12.0)
    return {
        "total_g": round(electronics + PCB_G + shell, 1),
        "electronics_g": round(electronics, 1),
        "pcb_g": PCB_G,
        "shell_g": shell,
    }


def display_inches(part: dict[str, Any]) -> float | None:
    name = f"{part.get('display_name') or ''} {part.get('summary') or ''}"
    m = re.search(_NUM + r"\s*(?:in\b|inch|\")", name.lower())
    return float(m.group(1)) if m else None


UNSAFE = r"\b(weapon|gun|jammer|jamming|taser|explosive|e-?bike|scooter|pacemaker|insulin)\b"
