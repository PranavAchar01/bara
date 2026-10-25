"""Apify scout: the Actor's parsers, the engine's result splitting, caching and the shopping
list credit. Offline: the Actor run is replaced by canned dataset items."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from bara import bom
from bara.live import apify_scout as ap

scout = ap._scout_module()

MIT_TEXT = "MIT License\n\nPermission is hereby granted, free of charge, to any person..."
CERN_TEXT = "CERN Open Hardware Licence Version 2 - Strongly Reciprocal\n..."


def test_detect_licence() -> None:
    assert scout.detect_licence(MIT_TEXT) == "MIT"
    assert scout.detect_licence(CERN_TEXT) == "CERN-OHL-S-2.0"
    assert scout.detect_licence("all rights reserved") == ""


def test_lcsc_ids_and_bom_csv() -> None:
    assert scout.lcsc_ids("Uses C14267 (CH340G), C2913202 and C14267 again; C12 is not one") == [
        "C14267",
        "C2913202",
    ]
    csv_text = "Designator,Value,LCSC Part #\nU1,CH340G,C14267\nR1;R2,10k,C25744\nJ1,hdr,\n"
    assert scout.bom_lcsc_ids(csv_text) == ["C14267", "C25744"]


def test_price_breaks() -> None:
    raw = "1-99:0.0436,100-299:0.0358,9000-:0.0215"
    assert scout.price_breaks(raw) == [(1, 0.0436), (100, 0.0358), (9000, 0.0215)]
    assert scout.unit_price(raw, 1) == 0.0436
    assert scout.unit_price(raw, 150) == 0.0358
    assert scout.unit_price(raw, 20000) == 0.0215
    assert scout.unit_price("", 1) is None
    assert scout.unit_price(5.14) == 5.14


def test_tree_summary_skips_libraries_and_picks_files() -> None:
    paths = [
        "hw/board.kicad_pcb", "hw/board.kicad_sch", "hw/case/shell.stl",
        "hw/3dshapes/part.step", "bom/jlc_bom.csv", "LICENSE",
    ]  # fmt: skip
    t = scout.tree_summary(paths)
    assert t is not None
    assert t["kicad_pcb"] == "hw/board.kicad_pcb"
    assert t["enclosure_files"] == ["hw/case/shell.stl"]  # 3dshapes models are not a case
    assert t["bom_files"] == ["bom/jlc_bom.csv"] and t["licence_files"] == ["LICENSE"]
    assert scout.tree_summary(["README.md"]) is None
    lib = ["a.kicad_pcb", *[f"f{i}.kicad_mod" for i in range(50)]]
    assert scout.tree_summary(lib) is None


def test_part_item_links() -> None:
    row = {"lcsc": 14267, "mfr": "CH340G", "package": "SOP-16", "stock": 49238,
           "price": "1-9:0.5662,10-49:0.4783", "is_basic": False, "description": "USB"}  # fmt: skip
    p = scout.part_item(row)
    assert p["lcsc_id"] == "C14267" and p["unit_price_usd"] == 0.5662
    assert p["product_url"].endswith("/product-detail/C14267.html")
    assert "CH340G" in p["buy_urls"]["digikey"]


def _items() -> list[dict[str, Any]]:
    return [
        {
            "type": "design",
            "repo": "https://github.com/a/console",
            "licence": "MIT",
            "fit": "close",
        },
        {"type": "design", "repo": "", "licence": "MIT"},  # malformed: dropped
        {"type": "part", "lcsc_id": "C14267", "mpn": "CH340G", "unit_price_usd": 0.57, "stock": 9},
        {"type": "part", "lcsc_id": "bogus"},
        {"type": "stats", "pages_fetched": 17},
    ]


def test_split_items_and_summary() -> None:
    designs, parts, pages = ap.split_items(_items())
    assert len(designs) == 1 and len(parts) == 1 and pages == 17
    res = ap.ScoutResult("console", designs, parts, "local", pages)
    assert res.numbers() == {"designs_found": 1, "parts_priced": 1, "pages_crawled": 17,
                             "mode": "local"}  # fmt: skip
    assert "Apify scout" in res.summary() and "a/console (MIT)" in res.summary()


def test_merge_designs_scout_first_and_deduped() -> None:
    a = {"repo": "https://github.com/a/console"}
    merged = ap.merge_designs([a], [{"repo": "https://github.com/A/Console/"}, {"repo": "x/y"}])
    assert [d["repo"] for d in merged] == [a["repo"], "x/y"]


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(ap, "CACHE", tmp_path)
    monkeypatch.setattr(ap, "STATS", tmp_path / "stats.jsonl")
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    monkeypatch.delenv("BARA_APIFY", raising=False)
    return tmp_path


def test_run_caches_and_second_call_does_not_hit_actor(cache, monkeypatch) -> None:
    calls = []

    async def fake_execute(inp):
        calls.append(inp)
        return _items(), "local", []

    monkeypatch.setattr(ap, "execute", fake_execute)
    first = asyncio.run(ap.run("Handheld Console"))
    second = asyncio.run(ap.run("Handheld Console"))
    assert len(calls) == 1
    assert first.mode == "local" and second.mode == "cached"
    assert len(second.designs) == 1 and second.pages_fetched == 17
    assert "C14267" in ap.cached_quotes(["c14267", "C99999"])


def test_run_never_raises_and_off_switch(cache, monkeypatch) -> None:
    async def boom(inp):
        raise TimeoutError

    monkeypatch.setattr(ap, "execute", boom)
    assert asyncio.run(ap.run("x device")).mode == "failed"
    monkeypatch.setenv("BARA_APIFY", "off")
    assert asyncio.run(ap.run("x device")).mode == "off"
    assert ap.cached_quotes(["C14267"]) == {}


def test_token_picks_cloud_and_falls_back_locally(cache, monkeypatch) -> None:
    async def cloud(token, inp):
        assert token == "tok"
        raise ConnectionError

    async def local(inp):
        return _items()

    monkeypatch.setattr(ap, "_run_cloud", cloud)
    monkeypatch.setattr(ap, "_run_local", local)
    monkeypatch.setenv("APIFY_TOKEN", "tok")
    items, mode, notes = asyncio.run(ap.execute({"query": "q"}))
    assert mode == "local" and "apify cloud failed" in notes[0] and "tok" not in notes[0]

    async def cloud_ok(token, inp):
        return _items()

    monkeypatch.setattr(ap, "_run_cloud", cloud_ok)
    assert asyncio.run(ap.execute({"query": "q"}))[1] == "apify cloud"


def test_stats_totals(cache) -> None:
    res = ap.ScoutResult("q", [{"repo": "r"}], [{"lcsc_id": "C1000"}], "local", 12)
    ap.record("b_1", res, 3)
    ap.record("b_2", res, 1)
    assert ap.totals() == {"builds": 2, "designs_found": 2, "parts_priced": 2,
                           "pages_crawled": 24, "bom_parts_quoted": 4}  # fmt: skip


def test_bom_credits_apify_for_scouted_price() -> None:
    build = {"build_id": "b_t", "parts": [
        {"part_id": "lcsc_C14267", "instance_id": "i1", "quantity": 2,
         "card": {"display_name": "USB bridge"}},
    ]}  # fmt: skip
    quotes = {"C14267": {"unit_price_usd": 0.57, "stock": 49238, "mpn": "CH340G"}}
    out = bom.bom(build, None, quotes)
    row = out["rows"][0]
    assert row["sourced_via"] == "Apify scout" and row["stock"] == 49238
    assert row["line_total_usd"] == 1.14 and row["mpn"] == "CH340G"
    assert out["totals"]["sourced_via_apify"] == 1
    plain = bom.bom(build, None, {})
    assert plain["rows"][0]["sourced_via"] == "" and plain["rows"][0]["unit_price_usd"] is None
