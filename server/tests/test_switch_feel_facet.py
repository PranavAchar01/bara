"""A switch feel asked for in the brief filters on the facet the catalog actually carries
(manifest "actuation"), so a tactile Choc build keeps the Choc Brown."""

from __future__ import annotations

import json
from pathlib import Path

from bara.live.brief import spec_from_brief

CATALOG = Path(__file__).resolve().parents[1] / "data" / "catalog" / "catalog.jsonl"


def test_a_tactile_choc_brief_keeps_the_choc_brown() -> None:
    spec = spec_from_brief(
        "x", {"switch_type": "tactile"}, {}, assumptions=[], clarified=[]
    )
    (req,) = [r for r in spec["hard_requirements"] if r["value"] == "tactile"]
    switches = [json.loads(line) for line in CATALOG.open() if '"sw:kailh_choc' in line]
    fits = [p["part_id"] for p in switches if p["facets"].get(req["facet"]) == "tactile"]
    assert fits == ["sw:kailh_choc_brown"]
