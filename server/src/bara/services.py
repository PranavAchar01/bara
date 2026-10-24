"""Shared singletons for one app instance."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from bara.catalog import Catalog, load_catalog
from bara.config import Settings
from bara.edits import EditEngine
from bara.engine import Engine
from bara.router import Router
from bara.schemas import SchemaSet


@dataclass
class DedupeStore:
    """Global msg_id memory (SPEC 8.6): msg_id -> (time seen, first ack payload)."""

    ttl_s: int
    seen: dict[str, tuple[float, dict[str, Any]]] = field(default_factory=dict)

    def get(self, msg_id: str) -> dict[str, Any] | None:
        self._purge()
        hit = self.seen.get(msg_id)
        return dict(hit[1]) if hit else None

    def put(self, msg_id: str, ack_payload: dict[str, Any]) -> None:
        self.seen[msg_id] = (time.monotonic(), dict(ack_payload))

    def _purge(self) -> None:
        cutoff = time.monotonic() - self.ttl_s
        for key in [k for k, (t, _) in self.seen.items() if t < cutoff]:
            del self.seen[key]


@dataclass
class Services:
    settings: Settings
    catalog: Catalog
    schemas: SchemaSet
    router: Router
    edits: EditEngine
    engine: Engine
    dedupe: DedupeStore
    started: float


def build_services(settings: Settings) -> Services:
    catalog = load_catalog(settings.spec_dir, settings.catalog_dir)
    schemas = SchemaSet(settings.schemas_dir)
    router = Router(catalog, settings)
    edits = EditEngine(catalog, settings.catalog_dir / "check_rules.json", schemas)
    engine = Engine(catalog, settings, router, edits)
    if not settings.mock:
        from bara.live.catalog_source import open_part_source
        from bara.live.runner import LiveRunner

        engine.live = LiveRunner(engine, open_part_source(catalog, settings.catalog_dir))
    return Services(
        settings=settings,
        catalog=catalog,
        schemas=schemas,
        router=router,
        edits=edits,
        engine=engine,
        dedupe=DedupeStore(settings.msg_id_ttl_s),
        started=time.monotonic(),
    )
