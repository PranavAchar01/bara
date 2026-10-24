"""Function block diagram: what a device of this class is made of, derived by the model.

Replaces hand-written part lists. The model names the blocks (input, sensing, compute, comms,
power, output, mechanical) with a vocab function id and search terms for each; completeness
turns every block into a required slot that must resolve (curated catalog, KiCad library,
LCSC) or fail loudly by name.
"""

from __future__ import annotations

from typing import Any

from bara.live.ask import ask_json

CATEGORIES = ["input", "sensing", "compute", "comms", "power", "output", "mechanical"]

SYSTEM = """You are the electronics lead on a hardware design tool. Given a device request, work
from the use case to the parts, then list the function block diagram of a real, working product.

First understand the use case (use_case): the jobs the person does with it (what they want to
get done, in plain verbs), the environment it lives in, its power source, and how it is held,
worn or mounted. Then derive every function those jobs require. Each block carries `why`: the
job from use_case.jobs it serves, so every part traces back to something the person does. A job
with no ready-made part still gets a block (name the closest real part or describe the
function); never skip a job because no part comes to mind.

Rules:
- One block per distinct job, grouped by category: input, sensing, compute, comms, power,
  output, mechanical. Use identical parts as ONE block with a count (twelve buttons are one
  block with count 12).
- Every block carries a function_id from the allowed list, a short label, a count, and
  search_terms: up to three real manufacturer part numbers (MPNs) a hobbyist can buy on LCSC or
  that exist in KiCad's library, best first. For generic parts (buttons, headers, batteries)
  leave search_terms empty. Never invent an MPN; if you do not know one, leave it empty.
- Include everything the product needs to work as that product: the controller (compute.mcu, or
  compute.sbc when the product runs a full operating system), a power path, the sensing and
  I/O its function implies (a pointing device needs its sensor, an audio device its codec or
  amplifier and transducer, a display device its driver or bridge and connector, a wireless
  product its radio), and the mechanical parts users touch.
- List only parts that must be chosen and bought. Leave out: the enclosure, the PCB, cables,
  fasteners, gaskets, standoffs, resistors/capacitors/inductors/diodes/crystals (support parts
  are added automatically), on-chip radios and antennas of a module you already list, and
  rigid flex details. compute.mcu means a programmable microcontroller module only; a dedicated
  protocol or power IC is component.ic (a product with no programmable logic has no compute.mcu).
- Put the pointing sensor, codec, amplifier, bridge, driver, radio or power IC a product needs
  as its own block with its MPN in search_terms.
- touchpoint is true for a block a person touches, looks at, listens to or plugs into, or that
  must face the outside world (buttons, sticks, screens, speakers, ports, lenses, optical
  sensors, microphones); false for parts hidden inside the housing.
- requirement: the key numbers the chosen part must meet to make the product what it is, as one
  short phrase (a display's diagonal size and resolution, a connector standard, a rated
  voltage or current, a battery capacity). Empty when any part of the function will do.
- Every block must serve a function the product's brief implies. Do not add parts the product
  does not have.
- mains_input is true only when the product plugs into AC mains. Its low-voltage side is built
  behind a certified AC-DC module; do not design any mains-side circuit.
- portable is true for battery-powered products. avg_current_ma is the typical average draw.
  shell_g is the mass of a typical shell/housing for the product in grams.
- Be a careful engineer, not a minimalist: prefer the complete, shippable BOM."""


def schema(function_ids: list[str]) -> dict[str, Any]:
    block = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "category",
            "function_id",
            "label",
            "count",
            "search_terms",
            "kicad_names",
            "touchpoint",
            "requirement",
            "why",
        ],
        "properties": {
            "why": {"type": "string"},
            "category": {"type": "string", "enum": CATEGORIES},
            "function_id": {"type": "string", "enum": function_ids},
            "label": {"type": "string"},
            "count": {"type": "integer"},
            "search_terms": {"type": "array", "items": {"type": "string"}},
            "kicad_names": {"type": "array", "items": {"type": "string"}},
            "touchpoint": {"type": "boolean"},
            "requirement": {"type": "string"},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "device_class",
            "mains_input",
            "portable",
            "avg_current_ma",
            "shell_g",
            "use_case",
            "blocks",
        ],
        "properties": {
            "use_case": {
                "type": "object",
                "additionalProperties": False,
                "required": ["jobs", "environment", "power", "handling"],
                "properties": {
                    "jobs": {"type": "array", "items": {"type": "string"}},
                    "environment": {"type": "string"},
                    "power": {"type": "string"},
                    "handling": {"type": "string"},
                },
            },
            "device_class": {"type": "string"},
            "mains_input": {"type": "boolean"},
            "portable": {"type": "boolean"},
            "avg_current_ma": {"type": "number"},
            "shell_g": {"type": "number"},
            "blocks": {"type": "array", "items": block},
        },
    }


AUDIT_SYSTEM = """You audit a function block diagram for a hardware product and return the blocks
it is missing. Walk every function chain the product implies and check each link has a block:
- sound out: source, converter or codec, amplifier, transducer, connector
- sound in: transducer, preamp or converter, controller
- display: panel, its driver or bridge, backlight supply, connector to the board
- input: the sensor or switch, anything that conditions its signal, the controller input
- wireless or wired link: radio or PHY, antenna or connector, protection
- storage: the medium, its socket or controller
- power: input or cell, protection, charger or converter, regulators for each voltage, monitor
- anything the product's defining function needs (a motion sensor, a driver for a motor, a
  scaler for a video input)
Return ONLY the missing blocks, in the same shape as the listed ones, with real MPNs when you
know them. Return an empty list when the diagram is complete. Never repeat a listed block."""


async def _complete_chains(
    prompt: str, data: dict[str, Any], function_ids: list[str], note: str
) -> str:
    """Second pass: every implied function chain gets all of its blocks."""
    listed = "\n".join(f"- {b['label']} ({b['function_id']}) x{b['count']}" for b in data["blocks"])
    item = schema(function_ids)["properties"]["blocks"]["items"]
    out_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["missing"],
        "properties": {"missing": {"type": "array", "items": item}},
    }
    got, why = await ask_json(
        AUDIT_SYSTEM,
        f"Device request: {prompt}\nListed blocks:\n{listed}\n"
        f"Allowed function_id values: {', '.join(function_ids)}",
        out_schema,
        name="block_audit",
        timeout_s=60,
    )
    if got is None:
        return f"{note}; {why}".strip("; ")
    seen = {(b["function_id"], b["label"].lower()) for b in data["blocks"]}
    for blk in got["missing"]:
        if (blk["function_id"], blk["label"].lower()) not in seen:
            data["blocks"].append(blk)
    return note


async def derive(
    prompt: str, function_ids: list[str], hint: str = ""
) -> tuple[dict[str, Any] | None, str]:
    ids = ", ".join(function_ids)
    text = f"Device request: {prompt}\n{hint}\nAllowed function_id values: {ids}"
    data, note = await ask_json(SYSTEM, text, schema(function_ids), name="blocks", timeout_s=75)
    if data is not None and not data["blocks"]:
        return None, "empty block diagram"
    if data is not None:
        note = await _complete_chains(prompt, data, function_ids, note)
        note = await _name_the_parts(prompt, data, note)
    return data, note


NAMES_SYSTEM = """You name real, purchasable parts. For each numbered block of a product, give
up to three real manufacturer part numbers sold on LCSC (search_terms, best first) and up to
three KiCad library symbol or footprint names (kicad_names) that fit it. Name the actual
mechanism a product of that kind uses. Never invent a part number; leave a list empty only when
the block is a plain generic part."""


async def _name_the_parts(prompt: str, data: dict[str, Any], note: str) -> str:
    """One follow-up call for blocks that came back with no part names at all."""
    bare = [
        i for i, b in enumerate(data["blocks"]) if not b["search_terms"] and not b["kicad_names"]
    ]
    if not bare:
        return note
    lines = "\n".join(
        f"{i}: {data['blocks'][i]['label']} ({data['blocks'][i]['function_id']})" for i in bare
    )
    item = {
        "type": "object",
        "additionalProperties": False,
        "required": ["index", "search_terms", "kicad_names"],
        "properties": {
            "index": {"type": "integer"},
            "search_terms": {"type": "array", "items": {"type": "string"}},
            "kicad_names": {"type": "array", "items": {"type": "string"}},
        },
    }
    out_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["blocks"],
        "properties": {"blocks": {"type": "array", "items": item}},
    }
    got, extra = await ask_json(
        NAMES_SYSTEM,
        f"Product: {prompt}\nBlocks:\n{lines}",
        out_schema,
        name="block_names",
        timeout_s=45,
    )
    if got is None:
        return f"{note}; {extra}".strip("; ")
    for row in got["blocks"]:
        if row["index"] in bare:
            blk = data["blocks"][row["index"]]
            blk["search_terms"] = [t for t in row["search_terms"] if t][:3]
            blk["kicad_names"] = [t for t in row["kicad_names"] if t][:3]
    return note


def chain(
    blocks: dict[str, Any] | None, slots: list[Any], dropped: list[dict[str, str]]
) -> dict[str, Any]:
    """The audit trail: use case -> jobs -> functions -> blocks -> parts, one link per slot."""
    links = []
    for slot in slots:
        need = slot.need
        if need is None:
            continue
        if slot.chosen is not None:
            outcome = f"part {slot.chosen.get('part_id')}"
        elif slot.covered_by:
            outcome = f"covered by {slot.covered_by}"
        else:
            outcome = f"UNRESOLVED: {slot.unresolved or 'no part'}"
        links.append(
            {
                "job": need.why,
                "function_id": need.function_id,
                "block": need.label,
                "quantity": max(1, slot.quantity),
                "outcome": outcome,
            }
        )
    return {
        "use_case": (blocks or {}).get("use_case"),
        "links": links,
        "dropped": dropped,
    }
