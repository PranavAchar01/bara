"""What a prompt typed over an open build asks for: a second device beside it, or a change to it.

"add a mouse to the keyboard" names a thing and relates it to what is on screen. The language
model reads it with the open build in view and decides: a device of its own (built on a new canvas
next to the first, told what it pairs with), a change to the open device (the edit path), or a
different device altogether. There is no word list here: the judgment is the model's.
"""

from __future__ import annotations

from typing import Any

from bara.live.ask import ask_json

SYSTEM = """You route one typed request made while a hardware device is open on screen.

Decide what the request asks for:
- "companion": a separate device that works alongside the open one (a mouse for a keyboard, a
  dock for a console, a remote for a lamp). It is built as its own device and stands beside the
  open one. Typical wording: add / make / connect / pair a <device> to or for the open device.
- "modify": a change to the open device itself: a part, feature, size, layout or material of it
  (add a speaker, more keys, a bigger screen, a different case colour).
- "new": a wholly different device that has no relation to the open one.

A thing that would sit INSIDE the open device's case is "modify". A thing with its own case, that
a person holds or places on the desk next to the open device, is "companion".

For "companion", write device_prompt: a complete build prompt for that new device alone, naming
what it pairs with and how, e.g. "a wireless mouse that pairs over Bluetooth with a 75% keyboard,
sized to sit beside it". Do not describe the open device's own parts. For "modify", device is the
part being added, if one is named. For "modify" and "new", device_prompt is the request unchanged."""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["companion", "modify", "new"]},
        "device": {"type": "string", "description": "short name of the new device (companion) or of the part being added (modify); empty otherwise"},
        "device_prompt": {"type": "string"},
    },
    "required": ["kind", "device", "device_prompt"],
    "additionalProperties": False,
}


async def classify(
    prompt: str, has_build: bool, build_prompt: str = "", part_names: list[str] | None = None
) -> dict[str, Any]:
    """{"kind": "new" | "companion" | "modify", "thing": str | None, "prompt": str, "note": str}.

    Without an open build, or when the model gives no usable answer, the request starts a build
    as it stands ("new"); `note` says why."""
    text = prompt.strip()
    plain = {"kind": "new", "thing": None, "prompt": text, "note": ""}
    if not has_build:
        return plain
    parts = ", ".join((part_names or [])[:40])
    question = (
        f"Open device (its original prompt): {build_prompt.strip()[:400] or 'unknown'}\n"
        f"Its parts: {parts or 'unknown'}\n\nRequest: {text[:600]}"
    )
    data, note = await ask_json(SYSTEM, question, SCHEMA, name="intent", fast=True, timeout_s=20.0, max_tokens=400, effort="low")
    if not data or data.get("kind") not in ("companion", "modify", "new"):
        return {**plain, "note": note}
    kind = data["kind"]
    device_prompt = str(data.get("device_prompt") or "").strip() or text
    if kind == "companion":
        thing = str(data.get("device") or "").strip() or None
        return {"kind": "companion", "thing": thing, "prompt": device_prompt, "note": note}
    thing = (str(data.get("device") or "").strip() or None) if kind == "modify" else None
    return {"kind": kind, "thing": thing, "prompt": text, "note": note}
