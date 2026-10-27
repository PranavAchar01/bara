"""Where every footprint on a board came from, under which licence, and a CycloneDX HBOM.

Tangible only builds from published libraries. This turns that rule into a gate: each
footprint's library is resolved through the board's fp-lib-table to a source in the policy
file, and a footprint whose source is unknown, or whose licence the policy does not allow,
is flagged."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

_FP = re.compile(r'^\s*\(footprint\s+"([^"]+)"', re.M)
_PROP = re.compile(r'\(property\s+"(Reference|Value|LCSC Part)"\s+"([^"]*)"')
_LIB = re.compile(r'\(lib\s+\(name\s+"([^"]+)"\)\s*\(type\s+"[^"]*"\)\s*\(uri\s+"([^"]+)"\)')


def footprints(pcb: Path) -> list[dict[str, str]]:
    text = pcb.read_text()
    starts = [m.start() for m in _FP.finditer(text)] + [len(text)]
    out = []
    for a, b in zip(starts, starts[1:], strict=False):
        chunk = text[a:b]
        lib_id = _FP.match(chunk)
        props = dict(_PROP.findall(chunk))
        lib, _, name = (lib_id.group(1) if lib_id else "").partition(":")
        out.append(
            {
                "ref": props.get("Reference", "?"),
                "value": props.get("Value", ""),
                "library": lib,
                "footprint": name,
                "lcsc": props.get("LCSC Part", ""),
            }
        )
    return out


def lib_table(board: Path) -> dict[str, str]:
    table = board / "fp-lib-table"
    return dict(_LIB.findall(table.read_text())) if table.is_file() else {}


def _source(uri: str, policy: dict[str, Any]) -> str | None:
    for key, src in policy["sources"].items():
        if any(m in uri for m in src["match"]):
            return key
    return None


def check(board: Path, policy: dict[str, Any]) -> dict[str, Any]:
    table = lib_table(board)
    allowed = set(policy["allowed_licences"])
    review = set(policy.get("review_licences") or [])
    parts = []
    for fp in footprints(board / "main.kicad_pcb"):
        uri = table.get(fp["library"], "")
        key = _source(uri, policy) if uri else None
        src = policy["sources"].get(key or "", {})
        lic = src.get("licence", "unknown")
        verdict = "ok" if lic in allowed else "review" if lic in review else "blocked"
        parts.append({**fp, "source": key or "unknown", "licence": lic,
                      "url": src.get("url", ""), "verdict": verdict})  # fmt: skip
    count = {v: sum(1 for p in parts if p["verdict"] == v) for v in ("ok", "review", "blocked")}
    return {"parts": parts, **count}


def cyclonedx(name: str, parts: list[dict[str, Any]]) -> dict[str, Any]:
    """CycloneDX 1.5 hardware bill of materials: one `device` component per footprint."""
    comps = []
    for p in parts:
        c: dict[str, Any] = {
            "type": "device",
            "bom-ref": f"{name}:{p['ref']}",
            "name": p["footprint"] or p["ref"],
            "description": f"{p['ref']} {p['value']}".strip(),
            "group": p["library"],
            "properties": [
                {"name": "tangible:source", "value": p["source"]},
                {"name": "tangible:verdict", "value": p["verdict"]},
            ],
        }
        if p["licence"] not in ("unknown", "NOASSERTION"):
            c["licenses"] = [{"expression": p["licence"]}]
        if p["url"]:
            c["externalReferences"] = [{"type": "distribution", "url": p["url"]}]
        if p["lcsc"]:
            c["properties"].append({"name": "tangible:lcsc", "value": p["lcsc"]})
        comps.append(c)
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, 'tangible:' + name)}",
        "version": 1,
        "metadata": {"component": {"type": "device", "name": name, "bom-ref": name}},
        "components": comps,
    }


def load_policy(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())
