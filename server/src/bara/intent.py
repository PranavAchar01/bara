"""What a prompt typed over an open build asks for: a second device beside it, or a change to it.

"add a mouse to the keyboard" names a thing and relates it to what is on screen. The language
model reads it with the open build in view and decides: a device of its own (built on a new canvas
next to the first, told what it pairs with), a change to the open device (the edit path), or a
different device altogether. The judgment is the model's; when no model answers (no key, a
timeout) the sentence's shape decides instead (`read_shape`): a thing set beside the build, or a
named device (a mouse, a numpad) added, connected or matched to it, is a device of its own.

A companion inherits the open device's look: the caller sends `parent_style` (its colours, case
material and finish, connector, what it is) and the new device's prompt carries it, so a mouse
made for a keyboard comes out in the keyboard's colours and plugs in the same way.
"""

from __future__ import annotations

import re
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
        "device": {
            "type": "string",
            "description": "short name of the new device (companion) or of the part being added (modify); empty otherwise",
        },
        "device_prompt": {"type": "string"},
    },
    "required": ["kind", "device", "device_prompt"],
    "additionalProperties": False,
}

# Things with a case of their own that stand beside another device, by the kind a shared canvas
# lays them out as. Only the no-model fallback and the layout kind read these.
DEVICE_KINDS: dict[str, tuple[str, ...]] = {
    "keyboard": ("keyboard", "numpad", "number pad", "keypad", "macropad", "macro pad"),
    "mouse": ("mouse", "trackball", "trackpad", "touchpad"),
    "handheld": (
        "handheld",
        "gameboy",
        "game boy",
        "console",
        "controller",
        "gamepad",
        "joystick",
        "remote",
    ),
    "display": ("monitor", "desktop display", "status display"),
    "dock": ("dock", "stand", "charger", "charging pad", "hub"),
    "audio": ("headphones", "headset", "earbuds"),
    "board": ("dev board", "board"),
}
KIND_OF: dict[str, str] = {word: kind for kind, words in DEVICE_KINDS.items() for word in words}

_VERB = (
    r"(?:add|connect|pair|attach|hook up|plug in|plug|make|build|give|design|create|put|want|need)"
)
_BESIDE = (
    "to go with",
    "that goes with",
    "that pairs with",
    "paired with",
    "next to",
    "beside",
    "alongside",
    "that matches",
    "to match",
)
_LINKS = (*_BESIDE, "for", "to", "with", "on", "onto", "in")
_WANT = r"(?:i (?:want|need|would like) to )?"
_ARTICLES = r"(?:(?:an?|another|matching|some|new|second)\s+)*"
_REF = r"(?:the|this|my|it|that|our)\b"
_SHAPE = re.compile(
    rf"^{_WANT}(?:{_VERB}\s+)?(?:(?:me|us)\s+)?{_ARTICLES}"
    r"(?P<thing>[a-z0-9-]+(?:\s+[a-z0-9-]+){0,3}?)"
    rf"(?:\s+(?P<link>{'|'.join(re.escape(x) for x in _LINKS)})\s+{_REF}.*)?$"
)
# "connect this keyboard to a mouse": the open device first, the new one after the link
_REVERSE = re.compile(
    rf"^{_WANT}{_VERB}\s+{_REF}(?:\s+[a-z0-9-]+){{0,3}}?\s+(?:to|with|and)\s+{_ARTICLES}"
    r"(?P<thing>[a-z0-9-]+(?:\s+[a-z0-9-]+){0,3})$"
)


def _words(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s-]", " ", text.lower())).strip()


def device_kind(text: str) -> str | None:
    """The kind a device is laid out as ("keyboard", "mouse", "handheld", ...), from its name: the
    device word before any "for / to / with" ("a wireless mouse for a keyboard" is a mouse)."""
    head = (
        re.split(r" (?:for|to|with|beside|next to|that|alongside) ", f" {_words(text)} ")[0] + " "
    )
    best: tuple[int, int, str] | None = None
    for word, kind in KIND_OF.items():
        for form in (word, word + "s", word + "es"):
            at = head.rfind(f" {form} ")
            if at >= 0 and (best is None or (at, len(word)) > best[:2]):
                best = (at, len(word), kind)
    return best[2] if best else None


def read_shape(text: str) -> dict[str, Any] | None:
    """What a line asks for by its shape alone, for when no model reads it.

    {"kind": "companion" | "modify", "thing": str}, or None when it relates nothing to the open
    device. "add a mouse to this keyboard", "connect a mouse", "make a matching mouse" and "a
    numpad beside it" are devices of their own; "add a knob to it" is a part for this one."""
    t = re.sub(r"^(?:(?:please|can you|could you|now|and|also|then|ok|okay)\s+)+", "", _words(text))
    rev = _REVERSE.match(t)
    if rev and device_kind(rev.group("thing")):
        return {"kind": "companion", "thing": rev.group("thing").strip()}
    m = _SHAPE.match(t)
    if not m:
        return None
    thing = m.group("thing").strip()
    link = m.group("link")
    matched = re.search(r"\b(?:matching|another|second)\b", t) is not None
    verb = re.match(rf"^{_WANT}{_VERB}\b", t) is not None
    if re.match(_REF, thing):
        return None  # "connect this keyboard to the wifi" is about the open device itself
    if link in _BESIDE or (device_kind(thing) and (verb or link or matched)):
        return {"kind": "companion", "thing": thing}
    if link:
        return {"kind": "modify", "thing": thing}
    return None


def styled_prompt(prompt: str, style: dict[str, Any] | None) -> str:
    """The companion's build prompt with the open device's look and the pairing spelled out."""
    if not style:
        return prompt
    parent = str(style.get("device") or "").strip() or "open device"
    bits: list[str] = []
    if "pair" not in prompt.lower():
        bits.append(f"it pairs with the {parent} as a matching set")
    palette = style.get("palette") if isinstance(style.get("palette"), dict) else {}
    colours = [
        f"{role} {v}"
        for role, v in palette.items()
        if isinstance(v, str) and re.fullmatch(r"#[0-9a-fA-F]{3,8}", v)
    ]
    if colours:
        bits.append(f"case colours the same as the {parent} ({', '.join(colours[:5])})")
    material = " ".join(str(style.get(k) or "").strip() for k in ("finish", "material")).strip()
    if material:
        bits.append(f"a {material} case like the {parent}")
    connector = str(style.get("connector") or "").strip()
    if connector:
        bits.append(f"{connector} like the {parent}")
    return f"{prompt.rstrip('. ')}; {'; '.join(bits)}." if bits else prompt


async def classify(
    prompt: str,
    has_build: bool,
    build_prompt: str = "",
    part_names: list[str] | None = None,
    parent_style: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """{"kind": "new" | "companion" | "modify", "thing": str | None, "prompt": str, "note": str,
    "device_kind": str | None}.

    Without an open build the request starts a build as it stands ("new"). When the model gives no
    usable answer the sentence's shape decides (read_shape), else it is "new"; `note` says why. A
    companion's prompt carries `parent_style`; `device_kind` is the kind it is laid out as."""
    text = prompt.strip()
    plain: dict[str, Any] = {
        "kind": "new",
        "thing": None,
        "prompt": text,
        "note": "",
        "device_kind": None,
    }
    if not has_build:
        return plain
    parent = (
        str((parent_style or {}).get("device") or "").strip()
        or build_prompt.strip()[:80]
        or "open device"
    )

    def companion(thing: str | None, device_prompt: str, note: str) -> dict[str, Any]:
        return {
            "kind": "companion",
            "thing": thing,
            "prompt": styled_prompt(device_prompt, parent_style),
            "note": note,
            "device_kind": device_kind(thing or "") or device_kind(device_prompt),
        }

    parts = ", ".join((part_names or [])[:40])
    question = (
        f"Open device (its original prompt): {build_prompt.strip()[:400] or 'unknown'}\n"
        f"Its parts: {parts or 'unknown'}\n\nRequest: {text[:600]}"
    )
    data, note = await ask_json(
        SYSTEM,
        question,
        SCHEMA,
        name="intent",
        fast=True,
        timeout_s=20.0,
        max_tokens=400,
        effort="low",
    )
    if not data or data.get("kind") not in ("companion", "modify", "new"):
        shape = read_shape(text)
        if shape and shape["kind"] == "companion":
            return companion(
                shape["thing"], f"a {shape['thing']} that pairs with the {parent}", note
            )
        if shape:
            return {**plain, "kind": "modify", "thing": shape["thing"], "note": note}
        return {**plain, "note": note}
    kind = data["kind"]
    device_prompt = str(data.get("device_prompt") or "").strip() or text
    if kind == "companion":
        return companion(str(data.get("device") or "").strip() or None, device_prompt, note)
    thing = (str(data.get("device") or "").strip() or None) if kind == "modify" else None
    return {**plain, "kind": kind, "thing": thing, "note": note}
