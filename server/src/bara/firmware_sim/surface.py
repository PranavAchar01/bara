"""The play surface of one build: which controls the person gets and how each output shows.

One model call turns the build's real parts and I/O plan into a surface spec (a control spec per
input, a display spec per output, the lead control). Everything the model says is checked against
the plan: an unknown input or output is dropped, a control type that does not fit the input's kind
is replaced by the kind's own, a sensor range cannot leave the part's range, and every real input
gets a control whether the model named it or not. When no model answers, the same spec is derived
from the plan alone. No branch looks at what the device is."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from bara.live.llm_json import call_json

# input kind -> the control types that can drive it (the first is the default)
CONTROLS: dict[str, tuple[str, ...]] = {
    "key": ("key",),
    "button": ("button", "toggle"),
    "switch": ("toggle", "button"),
    "encoder": ("knob",),
    "axis": ("stick", "slider"),
    "sensor": ("slider",),
}
# output kind -> how it can show
SHOWS: dict[str, tuple[str, ...]] = {
    "display": ("screen",),
    "led": ("led", "led_strip"),
    "tone": ("buzzer",),
    "motor": ("motor",),
    "serial": ("console",),
    "hid": ("console",),
}

SURFACE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["controls", "outputs", "lead"],
    "properties": {
        "controls": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["input_id", "control", "label", "unit", "group"],
                "properties": {
                    "input_id": {"type": "string"},
                    "control": {
                        "type": "string",
                        "enum": ["key", "button", "toggle", "knob", "stick", "slider"],
                    },
                    "label": {"type": "string"},
                    "unit": {"type": "string"},
                    "group": {"type": "string"},
                },
            },
        },
        "outputs": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["output_id", "show", "label"],
                "properties": {
                    "output_id": {"type": "string"},
                    "show": {
                        "type": "string",
                        "enum": ["screen", "led", "led_strip", "buzzer", "motor", "console"],
                    },
                    "label": {"type": "string"},
                },
            },
        },
        "lead": {"type": "string"},
    },
}

SYSTEM = (
    "You design the play surface for a simulator of one electronic device. You are given its "
    "real inputs and outputs. For every input choose the control that fits its kind (key or "
    "button: button; switch: toggle; encoder: knob; axis: stick or slider; sensor: slider), a "
    "short standardized label in professional technical wording (for a sensor the measured "
    "quantity, for example 'Soil volumetric water content', 'Ambient temperature', "
    "'Illuminance', 'Sound pressure level', 'Battery state of charge'; for a control its "
    "function, for example 'Start / stop', 'Select'), the unit exactly as given for sensors "
    "(empty otherwise), and a group name of one or two words that gathers related controls "
    "('Measurements', 'Controls', 'Direction'). For every output choose how it shows: display: "
    "screen; led: led, or led_strip when it is a row of lights; buzzer: buzzer; motor: motor; "
    "serial or hid: console. Name each output in plain technical words. lead is the id of the "
    "one input a person should reach for first. Use only ids you were given. Never invent an "
    "input or output. No brand names, no part numbers, no dashes, no casual wording."
)

_BRANDS = re.compile(
    r"\b(arduino|raspberry|adafruit|sparkfun|seeed|nordic|espressif|cherry|kailh|gateron|"
    r"nintendo|sony|xbox|playstation|game ?boy|zmk|qmk|nrf\w*|rp20\d+|esp\d+\w*|stm32\w*)\b",
    re.I,
)


def clean(text: Any, n: int = 32) -> str:
    """UI copy: printable ASCII plus the degree and micro signs, no dashes used as punctuation, no
    brand names."""
    s = str(text or "").replace("—", ", ").replace("–", "-")
    s = re.sub(r"[^ -~°µ]", "", s)
    s = _BRANDS.sub("", s)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s+,", ",", s).strip(" ,.-")
    return s[:n].strip()


def _signature(io: dict[str, Any]) -> str:
    rows = [(i["id"], i["kind"], i.get("unit", "")) for i in io["inputs"]]
    rows += [(o["id"], o["kind"], "") for o in io["outputs"]]
    return hashlib.sha1(json.dumps(rows).encode()).hexdigest()[:12]


def default_group(i: dict[str, Any]) -> str:
    return {
        "key": "Keys",
        "button": "Buttons",
        "switch": "Switches",
        "encoder": "Knobs",
        "axis": "Sticks",
        "sensor": "Measurements",
    }.get(i["kind"], "Controls")


def _lead_default(io: dict[str, Any]) -> str:
    order = ("sensor", "button", "encoder", "axis", "switch", "key")
    for kind in order:
        for i in io["inputs"]:
            if i["kind"] == kind:
                return str(i["id"])
    return ""


def _control(i: dict[str, Any], want: dict[str, Any] | None) -> dict[str, Any]:
    allowed = CONTROLS.get(i["kind"], ("button",))
    if i["kind"] == "axis":  # one stick drives an x and a y input; a dial is a lone slider
        allowed = ("stick",) if str(i["id"]).endswith((".x", ".y")) else ("slider",)
    ctl = want.get("control") if want else None
    row: dict[str, Any] = {
        "input_id": i["id"],
        "kind": i["kind"],
        "instance_id": i.get("instance_id"),
        "index": i.get("index"),
        "control": ctl if ctl in allowed else allowed[0],
        "label": clean(want.get("label") if want else "") or clean(i["label"]) or i["id"],
        "group": clean(want.get("group") if want else "", 20) or default_group(i),
    }
    if i["kind"] == "sensor":  # the range and unit belong to the part, not to the model
        row.update(unit=i["unit"], min=i["min"], max=i["max"], default=i["default"])
    else:
        row["unit"] = ""
    # a joystick axis pair keeps its name from the plan when the model's label is empty
    return row


def _output(o: dict[str, Any], want: dict[str, Any] | None) -> dict[str, Any]:
    allowed = SHOWS.get(o["kind"], ("console",))
    show = want.get("show") if want else None
    return {
        "output_id": o["id"],
        "kind": o["kind"],
        "show": show if show in allowed else allowed[0],
        "label": clean(want.get("label") if want else "", 40) or clean(o["label"], 40),
    }


def build_surface(io: dict[str, Any], model: dict[str, Any] | None) -> dict[str, Any]:
    """The checked surface: the model choices where they fit the plan, else the plan itself."""
    m = model or {}
    wc = {c.get("input_id"): c for c in m.get("controls") or [] if isinstance(c, dict)}
    wo = {c.get("output_id"): c for c in m.get("outputs") or [] if isinstance(c, dict)}
    controls = [_control(i, wc.get(i["id"])) for i in io["inputs"]]
    outputs = [_output(o, wo.get(o["id"])) for o in io["outputs"]]
    ids = {i["id"] for i in io["inputs"]}
    lead = (model or {}).get("lead")
    return {
        "controls": controls,
        "outputs": outputs,
        "lead": lead if lead in ids else _lead_default(io),
        "sig": _signature(io),
        "by": "model" if model else "parts",
    }


def _brief(build: dict[str, Any], io: dict[str, Any]) -> str:
    lines = [f"Device request: {clean(build.get('prompt'), 200)}", "Parts:"]
    for p in build.get("parts") or []:
        card = p.get("card") or {}
        lines.append(
            f"- {card.get('primary_function') or ''}: {clean(card.get('display_name'), 50)} "
            f"x{p.get('quantity') or 1}"
        )
    lines.append("Inputs (id | kind | label | range):")
    for i in io["inputs"][:60]:
        rng = f" | {i['min']} to {i['max']} {i['unit']}" if i["kind"] == "sensor" else ""
        lines.append(f"- {i['id']} | {i['kind']} | {i['label']}{rng}")
    if len(io["inputs"]) > 60:
        lines.append(f"- and {len(io['inputs']) - 60} more inputs of the same kinds")
    lines.append("Outputs (id | kind | label):")
    lines += [f"- {o['id']} | {o['kind']} | {o['label']}" for o in io["outputs"]]
    return "\n".join(lines)


class SurfaceStore:
    """Surfaces cached per build on disk, keyed by the plan's signature."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, build_id: str) -> Path:
        return self.root / f"{re.sub(r'[^A-Za-z0-9_-]', '', build_id)}.json"

    def get(self, build_id: str, sig: str) -> dict[str, Any] | None:
        try:
            data = json.loads(self._path(build_id).read_text())
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) and data.get("sig") == sig else None

    def put(self, build_id: str, surface: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._path(build_id).write_text(json.dumps(surface))


async def make_surface(
    build: dict[str, Any],
    io: dict[str, Any],
    store: SurfaceStore | None,
    build_id: str,
    cerebras_model: str,
    anthropic_model: str,
    refresh: bool = False,
) -> dict[str, Any]:
    sig = _signature(io)
    if store and not refresh:
        hit = store.get(build_id, sig)
        if hit:
            return hit
    res, notes = await call_json(
        SYSTEM,
        _brief(build, io),
        SURFACE_SCHEMA,
        name="sim_surface",
        cerebras_model=cerebras_model,
        anthropic_model=anthropic_model,
        timeout_s=25.0,
    )
    surface = build_surface(io, res.data if res else None)
    surface["notes"] = notes
    if store and res:  # a part-derived fallback is not cached: the next open tries the model again
        store.put(build_id, surface)
    return surface
