"""Prompt -> AI brief (JSON) -> SPEC Spec.

The brief is the one place a model reads the prompt. It is written by the provider cascade
(Cerebras, then Anthropic) under an enum-constrained schema, and by deterministic rules when
no provider answers. Every later stage reads only the brief and the catalog. The brief is
logged verbatim and kept on the run so the report and tests can show it.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from bara.catalog import Catalog
from bara.live.llm_json import call_json
from bara.router import Router, normalize

log = logging.getLogger(__name__)

LAYOUT_STYLES = ["split", "unibody", "macropad", "none"]
FEATURE_KINDS = ["knob", "screen", "trackball", "battery", "led", "speaker", "sensor", "button"]
SIDES = ["left", "right", "center", None]
DISPLAY_TYPES = ["oled", "epaper", "tft", "seven_segment", "lcd_char", "memory_lcd", None]
COLOUR_TARGETS = ["case", "keycaps", "accent", "trackball", "knob", "all"]
BLOCKING = ["primary_function", "which_device", None]

# Colour names a person types, as sRGB hex. Used by the rules path and to fill a hex the
# model left out. Values are common paint-chip approximations, not brand colours.
COLOUR_WORDS: dict[str, str] = {
    "white": "#F2F2EE", "black": "#1E1E1E", "grey": "#8A8A8A", "gray": "#8A8A8A",
    "red": "#C8322D", "orange": "#E8772E", "yellow": "#E9C23B", "green": "#4F8A4B",
    "blue": "#2F5DA8", "navy": "#1F2F55", "purple": "#6A4C93", "pink": "#E89AB4",
    "sage": "#9CAF88", "cream": "#F1E6CC", "beige": "#D9C7A7", "brown": "#7A5638",
    "teal": "#2F8C8A", "mint": "#A8D8C0", "lavender": "#B7A6D9", "olive": "#7D7F3A",
    "silver": "#BFC3C7", "gold": "#C9A23A", "tan": "#C8AA80", "charcoal": "#36393D",
}  # fmt: skip

# Words the shared router keyword list does not cover yet, for the rules path only.
EXTRA_FUNCTION_WORDS: dict[str, list[str]] = {
    "rover": ["output.motor_dc", "mech.wheel", "mech.chassis"],
    "robot": ["output.motor_dc", "mech.wheel", "mech.chassis"],
    "car": ["output.motor_dc", "mech.wheel", "mech.chassis"],
    "watering": ["output.pump", "sense.soil_moisture"],
}
EXTRA_DEVICE_CLASS = {"output": "robot", "sense": "sensor_station", "display": "display_device"}

NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "single": 1, "two": 2, "dual": 2, "pair": 2, "three": 3,
    "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}  # fmt: skip

SYSTEM_PROMPT = (
    "You turn one hardware build request into a build brief for a parts engine. Answer only "
    "with JSON matching the schema. Write what the person asked for; fill gaps with the most "
    "common hobby choice and never invent features they did not ask for.\n"
    "summary: one plain sentence describing the device to build.\n"
    "scope: out_of_scope only for medical diagnosis, weapons, jamming, mains appliances, "
    "rideable vehicles or impossible requests. A mains appliance is one whose own circuit "
    "switches, heats or drives mains power (heater, kettle, mains relay); a product whose "
    "electronics run on low voltage from a wall adapter or a certified AC-DC module is "
    "in_scope. A vague request is in_scope.\n"
    "functions: every function id the device needs (keys, controller, display, sensors, "
    "power, knob hardware, keycaps), from the enum.\n"
    "layout_style: split for two halves, unibody for a one-piece keyboard, macropad for a "
    "small key grid, none for devices that are not keyboards.\n"
    "key_count: total keys across both halves; rows and cols per half; thumb_keys per half.\n"
    "stagger: column for ergonomic splits, ortho for grids, row for classic boards.\n"
    "switch_family: choc_v1 for low profile or choc, mx otherwise, null if no keys.\n"
    "mcu: a controller only when the request names one, else null.\n"
    "wireless: ble for wireless or bluetooth keyboards, wifi when the device needs the "
    "internet, none otherwise. power_source battery when wireless or handheld.\n"
    "features: one entry per knob, screen, trackball, battery, led, speaker, sensor or "
    "button group, with its count, side and position words as written (for example "
    "'top left', 'right thumb'). A feature the request negates ('no trackball') is left "
    "out.\n"
    "colours: every colour named, with what it applies to and a hex value.\n"
    "blocking_facet: primary_function only when the request names no job at all (a mood, "
    "a place, 'a gadget'); which_device for unrelated alternatives; else null."
)


def brief_schema(function_ids: list[str], device_classes: list[str]) -> dict[str, Any]:
    nullable_int = {"type": ["integer", "null"]}
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "summary",
            "scope",
            "device",
            "device_class",
            "functions",
            "layout_style",
            "key_count",
            "rows",
            "cols",
            "thumb_keys",
            "stagger",
            "switch_family",
            "switch_type",
            "mcu",
            "wireless",
            "power_source",
            "display_type",
            "features",
            "colours",
            "tented",
            "blocking_facet",
        ],  # fmt: skip
        "properties": {
            "summary": {"type": "string"},
            "scope": {"type": "string", "enum": ["in_scope", "out_of_scope"]},
            "device": {"type": "string"},
            "device_class": {"type": "string", "enum": device_classes},
            "functions": {"type": "array", "items": {"type": "string", "enum": function_ids}},
            "layout_style": {"type": "string", "enum": LAYOUT_STYLES},
            "key_count": nullable_int,
            "rows": nullable_int,
            "cols": nullable_int,
            "thumb_keys": nullable_int,
            "stagger": {"type": ["string", "null"], "enum": ["column", "row", "ortho", None]},
            "switch_family": {"type": ["string", "null"], "enum": ["mx", "choc_v1", None]},
            "switch_type": {
                "type": ["string", "null"],
                "enum": ["linear", "tactile", "clicky", None],
            },
            "mcu": {"type": ["string", "null"]},
            "wireless": {"type": "string", "enum": ["none", "ble", "wifi"]},
            "power_source": {"type": "string", "enum": ["usb", "battery"]},
            "display_type": {"type": ["string", "null"], "enum": DISPLAY_TYPES},
            "features": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["kind", "count", "side", "position"],
                    "properties": {
                        "kind": {"type": "string", "enum": FEATURE_KINDS},
                        "count": {"type": "integer"},
                        "side": {"type": ["string", "null"], "enum": SIDES},
                        "position": {"type": ["string", "null"]},
                    },
                },
            },
            "colours": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["target", "name", "hex"],
                    "properties": {
                        "target": {"type": "string", "enum": COLOUR_TARGETS},
                        "name": {"type": "string"},
                        "hex": {"type": "string"},
                    },
                },
            },
            "tented": {"type": "boolean"},
            "blocking_facet": {"type": ["string", "null"], "enum": BLOCKING},
        },
    }


@dataclass
class BriefResult:
    brief: dict[str, Any]
    classifier: dict[str, Any]
    warnings: list[dict[str, Any]] = field(default_factory=list)


# ---- deterministic rules ---------------------------------------------------------------
def _num(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    return NUMBER_WORDS.get(token)


def _negated(text: str, word: str) -> bool:
    return re.search(rf"\b(no|without|not)\s+(an?\s+)?{word}", text) is not None


def _count_of(text: str, word: str) -> int:
    """'two knobs' -> 2, 'a knob' -> 1, 'knob' -> 1, 'no knob' -> 0, absent -> 0."""
    if not re.search(rf"\b{word}s?\b", text) or _negated(text, word):
        return 0
    m = re.search(rf"\b(\w+)[\s-]+{word}s?\b", text)
    if m and _num(m.group(1)) is not None:
        return int(_num(m.group(1)) or 1)
    return 1


def _side_near(text: str, word: str) -> tuple[str | None, str | None]:
    m = re.search(rf"{word}s?\s+(on\s+the\s+|at\s+the\s+|in\s+the\s+)?([a-z ]{{0,24}})", text)
    tail = m.group(2) if m else ""
    m2 = re.search(rf"((top|bottom|upper|lower)\s+(left|right)|left|right)\s+{word}", text)
    head = m2.group(1) if m2 else ""
    where = " ".join(x for x in (head, tail) if x).strip()
    position = re.sub(r"\b(and|with|a|the)\b.*$", "", where).strip() or None
    side = None
    for s in ("left", "right", "center"):
        if position and re.search(rf"\b{s}\b", position):
            side = s
    return side, position


def rules_brief(prompt: str, router: Router, catalog: Catalog) -> dict[str, Any]:
    norm = normalize(prompt)
    text = " " + prompt.lower().replace("-", " ") + " "
    c = router.keyword_classify(norm)
    known = set(catalog.function_ids())
    functions: list[str] = list(c["functions"])
    for word, fids in EXTRA_FUNCTION_WORDS.items():
        if re.search(rf"\b{word}\b", text):
            functions += [f for f in fids if f in known and f not in functions]
    if functions and c["blocking_facet"] == "primary_function":
        c["blocking_facet"] = None
        c["device_class"] = EXTRA_DEVICE_CLASS.get(functions[0].split(".")[0], "other")

    is_keyboard = bool(re.search(r"\b(keyboard|keypad|macro ?pad|split|keys?)\b", text))
    if re.search(r"\b\d+\s*x\s*\d+\b", text) and "pad" in text:
        is_keyboard = True
    layout_style = "none"
    if is_keyboard:
        layout_style = "split" if re.search(r"\bsplit\b", text) else "unibody"
        if re.search(r"\bmacro ?pad|keypad|numpad\b", text):
            layout_style = "macropad"

    rows = cols = key_count = None
    grid = re.search(r"\b(\d+)\s*x\s*(\d+)\b", text)
    if grid:
        cols, rows = int(grid.group(1)), int(grid.group(2))
        key_count = cols * rows
    m = re.search(r"\b(\d+)\s*keys?\b", text)
    if m:
        key_count = int(m.group(1))

    features: list[dict[str, Any]] = []
    for word, kind in (("knob", "knob"), ("encoder", "knob"), ("trackball", "trackball")):
        n = _count_of(text, word)
        if n and not any(f["kind"] == kind for f in features):
            side, position = _side_near(text, word)
            features.append({"kind": kind, "count": n, "side": side, "position": position})
    display_type = None
    if re.search(r"\b(e ?ink|e ?paper|epaper)\b", text):
        display_type = "epaper"
    elif re.search(r"\b(oled|screen|display)\b", text) and not _negated(text, "screen"):
        display_type = "oled"
    elif "display.seven_segment" in functions:
        display_type = "seven_segment"
    if display_type:
        side, position = _side_near(text, "screen")
        features.append({"kind": "screen", "count": 1, "side": side, "position": position})

    wireless = "none"
    if re.search(r"\b(wireless|bluetooth|ble)\b", text):
        wireless = "ble"
    if re.search(r"\b(wifi|wi fi|internet|online)\b", text):
        wireless = "wifi"
    handheld = bool(re.search(r"\b(handheld|portable|pocket|rover|robot|car)\b", text))
    battery = wireless == "ble" or handheld or bool(re.search(r"\bbattery\b", text))
    if battery:
        features.append({"kind": "battery", "count": 1, "side": None, "position": None})

    switch_family = None
    if is_keyboard:
        switch_family = "choc_v1" if re.search(r"\b(choc|low profile)\b", text) else "mx"
    switch_type = next((t for t in ("linear", "tactile", "clicky") if f" {t} " in text), None)

    colours: list[dict[str, Any]] = []
    found = sorted(
        (m.start(), m.end(), word)
        for word in COLOUR_WORDS
        for m in re.finditer(rf"\b{word}\b", text)
    )
    plain = 0
    for _start, end, word in found:
        after = text[end : end + 14]
        target = "trackball" if "trackball" in after else "knob" if "knob" in after else None
        if target is None:
            target = ("case", "keycaps" if is_keyboard else "accent", "accent")[min(plain, 2)]
            plain += 1
        colours.append({"target": target, "name": word, "hex": COLOUR_WORDS[word]})

    # Functions the brief implies; every id must exist in the loaded vocab.
    implied: list[str] = []
    if is_keyboard:
        implied += ["input.key", "mech.keycap"]
    if any(f["kind"] == "knob" for f in features):
        implied += ["input.rotary_encoder", "mech.knob"]
    if any(f["kind"] == "trackball" for f in features):
        implied += ["input.trackball"]
    if display_type:
        implied += [f"display.{display_type}"]
    if functions or is_keyboard:
        implied += ["compute.mcu"]
    implied += ["power.battery"] if battery else ["power.usb_in"]
    if wireless == "ble":
        implied += ["comms.ble"]
    if wireless == "wifi":
        implied += ["comms.wifi"]
    functions = [f for f in functions if f != "input.key_matrix" and not _negated_fn(text, f)]
    for f in implied:
        if f in known and f not in functions:
            functions.append(f)
    if any(f["kind"] == "screen" for f in features):
        functions = [
            f for f in functions if not f.startswith("display.") or f == f"display.{display_type}"
        ]

    device_class = c["device_class"]
    if is_keyboard:
        device_class = "input_device"
    elif handheld:
        device_class = "handheld"
    head = re.split(r"\b(with|that|which|and)\b", norm)[0]
    words = [w for w in head.split() if w not in {"a", "an", "the", "small", "my"}]
    device = " ".join(words[-3:]) if words else "gadget"
    if is_keyboard:
        device = {"split": "split keyboard", "macropad": "macropad"}.get(layout_style, "keyboard")
    blocking = c["blocking_facet"] if not is_keyboard else None
    return {
        "summary": f"A {device} built from the prompt '{prompt.strip()[:80]}'.",
        "scope": c["scope"] if c["scope"] in ("in_scope", "out_of_scope") else "in_scope",
        "device": device,
        "device_class": device_class if device_class in catalog.device_classes() else "other",
        "functions": functions,
        "layout_style": layout_style,
        "key_count": key_count,
        "rows": rows,
        "cols": cols,
        "thumb_keys": None,
        "stagger": None,
        "switch_family": switch_family,
        "switch_type": switch_type,
        "mcu": None,
        "wireless": wireless,
        "power_source": "battery" if battery else "usb",
        "display_type": display_type,
        "features": features,
        "colours": colours,
        "tented": bool(re.search(r"\btent(ed|ing)?\b", text)),
        "blocking_facet": blocking,
    }


def _negated_fn(text: str, function_id: str) -> bool:
    word = function_id.split(".")[-1].replace("_", " ")
    return _negated(text, word)


def normalise_brief(brief: dict[str, Any], catalog: Catalog) -> dict[str, Any]:
    """Fill defaults the rest of the engine relies on; never adds a feature."""
    out = dict(brief)
    known = set(catalog.function_ids())
    out["functions"] = [f for f in out.get("functions", []) if f in known]
    if out.get("layout_style") in ("split", "unibody", "macropad"):
        for f in ("input.key", "mech.keycap", "compute.mcu"):
            if f not in out["functions"]:
                out["functions"].append(f)
        out["switch_family"] = out.get("switch_family") or "mx"
        if out.get("key_count") is None:
            rows, cols = out.get("rows"), out.get("cols")
            out["key_count"] = rows * cols if rows and cols else None
    for colour in out.get("colours", []):
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", colour.get("hex") or ""):
            colour["hex"] = COLOUR_WORDS.get(colour.get("name", "").lower(), "#9E9E9E")
        colour["hex"] = colour["hex"].upper()
    knobs = sum(f["count"] for f in out.get("features", []) if f["kind"] == "knob")
    if knobs:
        for f in ("input.rotary_encoder", "mech.knob"):
            if f in known and f not in out["functions"]:
                out["functions"].append(f)
    return out


async def write_brief(prompt: str, catalog: Catalog, router: Router, settings: Any) -> BriefResult:
    started = time.monotonic()
    schema = brief_schema(catalog.function_ids(), catalog.device_classes())
    result, notes = await call_json(
        SYSTEM_PROMPT,
        prompt,
        schema,
        name="brief",
        cerebras_model=settings.cerebras_model,
        anthropic_model=settings.anthropic_model,
        timeout_s=settings.llm_timeout_s,
    )
    warnings: list[dict[str, Any]] = []
    if result is not None:
        brief = result.data
        classifier = {
            "stage": "llm",
            "confidence": 0.85,
            "margin": None,
            "model": result.model,
            "latency_ms": result.latency_ms,
            "provider": result.provider,
            "fallback": result.fallback,
        }
        if result.fallback:
            warnings.append(_warn("llm_fallback", "info", "The backup model wrote the brief."))
    else:
        brief = rules_brief(prompt, router, catalog)
        classifier = {
            "stage": "rules",
            "confidence": 0.6,
            "margin": None,
            "model": None,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "provider": None,
            "fallback": True,
        }
        warnings.append(
            _warn(
                "llm_degraded",
                "warning",
                ("No model answered (" + "; ".join(notes) + "). Wrote the brief with rules."),
            )
        )
    brief = normalise_brief(brief, catalog)
    return BriefResult(brief=brief, classifier=classifier, warnings=warnings)


def _warn(code: str, severity: str, message: str) -> dict[str, Any]:
    return {
        "warning_id": "w_llm",
        "code": code,
        "severity": severity,
        "message": message[:300],
        "subjects": [],
        "stage": "classify",
    }


# ---- brief -> Spec ---------------------------------------------------------------------
def _req(facet: str, op: str, value: Any, source: str, label: str) -> dict[str, Any]:
    return {
        "req_id": "",
        "facet": facet,
        "op": op,
        "value": value,
        "unit": None,
        "source": source,
        "text_span": None,
        "label": label[:80],
    }


def spec_from_brief(
    prompt: str,
    brief: dict[str, Any],
    classifier: dict[str, Any],
    *,
    assumptions: list[dict[str, Any]],
    clarified: list[dict[str, Any]],
) -> dict[str, Any]:
    hard: list[dict[str, Any]] = []
    soft: list[dict[str, Any]] = []
    from_arch = set(brief.get("archetype_fields") or [])

    def src(field: str, default: str = "explicit") -> str:
        return "default" if field in from_arch else default

    if brief.get("layout_style") == "split":
        hard.append(_req("split", "eq", True, "explicit", "Split"))
    if brief.get("wireless") in ("ble", "wifi"):
        label = "Wireless (BLE)" if brief["wireless"] == "ble" else "Wi-Fi"
        hard.append(_req("wireless", "eq", brief["wireless"], src("wireless"), label))
    if brief.get("display_type"):
        hard.append(
            _req("display_type", "eq", brief["display_type"], src("display_type"), "Screen")
        )
    if brief.get("power_source") == "battery":
        hard.append(
            _req("power_source", "has", "battery", src("power_source", "implicit"), "Battery")
        )
    if brief.get("key_count"):
        n = brief["key_count"]
        hard.append(_req("key_count", "eq", n, src("key_count"), f"{n} keys"))
    if brief.get("switch_family"):
        soft.append(_req("switch_family", "eq", brief["switch_family"], "default", "Switches"))
    if brief.get("switch_type"):
        hard.append(
            _req("switch_type", "eq", brief["switch_type"], "explicit", brief["switch_type"])
        )
    for req in clarified:
        hard.append(dict(req))
    for i, req in enumerate(hard + soft, start=1):
        req["req_id"] = f"r{i}"

    counts: dict[str, int] = {
        fid: int(n) for fid, n in (brief.get("function_counts") or {}).items() if int(n) > 1
    }
    for feature in brief.get("features", []):
        if feature["kind"] == "knob":
            counts["input.rotary_encoder"] = counts["mech.knob"] = int(feature["count"])
    halves = 2 if brief.get("layout_style") == "split" else 1
    functions = []
    for fid in brief.get("functions", []):
        source = "implicit" if fid in ("compute.mcu", "mech.keycap", "power.usb_in") else "explicit"
        count = counts.get(fid, halves if fid in ("compute.mcu", "power.battery") else 1)
        functions.append(
            {"function_id": fid, "required": True, "count": max(1, count), "source": source}
        )
    norm = normalize(prompt) or prompt
    device_class = brief.get("device_class") or "unknown"
    taxonomy = [device_class]
    if brief.get("layout_style") in ("split", "unibody", "macropad"):
        taxonomy += ["keyboard", brief["layout_style"]]
    return {
        "spec_id": "sp_" + (re.sub(r"[^a-z0-9]", "", norm)[:20] or "live"),
        "prompt": prompt,
        "normalized_prompt": norm,
        "device_class": device_class,
        "taxonomy_path": taxonomy,
        "functions": functions,
        "hard_requirements": hard,
        "soft_requirements": soft,
        "leftover_text": None,
        "classifier": classifier,
        "scope": "in_scope",
        "scope_reason": None,
        "assumptions": assumptions,
        "ambiguity": {"needs_clarify": False, "missing_facets": []},
        "main_purpose": brief.get("summary", "")[:200] or None,
    }
