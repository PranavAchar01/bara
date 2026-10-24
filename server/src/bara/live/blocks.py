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

SYSTEM = """You are the electronics lead on a hardware design tool. Given a device request, list
the function block diagram of a real, working product of that kind.

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
- Do not add parts the product does not have. No keyboards parts unless it is a keyboard.
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
        ],
        "properties": {
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
            "blocks",
        ],
        "properties": {
            "device_class": {"type": "string"},
            "mains_input": {"type": "boolean"},
            "portable": {"type": "boolean"},
            "avg_current_ma": {"type": "number"},
            "shell_g": {"type": "number"},
            "blocks": {"type": "array", "items": block},
        },
    }


async def derive(
    prompt: str, function_ids: list[str], hint: str = ""
) -> tuple[dict[str, Any] | None, str]:
    ids = ", ".join(function_ids)
    text = f"Device request: {prompt}\n{hint}\nAllowed function_id values: {ids}"
    data, note = await ask_json(SYSTEM, text, schema(function_ids), name="blocks", timeout_s=75)
    if data is not None and not data["blocks"]:
        return None, "empty block diagram"
    if data is not None:
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
