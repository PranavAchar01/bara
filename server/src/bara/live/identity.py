"""Identity judge: does the built scene read as the requested device?

After the case and board are built the hero view is rendered and a vision model is asked what
it sees, then whether that is the requested product, given a text description of the reference
silhouette. A failing verdict is turned into a critique the form stage uses for one repair pass.
The judge sees the device class and the request's words only: no brand or product names.
"""

from __future__ import annotations

import json
import re
from typing import Any

from bara.live.ask import ask_json

SYSTEM = """You are a strict product-design reviewer. You see one rendered image of a generated
3D device (a plain shell with components, rendered without textures, decoration or branding)
and a request. Decide whether a person shown only this image would say it is the kind of device
that was requested.

First describe what you literally see (shape, proportions, openings, what sits on top). Then
judge against the device class and the person's own words, nothing else: never compare it with
a named brand or a specific commercial product, and never ask for one. The shell colour, its
material and the render's lighting are placeholders chosen later; never object to them. The
plan size and thickness in millimetres are given as measured from the model: trust those numbers
over your impression of the perspective (the camera looks down at an angle, which shortens the
depth). A box or slab with holes is not a product unless that kind of product is one. Mark
reads_as_device false only when the overall shape, proportions or the layout of controls would
not be recognised as that kind of device, and say precisely what to change in the form
(outline, proportions, thickness, where controls sit)."""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["sees", "reads_as_device", "confidence", "mismatches", "form_fixes"],
    "properties": {
        "sees": {"type": "string"},
        "reads_as_device": {"type": "boolean"},
        "confidence": {"type": "number"},
        "mismatches": {"type": "array", "items": {"type": "string"}},
        "form_fixes": {"type": "array", "items": {"type": "string"}},
    },
}


async def judge(
    request: str,
    description: str,
    reference: dict[str, Any],
    png: bytes,
    photos: list[bytes] | None = None,
    device_class: str = "",
    measured: tuple[float, float, float] | None = None,
    concept: Any = None,
) -> tuple[dict[str, Any] | None, str]:
    """The verdict on the render. The device is judged against its class and the request's
    own words (plus the build's device concept when one exists), never against brand names."""
    kinds = ", ".join(str(k) for k in (reference.get("kinds") or []) if k)
    size = ""
    if measured:
        w, d, t = measured
        shape = "portrait" if d > 1.05 * w else "landscape" if w > 1.05 * d else "square"
        size = (
            f"Measured model: {w:.0f} mm wide x {d:.0f} mm deep in plan ({shape}), "
            f"{t:.0f} mm thick.\n"
        )
    about = concept if isinstance(concept, str) else json.dumps(concept)[:1500] if concept else ""
    text = (
        f"Requested device (the person's words): {request}\n"
        + (f"Device class: {device_class}\n" if device_class else "")
        + (f"Kinds of product this class covers: {kinds}\n" if kinds else "")
        + (f"Device concept: {about}\n" if about else "")
        + f"Intended silhouette: {description}\n"
        + size
        + "The last image is the generated device from the front, above and to the left."
        + (
            f" The {len(photos)} image(s) before it are web photos of devices of this kind, "
            "for visual reference only (shape and layout, not brand or colour)."
            if photos
            else ""
        )
    )
    return await ask_json(
        SYSTEM,
        text,
        SCHEMA,
        name="identity",
        timeout_s=75,
        max_tokens=1500,
        images=[*(photos or []), png],
    )


def objection(verdict: dict[str, Any] | None) -> frozenset[str]:
    """The content words of what the reviewer objected to, to tell whether a redraw changed it."""
    if not verdict:
        return frozenset()
    text = " ".join([*verdict.get("mismatches", []), *verdict.get("form_fixes", [])]).lower()
    return frozenset(w for w in re.findall(r"[a-z]{4,}", text) if w not in _STOP)


_STOP = frozenset(
    "that this with from into than they should would make more less like looks read reads "
    "does device product form shape their there have which when where also only very".split()
)


def same_objection(a: dict[str, Any] | None, b: dict[str, Any] | None) -> bool:
    """True when two failing verdicts object to mostly the same things (Jaccard >= 0.5)."""
    oa, ob = objection(a), objection(b)
    if not oa or not ob:
        return False
    return len(oa & ob) / len(oa | ob) >= 0.5


def critique(verdict: dict[str, Any], measured: tuple[float, float, float] | None = None) -> str:
    lines = [f"A reviewer looking at the render saw: {verdict['sees']}"]
    lines += [f"Mismatch: {m}" for m in verdict.get("mismatches", [])]
    lines += [f"Fix: {m}" for m in verdict.get("form_fixes", [])]
    if measured:  # the reviewer judged a perspective view: the redraw works from the numbers
        lines.append(
            f"The built case measures {measured[0]:.0f} mm wide x {measured[1]:.0f} mm deep x "
            f"{measured[2]:.0f} mm thick; change what the reviewer objected to, not the colour."
        )
    return "\n".join(lines)
