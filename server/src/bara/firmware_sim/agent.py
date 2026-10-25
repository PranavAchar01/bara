"""The model's part of the simulator: name the inputs and outputs in plain words, choose which
matter, and turn a chat message ("make the LED blink faster") into a firmware change."""

from __future__ import annotations

import re
from typing import Any

from bara.live.llm_json import call_json


def _closed(schema: Any) -> Any:
    """Structured output wants every object closed (additionalProperties false)."""
    if isinstance(schema, dict):
        out = {k: _closed(v) for k, v in schema.items()}
        if out.get("type") == "object":
            out["additionalProperties"] = False
        return out
    if isinstance(schema, list):
        return [_closed(v) for v in schema]
    return schema


LABEL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "device_name": {"type": "string"},
        "inputs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "label": {"type": "string"},
                    "matters": {"type": "boolean"},
                },
                "required": ["id", "label", "matters"],
            },
        },
        "outputs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "label": {"type": "string"}},
                "required": ["id", "label"],
            },
        },
        "summary": {"type": "string"},
    },
    "required": ["device_name", "inputs", "outputs", "summary"],
}
LABEL_SCHEMA = _closed(LABEL_SCHEMA)

LABEL_SYSTEM = (
    "You label the controls of a hardware device for a person trying it in a simulator. "
    "For every input give a short plain label (2 to 4 words, no part numbers, no brand names, "
    "e.g. 'A button', 'Joystick X', 'Power switch', 'Volume knob'), and say whether it matters "
    "to try (false only for duplicates nobody would test one by one). Name the outputs the same "
    "way. device_name is 1 to 3 plain words. summary is one sentence on what to try first. "
    "A key that already has a legend keeps it ('Key Q' becomes 'Q key'). "
    "Keep every id exactly as given."
)


def _parts_brief(build: dict[str, Any]) -> list[str]:
    out = []
    for p in build.get("parts") or []:
        card = p.get("card") or {}
        out.append(
            f"- {p.get('instance_id')}: {card.get('display_name') or p.get('part_id')} "
            f"({card.get('function') or p.get('function') or ''}) x{p.get('quantity') or 1}"
            + (f", role: {p.get('label')}" if p.get("label") else "")
        )
    return out


def _clean(s: str, n: int = 28) -> str:
    return re.sub(r"[^ -~]", "", s).strip()[:n]


async def ai_labels(
    build: dict[str, Any], io: dict[str, Any], cerebras_model: str, anthropic_model: str
) -> tuple[dict[str, Any] | None, list[str]]:
    """Labels from the model, or None with notes when no model answered."""
    prompt = "\n".join(
        [
            f"Device prompt: {build.get('prompt') or ''}",
            "Parts:",
            *_parts_brief(build),
            "Inputs (id: current label, kind):",
            *[f"- {i['id']}: {i['label']}, {i['kind']}" for i in io["inputs"]],
            "Outputs (id: current label, kind):",
            *[f"- {o['id']}: {o['label']}, {o['kind']}" for o in io["outputs"]],
        ]
    )
    res, notes = await call_json(
        LABEL_SYSTEM,
        prompt,
        LABEL_SCHEMA,
        name="sim_labels",
        cerebras_model=cerebras_model,
        anthropic_model=anthropic_model,
        timeout_s=25.0,
    )
    if res is None:
        return None, notes
    data = res.data
    ids_in = {i["id"] for i in io["inputs"]}
    ids_out = {o["id"] for o in io["outputs"]}
    return {
        "device_name": _clean(str(data.get("device_name") or "")),
        "inputs": {
            str(x["id"]): {
                "label": _clean(str(x["label"])),
                "matters": bool(x.get("matters", True)),
            }
            for x in data.get("inputs") or []
            if isinstance(x, dict) and x.get("id") in ids_in and str(x.get("label") or "").strip()
        },
        "outputs": {
            str(x["id"]): _clean(str(x["label"]), 40)
            for x in data.get("outputs") or []
            if isinstance(x, dict) and x.get("id") in ids_out and str(x.get("label") or "").strip()
        },
        "summary": _clean(str(data.get("summary") or ""), 200),
        "provider": res.provider,
        "model": res.model,
    }, notes


def apply_labels(io: dict[str, Any], labels: dict[str, Any]) -> dict[str, Any]:
    for i in io["inputs"]:
        lab = labels["inputs"].get(i["id"])
        if lab:
            i["label"], i["matters"] = lab["label"], lab["matters"]
    for o in io["outputs"]:
        if labels["outputs"].get(o["id"]):
            o["label"] = labels["outputs"][o["id"]]
    if labels.get("device_name"):
        io["device"] = {**(io.get("device") or {}), "name": labels["device_name"]}
    io["labels_by"] = "ai"
    io["labels_model"] = labels.get("provider")
    io["try_first"] = labels.get("summary") or ""
    return io


# ---- chat ------------------------------------------------------------------------------------
CHAT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "kind": {"type": "string", "enum": ["change", "question"]},
        "blink_ms": {"type": "integer"},
        "debounce_ms": {"type": "integer"},
        "tone_ms": {"type": "integer"},
        "axis_deadzone": {"type": "integer"},
        "led_on_press": {"type": "boolean"},
        "labels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "label": {"type": "string"}},
                "required": ["id", "label"],
            },
        },
        "surface_ops": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "op": {"type": "string", "enum": ["show", "hide", "rename", "lead", "set"]},
                    "input_id": {"type": "string"},
                    "label": {"type": "string"},
                    "value": {"type": "number"},
                },
                "required": ["op", "input_id", "label", "value"],
            },
        },
    },
    "required": ["reply", "kind", "surface_ops"],
}
CHAT_SCHEMA = _closed(CHAT_SCHEMA)

CHAT_SYSTEM = (
    "You are the build agent inside a firmware simulator. The firmware has these settings: "
    "blink_ms (status LED half period while idle), debounce_ms (how long a contact must be "
    "stable), tone_ms (click sound length on each press), axis_deadzone (joystick dead zone, "
    "0 to 64), led_on_press (LED stays lit while any input is held), and a label per input. "
    "If the person asks for a change, set kind to 'change', include only the settings that "
    "change, and say in one or two plain sentences what will happen. If it is a question, set "
    "kind to 'question' and answer it in reply. Never invent settings that are not listed. "
    "The play surface shows one control per real input. A request to change the surface goes in "
    "surface_ops: show (bring a hidden input back, for example 'add a slider for battery level' "
    "when an input measures it), hide, rename (label in standardized technical wording), lead "
    "(make it the main control), set (value is a sensor's physical value in its unit). Use only "
    "input ids from the list. If the build has no part that provides what was asked, return no "
    "op and say in reply which part is missing. Leave label empty and value 0 when unused."
)


def rule_patch(message: str, cfg: dict[str, Any], io: dict[str, Any]) -> dict[str, Any]:
    """A deterministic reading of the common asks, used when no model is reachable."""
    m = message.lower()
    patch: dict[str, Any] = {}
    num = re.search(r"(\d{1,5})\s*(ms|millisecond)", m)
    hz = re.search(r"(\d+(?:\.\d+)?)\s*(hz|times a second)", m)
    if "blink" in m or "flash" in m:
        if num:
            patch["blink_ms"] = int(num.group(1))
        elif hz:
            patch["blink_ms"] = max(10, int(500 / float(hz.group(1))))
        elif "faster" in m or "quicker" in m:
            patch["blink_ms"] = max(20, cfg["blink_ms"] // 2)
        elif "slower" in m:
            patch["blink_ms"] = min(10_000, cfg["blink_ms"] * 2)
        if "while" in m and ("press" in m or "hold" in m):
            patch["led_on_press"] = False
    if "debounce" in m and num:
        patch["debounce_ms"] = int(num.group(1))
    if ("beep" in m or "click" in m or "tone" in m) and num:
        patch["tone_ms"] = int(num.group(1))
    if re.search(r"(mute|no (beep|sound|click)|silence)", m):
        patch["tone_ms"] = 1
    ren = re.search(r"rename (.+?) to (.+)$", message, re.I)
    if ren:
        old, new = ren.group(1).strip().lower(), ren.group(2).strip()
        for i in io["inputs"]:
            if i["label"].lower() == old:
                patch.setdefault("labels", {})[i["id"]] = new[:24]
    return patch


async def chat_patch(
    message: str,
    cfg: dict[str, Any],
    io: dict[str, Any],
    cerebras_model: str,
    anthropic_model: str,
    scene: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str, str, str]:
    """(patch, reply, kind, by). Falls back to the rule reading when no model answers. `scene`
    is the combined device this one stands in: what the simulation tests across the devices."""
    combined = (
        [
            f"Combined device: {scene['title']} ({', '.join(scene.get('devices') or [])}). "
            f"This firmware runs the first one; the simulation tests: {scene.get('testing')}",
            "Cross-device behaviour: " + "; ".join(scene.get("flows") or []),
        ]
        if scene
        else []
    )
    prompt = "\n".join(
        [
            f"Device: {(io.get('device') or {}).get('name')}",
            *combined,
            "Current settings: "
            + ", ".join(
                f"{k}={cfg[k]}"
                for k in ("blink_ms", "debounce_ms", "tone_ms", "axis_deadzone", "led_on_press")
            ),
            "Inputs: "
            + "; ".join(
                f"{i['id']} = {i['label']}"
                + (f" ({i['min']} to {i['max']} {i['unit']})" if i["kind"] == "sensor" else "")
                for i in io["inputs"][:60]
            ),
            f"Person: {message}",
        ]
    )
    res, notes = await call_json(
        CHAT_SYSTEM,
        prompt,
        CHAT_SCHEMA,
        name="sim_chat",
        cerebras_model=cerebras_model,
        anthropic_model=anthropic_model,
        timeout_s=25.0,
    )
    if res is None:
        patch = rule_patch(message, cfg, io)
        reply = (
            "Changing " + ", ".join(f"{k} to {v}" for k, v in patch.items() if k != "labels") + "."
            if patch
            else "No model is reachable right now, and I could not read a setting change "
            "from that. Try 'make the LED blink every 200 ms'."
        )
        return patch, reply, "change" if patch else "question", "rules (" + "; ".join(notes) + ")"
    d = res.data
    patch = {
        k: d[k]
        for k in ("blink_ms", "debounce_ms", "tone_ms", "axis_deadzone", "led_on_press")
        if k in d and d[k] is not None and d[k] != cfg.get(k)
    }
    ids = {i["id"] for i in io["inputs"]}
    labels = {
        str(x["id"]): _clean(str(x["label"]), 24)
        for x in d.get("labels") or []
        if isinstance(x, dict) and x.get("id") in ids
    }
    if labels:
        patch["labels"] = labels
    ops = surface_ops(d.get("surface_ops"), io)
    if ops:
        patch["surface_ops"] = ops
    return patch, str(d.get("reply") or ""), str(d.get("kind") or "change"), res.provider


def surface_ops(raw: Any, io: dict[str, Any]) -> list[dict[str, Any]]:
    """The model's surface requests, kept only when they name a real input; a sensor value is
    held inside the part's own range."""
    by_id = {i["id"]: i for i in io["inputs"]}
    out: list[dict[str, Any]] = []
    for x in raw or []:
        if not isinstance(x, dict) or x.get("input_id") not in by_id:
            continue
        i = by_id[x["input_id"]]
        op = x.get("op")
        if op in ("show", "hide", "lead"):
            out.append({"op": op, "input_id": i["id"]})
        elif op == "rename" and _clean(str(x.get("label") or ""), 32):
            out.append({"op": op, "input_id": i["id"], "label": _clean(str(x["label"]), 32)})
        elif op == "set" and i["kind"] == "sensor":
            v = max(float(i["min"]), min(float(i["max"]), float(x.get("value") or 0)))
            out.append({"op": op, "input_id": i["id"], "value": v})
    return out
