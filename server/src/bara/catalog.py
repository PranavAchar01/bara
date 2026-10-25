"""Catalog loaded as data at startup: parts, part cards, designs, vocab and facets.

Sources, in order of precedence:
- spec/fixtures/rest/*.json (full Part for nice_nano, the Corne design, vocab, facets)
- PartCards and assets found anywhere in the stream fixtures
- server/data/catalog/*_overlay.json (hand-authored functions/interfaces/designs)

Nothing here names a device: every id comes from the data files.
"""

from __future__ import annotations

import copy
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bara import naming

log = logging.getLogger(__name__)

# Stream fixtures in the order their parts are added to the catalog.
FIXTURE_ORDER = [
    "exact_keyboard",
    "compose_wireless_split_oled",
    "failed_critical_missing",
    "clarify_vague_gadget",
    "edit_swap_switches",
    "edit_remove_part",
    "edit_rejected_choc",
    "resume_gap",
]


def _read(path: Path) -> Any:
    return json.loads(path.read_text())


def _walk(node: Any, visit) -> None:
    if isinstance(node, dict):
        visit(node)
        for value in node.values():
            _walk(value, visit)
    elif isinstance(node, list):
        for item in node:
            _walk(item, visit)


def _is_card(node: dict[str, Any]) -> bool:
    return (
        "part_id" in node
        and "display_name" in node
        and "kind" in node
        and "interfaces" not in node
        and "instance_id" not in node
    )


@dataclass
class Catalog:
    parts: dict[str, dict[str, Any]] = field(default_factory=dict)
    cards: dict[str, dict[str, Any]] = field(default_factory=dict)
    designs: dict[str, dict[str, Any]] = field(default_factory=dict)
    design_cards: dict[str, dict[str, Any]] = field(default_factory=dict)
    vocab: dict[str, Any] = field(default_factory=dict)
    facets: dict[str, Any] = field(default_factory=dict)
    fixtures: dict[str, dict[str, Any]] = field(default_factory=dict)
    rest_fixtures: dict[str, dict[str, Any]] = field(default_factory=dict)

    # ---- lookups -------------------------------------------------------
    def part(self, part_id: str) -> dict[str, Any] | None:
        return self.parts.get(part_id)

    def card(self, part_id: str) -> dict[str, Any] | None:
        return self.cards.get(part_id)

    def interfaces(self, part_id: str) -> list[dict[str, Any]]:
        part = self.parts.get(part_id)
        return list(part.get("interfaces", [])) if part else []

    def interface(self, part_id: str, interface_id: str) -> dict[str, Any] | None:
        for iface in self.interfaces(part_id):
            if iface.get("id") == interface_id:
                return iface
        return None

    def primary_function(self, part_id: str) -> str | None:
        card = self.cards.get(part_id)
        if card and card.get("primary_function"):
            return card["primary_function"]
        part = self.parts.get(part_id)
        if part:
            for fn in part.get("functions", []):
                if fn.get("primary"):
                    return fn["function_id"]
            if part.get("functions"):
                return part["functions"][0]["function_id"]
        return None

    def facet_label(self, facet: str, value: Any) -> str:
        for entry in self.facets.get("facets", []):
            if entry.get("facet") == facet:
                for v in entry.get("values", []):
                    if v.get("value") == value:
                        return str(v.get("label", value))
        return str(value)

    def facet_keys(self) -> list[str]:
        return [f["facet"] for f in self.facets.get("facets", [])]

    def function_ids(self) -> list[str]:
        return [f["id"] for f in self.vocab.get("functions", [])]

    def device_classes(self) -> list[str]:
        return [d["id"] for d in self.vocab.get("device_classes", [])]

    def stage_budget(self, stage: str) -> int:
        for s in self.vocab.get("stages", []):
            if s.get("id") == stage:
                return int(s.get("budget_ms", 50))
        return 50

    def check_severity(self, rule_id: str) -> str:
        for r in self.vocab.get("check_rules", []):
            if r.get("id") == rule_id:
                return r.get("severity", "error")
        return "error"


def _part_record(
    part_id: str,
    card: dict[str, Any],
    assets: list[dict[str, Any]],
    overlay: dict[str, Any] | None,
) -> dict[str, Any]:
    functions = (overlay or {}).get("functions") or (
        [{"function_id": card["primary_function"], "primary": True}]
        if card.get("primary_function")
        else []
    )
    record: dict[str, Any] = {
        "part_id": part_id,
        "kind": card.get("kind", "unknown"),
        "display_name": card["display_name"],
        "summary": card.get("summary"),
        "functions": copy.deepcopy(functions),
        "interfaces": copy.deepcopy((overlay or {}).get("interfaces", [])),
        "assets": copy.deepcopy(assets),
        "licence": {
            "spdx": card.get("licence_spdx", "NOASSERTION"),
            "commercial_ok": card.get("commercial_ok", "unknown"),
        },
        "provenance": {
            "route": "fixture_card" if overlay is None else "fixture_card+overlay",
            "verified": card.get("verified", "none"),
        },
        "facets": copy.deepcopy((overlay or {}).get("facets", {})),
        "status": "active",
    }
    if card.get("source_url"):
        record["provenance"]["source_url"] = card["source_url"]
    return record


def load_catalog(spec_dir: Path, catalog_dir: Path) -> Catalog:
    cat = Catalog()
    fixtures_dir = spec_dir / "fixtures"

    for path in sorted((fixtures_dir / "rest").glob("*.json")):
        cat.rest_fixtures[path.stem] = _read(path)
    names = [n for n in FIXTURE_ORDER if (fixtures_dir / f"{n}.json").exists()]
    names += sorted(p.stem for p in fixtures_dir.glob("*.json") if p.stem not in names)
    for name in names:
        cat.fixtures[name] = _read(fixtures_dir / f"{name}.json")

    def body(name: str) -> dict[str, Any]:
        fx = cat.rest_fixtures.get(name)
        return fx["response"]["body"] if fx else {}

    cat.vocab = {k: v for k, v in body("vocab").items() if k != "spec_version"}
    cat.facets = {k: v for k, v in body("facets").items() if k != "spec_version"}

    # Cards and assets from every fixture (REST first, then streams in order).
    assets_by_part: dict[str, list[dict[str, Any]]] = {}

    def visit(node: dict[str, Any]) -> None:
        if _is_card(node):
            cat.cards.setdefault(node["part_id"], copy.deepcopy(node))
        if "instance_id" in node and "part_id" in node and isinstance(node.get("assets"), list):
            assets_by_part.setdefault(node["part_id"], copy.deepcopy(node["assets"]))

    for fx in cat.rest_fixtures.values():
        _walk(fx.get("response", {}).get("body"), visit)
    for fx in cat.fixtures.values():
        _walk(fx.get("steps"), visit)

    overlay_path = catalog_dir / "parts_overlay.json"
    overlay = _read(overlay_path).get("parts", {}) if overlay_path.exists() else {}

    full_part = body("part").get("part")
    for part_id, card in cat.cards.items():
        if full_part and full_part.get("part_id") == part_id:
            cat.parts[part_id] = copy.deepcopy(full_part)
            continue
        cat.parts[part_id] = _part_record(
            part_id, card, assets_by_part.get(part_id, []), overlay.get(part_id)
        )
    for part_id in overlay:
        if part_id not in cat.parts:
            log.warning("overlay part %s has no card in the fixtures; skipped", part_id)
    # cards are what people see: generic names from the function; the records keep maker and MPN
    for part_id, card in cat.cards.items():
        naming.neutral(card, cat.parts.get(part_id))

    # Designs: full records from REST fixtures, then the overlay.
    full_design = body("design").get("design")
    if full_design:
        cat.designs[full_design["design_id"]] = copy.deepcopy(full_design)
    designs_overlay = catalog_dir / "designs_overlay.json"
    if designs_overlay.exists():
        for d in _read(designs_overlay).get("designs", []):
            cat.designs.setdefault(d["design_id"], copy.deepcopy(d))
    for item in body("designs").get("items", []):
        cat.design_cards[item["design_id"]] = copy.deepcopy(item)
    for design_id, design in cat.designs.items():
        if design_id not in cat.design_cards:
            card: dict[str, Any] = {
                "design_id": design_id,
                "name": design["name"],
                "licence_spdx": design.get("licence", {}).get("spdx", "NOASSERTION"),
                "commercial_ok": design.get("licence", {}).get("commercial_ok", "unknown"),
                "device_class": design.get("device_class", "unknown"),
                "thumbnail_url": None,
            }
            if design.get("summary"):
                card["summary"] = design["summary"]
            cat.design_cards[design_id] = card
    log.info("catalog: %d parts, %d designs", len(cat.parts), len(cat.designs))
    return cat
