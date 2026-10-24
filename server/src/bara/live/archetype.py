"""Archetypes: fill what a prompt leaves unstated from what real devices of that kind look like.

The brief writer guesses gaps ("most common hobby choice"); those guesses are where a bare
"a keyboard" turned into a 48-key grid. Here every field the prompt does not state is taken
from the closest archetype in data/archetypes.json (a named open design or a common build
pattern), and the fields filled are reported so the reuse event can say where they came from.

Generic: no device names in code. A field counts as stated when the prompt itself has words
for it (STATED); the archetype never overrides those.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from bara.live.catalog_source import PartSource

# Words that mean the prompt itself set this brief field.
STATED: dict[str, str] = {
    # size words ("60%", "tkl") are not here: they pick the archetype, which then sets the keys
    "key_count": r"\b\d+\s*-?\s*keys?\b|\b\d+\s*x\s*\d+\b",
    "rows": r"\b\d+\s*x\s*\d+\b|\b\d+\s*rows?\b",
    "cols": r"\b\d+\s*x\s*\d+\b|\b\d+\s*col(umn)?s?\b",
    "thumb_keys": r"\bthumb",
    "stagger": r"\bortho|\bcolumn|\brow[- ]stagger|\bstagger",
    "switch_family": r"\bchoc\b|\bmx\b|low[- ]profile|\bcherry\b|\bgateron\b|\bkailh\b",
    "display_type": r"\boled\b|e-?paper|e-?ink|\btft\b|\blcd\b|seven[- ]segment|7[- ]seg",
    "wireless": r"\bwireless\b|\bbluetooth\b|\bble\b|wi-?fi|\bwired\b|\busb\b|\bcable",
    "power_source": r"\bbattery\b|\busb\b|\bwired\b|\bplug|\bmains\b|\bsolar\b|\bcoin cell",
    "layout_style": r"\bsplit\b|\bmacro ?pad\b|\bkeypad\b|\bunibody\b|\bone[- ]piece\b",
    "layout_preset": r"\bortho",
}
KEY_FIELDS = ("key_count", "rows", "cols", "thumb_keys", "stagger", "layout_preset")


@dataclass
class ArchetypeResult:
    archetype: dict[str, Any] | None
    considered: list[tuple[float, dict[str, Any]]]
    filled: list[str] = field(default_factory=list)

    def reason(self) -> str:
        if self.archetype is None:
            return ""
        a = self.archetype
        what = ", ".join(self.filled[:6]) or "nothing (the prompt stated it all)"
        src = a["source"].get("url") or "common build pattern"
        return f"Unstated details from {a['name']} ({src}): {what}."


@lru_cache(maxsize=4)
def load(path: Path) -> tuple[dict[str, Any], ...]:
    data = json.loads(path.read_text())
    return tuple(data["archetypes"])


def _has(text: str, phrase: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])", text) is not None


def retrieve(prompt: str, brief: dict[str, Any], archetypes: tuple[dict[str, Any], ...]):
    """Rank archetypes by the prompt's own words (and the brief's device noun)."""
    text = prompt.lower()
    device = str(brief.get("device") or "").lower()
    ranked: list[tuple[float, dict[str, Any]]] = []
    for a in archetypes:
        if any(_has(text, w) for w in a.get("excludes", [])):
            continue
        score = sum(len(w) for w in a["words"] if _has(text, w))
        score += 0.5 * sum(len(w) for w in a["words"] if w not in text and _has(device, w))
        if any(_has(text, d) or d == device for d in a.get("default_for", [])):
            score += 2.0
        if score > 0:
            ranked.append((round(score, 2), a))
    ranked.sort(key=lambda t: -t[0])
    return ranked


def _supported(source: PartSource, fid: str) -> bool:
    try:
        return bool(source.query(function=fid, limit=1))
    except Exception:  # a source that cannot answer counts as not having it
        return False


def _display_supported(source: PartSource, value: str) -> bool:
    try:
        return bool(source.query(facets={"display_type": value}, limit=1))
    except Exception:
        return False


def apply(prompt: str, brief: dict[str, Any], source: PartSource, path: Path) -> ArchetypeResult:
    ranked = retrieve(prompt, brief, load(path))
    if not ranked:
        return ArchetypeResult(None, [])
    arch = ranked[0][1]
    text = prompt.lower()
    out = brief
    filled: list[str] = []

    def stated(key: str) -> bool:
        pattern = STATED.get(key)
        return bool(pattern and re.search(pattern, text))

    defaults = arch.get("brief", {})
    keyboard_stated = any(stated(k) for k in ("key_count", "rows", "cols"))
    fields: list[str] = []
    if not keyboard_stated and any(k in defaults for k in KEY_FIELDS):
        # the archetype sets the arrangement; the model's own unstated grid guesses go
        for key in KEY_FIELDS:
            if key not in defaults and not stated(key) and out.get(key) is not None:
                out.pop(key, None)
    for key, value in defaults.items():
        if stated(key):
            continue
        if key in KEY_FIELDS and keyboard_stated:
            continue  # the prompt sized the board itself; keep its own grid
        if key == "display_type":
            options = value if isinstance(value, list) else [value]
            if out.get("display_type") and out["display_type"] in options:
                continue
            pick = next((v for v in options if _display_supported(source, v)), None)
            if pick is None or out.get("display_type") == pick:
                continue
            value = pick
        fields.append(key)
        if out.get(key) != value:
            out[key] = copy.deepcopy(value)
            filled.append(key.replace("_", " "))
    if keyboard_stated:
        for key in ("layout_preset",):
            out.pop(key, None)

    functions = list(out.get("functions") or [])
    counts: dict[str, int] = dict(out.get("function_counts") or {})
    faces: dict[str, str] = dict(out.get("faces") or {})
    stated_features = {f["kind"] for f in out.get("features", []) if f.get("count")}
    added = []
    for fn in arch.get("functions", []):
        options = fn.get("any_of") or [fn["function_id"]]
        have = next((f for f in options if f in functions), None)
        if have is None:
            have = next((f for f in options if _supported(source, f)), None)
            if have is None:
                continue
            functions.append(have)
            added.append(have.split(".")[-1].replace("_", " "))
        kind = have.split(".")[-1]
        if fn.get("count", 1) > 1 and kind not in stated_features:
            counts[have] = max(counts.get(have, 1), int(fn["count"]))
        faces[have] = fn.get("face", "top")
    if added:
        filled.append("parts: " + ", ".join(added))
    out["functions"] = functions
    out["function_counts"] = counts
    out["faces"] = faces
    out["form"] = copy.deepcopy(arch.get("form"))
    out["size_range_mm"] = copy.deepcopy(arch.get("size_range_mm"))
    out["archetype_fields"] = fields
    out["archetype"] = {
        "id": arch["id"],
        "name": arch["name"],
        "url": arch["source"].get("url"),
        "kind": arch["source"].get("kind"),
    }
    if arch.get("form"):
        filled.append(f"{arch['form']['shape'].replace('_', ' ')} form")
    return ArchetypeResult(arch, ranked[:5], filled)
