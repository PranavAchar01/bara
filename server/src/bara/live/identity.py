"""Identity judge: does the built scene read as the requested device?

After the case and board are built the hero view is rendered and a vision model is asked what
it sees, then whether that is the requested product, given a text description of the reference
silhouette. A failing verdict is turned into a critique the form stage uses for one repair pass.
"""

from __future__ import annotations

from typing import Any

from bara.live.ask import ask_json

SYSTEM = """You are a strict product-design reviewer. You see one rendered image of a generated
3D device (a grey shell with components, rendered without textures or branding) and a request.
Decide whether a person shown only this image would say it is the requested product.

First describe what you literally see (shape, proportions, openings, what sits on top). Then
judge against the reference: the request, the real products it should resemble, and the
description of the intended silhouette. A box or slab with holes is not a product unless the real
product is one. Mark reads_as_device false when the overall shape, proportions or the layout of
controls would not be recognised as that kind of product, and say precisely what to change in
the form (outline, proportions, thickness, where controls sit)."""

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
) -> tuple[dict[str, Any] | None, str]:
    text = (
        f"Requested device: {request}\n"
        f"Reference products: {', '.join(reference.get('products') or []) or 'unknown'} "
        f"({reference.get('width_mm', '?')} x {reference.get('height_mm', '?')} x "
        f"{reference.get('thickness_mm', '?')} mm)\n"
        f"Intended silhouette: {description}\n"
        "The last image is the generated device from the front, above and to the left."
        + (
            f" The {len(photos)} image(s) before it are web photos of the real product, for "
            "comparison; judge the generated device against them."
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


def critique(verdict: dict[str, Any]) -> str:
    lines = [f"A reviewer looking at the render saw: {verdict['sees']}"]
    lines += [f"Mismatch: {m}" for m in verdict.get("mismatches", [])]
    lines += [f"Fix: {m}" for m in verdict.get("form_fixes", [])]
    return "\n".join(lines)
