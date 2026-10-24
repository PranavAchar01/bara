"""List parts fetched from LCSC that the stock KiCad library also carries.

Each one is a resolver gap: a stock KiCad part (reviewed footprint, KiCad 3D model)
must win over an EasyEDA download. Exits 1 when any are found.

    uv run python scripts/provenance_audit.py
"""

from __future__ import annotations

import sys
from typing import Any

from bara.kicad_generated import KicadIndex
from bara.live.completeness import Need
from bara.live.fetch import Overlay, Resolver, read_fetched


class _Stock:
    """The KiCad index alone, with nothing curated, so only the stock tier can answer."""

    name = "kicad"

    def __init__(self, index: KicadIndex) -> None:
        self.search = index.search

    def query(self, *a: Any, **k: Any) -> list[dict[str, Any]]:
        return []

    def get_part(self, part_id: str) -> dict[str, Any]:
        raise KeyError(part_id)


def main() -> int:
    index = KicadIndex.open()
    if index is None:
        sys.stderr.write("kicad index not built\n")
        return 2
    resolver = Resolver(Overlay(_Stock(index)))
    resolver._accept = lambda part, need: part  # type: ignore[method-assign]  # no GLB export
    rows = [r for r in read_fetched() if r.get("mpn")]
    gaps = 0
    for row in rows:
        mpn = row["mpn"]
        hit = resolver.generated(Need("audit", "audit", mpn, kicad=(mpn,)))
        if hit is not None:
            gaps += 1
            sys.stdout.write(f"{row['part_id']}\t{mpn}\t-> {hit['part_id']}\n")
    sys.stderr.write(f"{gaps} of {len(rows)} fetched parts have a stock KiCad symbol\n")
    return 1 if gaps else 0


if __name__ == "__main__":
    raise SystemExit(main())
