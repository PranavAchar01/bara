"""Open hardware projects (a KiCad board plus a printable shell) that already build the device,
from the scouted list in docs/shell-sources.json. The reuse stage names the closest one so a
build says which open design it stands next to instead of finding nothing in 0 ms.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

SOURCES = Path(__file__).resolve().parents[4] / "docs/shell-sources.json"
FIT_RANK = {"exact": 0, "close": 1, "weak": 2, "pcb-only": 3}
FIT_SCORE = {"exact": 1.0, "close": 0.8, "weak": 0.5, "pcb-only": 0.3}
MIN_OVERLAP = 0.66  # share of the listed device's words the request must contain
STOP = {"a", "an", "the", "with", "and", "for", "of", "my", "style", "large"}


def _words(text: str) -> set[str]:
    out = set()
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        if w in STOP:
            continue
        out.add(w[:-1] if len(w) > 3 and w.endswith("s") else w)
    return out


@lru_cache(maxsize=1)
def _entries() -> list[dict[str, Any]]:
    try:
        return [e for e in json.loads(SOURCES.read_text()) if e.get("candidates")]
    except (OSError, ValueError):
        return []


def closest(request: str, device: str = "") -> tuple[str, list[dict[str, Any]]]:
    """(the listed device that matched, its candidates best fit first); ("", []) when none."""
    asked = _words(request) | _words(device)
    best: tuple[float, int, dict[str, Any]] | None = None
    for entry in _entries():
        listed = _words(entry["device"])
        if not listed:
            continue
        overlap = len(listed & asked) / len(listed)
        # the fuller match wins a tie ("game boy" over "raspberry pi game boy")
        key = (overlap, -len(listed), entry)
        if overlap >= MIN_OVERLAP and (best is None or key[:2] > best[:2]):
            best = key
    if best is None:
        return "", []
    entry = best[2]
    cands = sorted(entry["candidates"], key=lambda c: FIT_RANK.get(c.get("fit", ""), 9))
    return entry["device"], cands


def rows(request: str, device: str = "", limit: int = 3) -> list[dict[str, Any]]:
    """reuse.decided `considered` rows for the matching open designs."""
    _, cands = closest(request, device)
    out = []
    for c in cands[:limit]:
        repo = str(c.get("repo", ""))
        out.append(
            {
                "design_id": repo,
                "name": f"{repo.rstrip('/').split('/')[-1]} ({c.get('licence', '?')}, "
                f"{c.get('fit', '?')} fit, open KiCad + shell)"[:80],
                "tier": "compose",
                "score": FIT_SCORE.get(c.get("fit", ""), 0.2),
                "unmet": [],
            }
        )
    return out
