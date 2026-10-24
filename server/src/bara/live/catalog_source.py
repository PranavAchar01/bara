"""Part source for the live engine.

The real source is ``bara.catalog_db.CatalogDB`` (agent CATALOG, sqlite + FTS5). Until its
sqlite file exists, ``StubCatalogDB`` serves the same interface from the parts the fixture
catalog already loaded (fixture cards + server/data/catalog/parts_overlay.json). Both are
read through ``open_part_source``; nothing else in the live package knows which one it got.
"""

from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Any, Protocol

from bara.catalog import Catalog

log = logging.getLogger(__name__)


class PartSource(Protocol):
    name: str

    def get_part(self, part_id: str) -> dict[str, Any]: ...

    def query(
        self,
        function: str | None = None,
        facets: dict[str, Any] | None = None,
        interfaces: list[str] | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]: ...

    def designs(self) -> list[dict[str, Any]]: ...

    def functions(self) -> list[str]: ...

    def facet_keys(self) -> list[str]: ...


def facet_match(part: dict[str, Any], facet: str, op: str, value: Any) -> bool:
    """Same matching rule as CatalogDB.query: a list on either side matches on overlap."""
    have = (part.get("facets") or {}).get(facet)
    if have is None:
        return False
    if op in ("gte", "lte"):
        try:
            return float(have) >= float(value) if op == "gte" else float(have) <= float(value)
        except (TypeError, ValueError):
            return False
    if op == "ne":
        return not facet_match(part, facet, "eq", value)
    left = have if isinstance(have, list) else [have]
    right = value if isinstance(value, list) else [value]
    return any(_eq(a, b) for a in left for b in right)


def _eq(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b) if isinstance(a, bool) and isinstance(b, bool) else False
    if isinstance(a, int | float) and isinstance(b, int | float):
        return abs(float(a) - float(b)) < 1e-9
    return str(a).lower() == str(b).lower()


def part_functions(part: dict[str, Any]) -> list[str]:
    return [f["function_id"] for f in part.get("functions", []) if f.get("function_id")]


class StubCatalogDB:
    """CatalogDB interface over the fixture catalog. Used until catalog.sqlite exists."""

    name = "stub"

    def __init__(self, catalog: Catalog) -> None:
        self.catalog = catalog

    def get_part(self, part_id: str) -> dict[str, Any]:
        part = self.catalog.parts.get(part_id)
        if part is None:
            raise KeyError(part_id)
        return part

    def query(
        self,
        function: str | None = None,
        facets: dict[str, Any] | None = None,
        interfaces: list[str] | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        out = []
        for part in self.catalog.parts.values():
            if function and function not in part_functions(part):
                continue
            if any(not facet_match(part, k, "eq", v) for k, v in (facets or {}).items()):
                continue
            types = {i.get("type") for i in part.get("interfaces", [])}
            if interfaces and not set(interfaces) <= types:
                continue
            out.append(part)
        return out[:limit]

    def designs(self) -> list[dict[str, Any]]:
        return list(self.catalog.designs.values())

    def functions(self) -> list[str]:
        return self.catalog.function_ids()

    def facet_keys(self) -> list[str]:
        keys: set[str] = set()
        for part in self.catalog.parts.values():
            keys.update((part.get("facets") or {}).keys())
        return sorted(keys)


def open_part_source(catalog: Catalog, catalog_dir: Path) -> PartSource:
    """The real CatalogDB when its module and sqlite file exist, else the stub."""
    db_path = catalog_dir / "catalog.sqlite"
    if db_path.exists():
        try:
            from bara.catalog_db import CatalogDB  # type: ignore[import-not-found]

            db = CatalogDB(db_path)
            db.name = "catalog_db"
            log.info("live: part source is CatalogDB at %s", db_path)
            return db
        except Exception:  # a half-written catalog must not take the server down
            log.exception("live: CatalogDB failed to open; using the overlay stub")
    log.info("live: part source is the overlay stub (%d parts)", len(catalog.parts))
    return StubCatalogDB(catalog)


def card_for(part: dict[str, Any], catalog: Catalog | None = None) -> dict[str, Any]:
    """SPEC PartCard for a part record (the catalog's own card when it has one)."""
    pid = part["part_id"]
    if catalog is not None and pid in catalog.cards:
        return copy.deepcopy(catalog.cards[pid])
    functions = part.get("functions", [])
    primary = next((f["function_id"] for f in functions if f.get("primary")), None)
    if primary is None and functions:
        primary = functions[0]["function_id"]
    thumb = next((a["url"] for a in part.get("assets", []) if a.get("role") == "thumbnail"), None)
    licence = part.get("licence") or {}
    prov = part.get("provenance") or {}
    card: dict[str, Any] = {
        "part_id": pid,
        "display_name": str(part.get("display_name") or pid)[:120],
        "kind": part.get("kind") or "unknown",
        "summary": part.get("summary"),
        "key_specs": _key_specs(part),
        "thumbnail_url": thumb,
        "licence_spdx": licence.get("spdx") or "NOASSERTION",
        "commercial_ok": licence.get("commercial_ok") or "unknown",
        "verified": prov.get("verified") or "none",
        "source_url": prov.get("source_url") or prov.get("url"),
    }
    if primary:
        card["primary_function"] = primary
    return card


def _key_specs(part: dict[str, Any]) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    facets = part.get("facets") or {}
    for key in ("mcu_family", "switch_family", "display_type", "wireless", "v_logic_v"):
        value = facets.get(key)
        if value is None or isinstance(value, list | dict):
            continue
        label = key.replace("_", " ").replace(" v", "").capitalize()
        unit = "V" if key == "v_logic_v" else None
        specs.append({"label": label, "value": value, "unit": unit})
    return specs[:4]


def merge_into_catalog(catalog: Catalog, parts: list[dict[str, Any]]) -> None:
    """Make parts a live build used visible to edits.py and REST (part, card lookups)."""
    for part in parts:
        pid = part["part_id"]
        if pid not in catalog.parts:
            catalog.parts[pid] = copy.deepcopy(part)
        if pid not in catalog.cards:
            catalog.cards[pid] = card_for(part)


def model_asset(part: dict[str, Any]) -> dict[str, Any] | None:
    return next(
        (a for a in part.get("assets", []) if a.get("kind") == "glb" and a.get("role") == "model"),
        None,
    )


def gpio_count(part: dict[str, Any]) -> int | None:
    """Free GPIO a controller exposes, from its typed gpio interface. None when unknown."""
    total = 0
    found = False
    for iface in part.get("interfaces", []):
        if iface.get("type") != "gpio":
            continue
        params = iface.get("params") or {}
        count = params.get("count")
        if count is None and iface.get("pins"):
            count = len(iface["pins"])
        if isinstance(count, int):
            total += count
            found = True
    if found:
        return total
    elec = part.get("electrical") or {}
    value = elec.get("gpio_count")
    return int(value) if isinstance(value, int | float) else None


def logic_voltage(part: dict[str, Any], iface_type: str | None = None) -> float | None:
    for iface in part.get("interfaces", []):
        if iface_type and iface.get("type") != iface_type:
            continue
        v = (iface.get("params") or {}).get("v_logic_v")
        if isinstance(v, int | float):
            return float(v)
    v = (part.get("facets") or {}).get("v_logic_v")
    return float(v) if isinstance(v, int | float) else None


def i2c_addresses(part: dict[str, Any]) -> list[int]:
    for iface in part.get("interfaces", []):
        if iface.get("type") == "i2c" and iface.get("role") == "requires":
            addrs = (iface.get("params") or {}).get("addresses") or []
            return [int(a) for a in addrs if isinstance(a, int)]
    return []


def interface_of(part: dict[str, Any], iface_type: str, role: str | None = None) -> dict | None:
    for iface in part.get("interfaces", []):
        if iface.get("type") == iface_type and (role is None or iface.get("role") == role):
            return iface
    return None
