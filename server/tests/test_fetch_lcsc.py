"""catalog_build.fetch_lcsc: record conversion and merge, offline (no network, no kicad-cli)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bara.catalog import Catalog  # noqa: E402
from bara.live.catalog_source import load_fetched, open_part_source  # noqa: E402
from catalog_build import fetch_lcsc as f  # noqa: E402
from catalog_build.kicad_lib import read_footprint  # noqa: E402

FOOTPRINT = Path(__file__).parent / "fixtures/lcsc_C2848306.kicad_mod"
INFO = {
    "mpn": "SHT40-AD1B-R3",
    "manufacturer": "Sensirion",
    "package": "DFN-4-EP(1.5x1.5)",
    "description": "Humidity\x00 and temperature\nsensor",
    "datasheet": "https://example.com/sht40.pdf",
}
GLB = {
    "bytes": 18076,
    "sha256": "ab" * 32,
    "bbox_mm": {"min": [-0.76, -0.76, 0.0], "max": [0.76, 0.76, 0.55]},
    "nodes": ["sht40"],
}


def record(glb=GLB, function="sense.humidity"):
    return f.build_record(
        lcsc_id="C2848306",
        info=INFO,
        function=function,
        footprint=read_footprint(FOOTPRINT),
        pins={"1": "SDA", "2": "SCL"},
        glb=glb,
        model_url="https://modules.easyeda.com/3dmodel/abc",
    )


def test_record_matches_catalog_shape():
    r = record()
    assert r["part_id"] == "lcsc:sht40_ad1b_r3_c2848306"
    assert r["display_name"] == "SHT40-AD1B-R3 (Sensirion)"
    assert r["functions"] == [{"function_id": "sense.humidity", "primary": True}]
    asset = r["assets"][0]
    assert asset["url"] == "/assets/parts/fetched/C2848306.glb"
    assert asset["sha256"] == GLB["sha256"] and asset["status"] == "ready"
    assert r["mechanical"]["bbox_mm"] == GLB["bbox_mm"]
    assert r["mechanical"]["mating_features"][0]["kind"] == "pad"
    assert r["facets"]["has_mesh"] is True
    assert r["facets"]["height_mm"] == 0.55
    assert r["facets"]["pin_count"] == 5 and r["facets"]["mount"] == "smd"
    assert r["summary"] == "Humidity and temperature sensor"  # control characters stripped
    json.dumps(r)


def test_provenance_and_licence_are_restrictive_by_default():
    r = record()
    assert r["provenance"]["lcsc_id"] == "C2848306"
    assert r["provenance"]["source_url"] == "https://www.lcsc.com/product-detail/C2848306.html"
    assert r["provenance"]["untrusted_source"] is True
    assert r["licence"]["spdx"] == "NOASSERTION"
    assert r["licence"]["commercial_ok"] == "unknown"


def test_missing_model():
    r = record(glb=None)
    asset = r["assets"][0]
    assert asset["status"] == "missing" and "sha256" not in asset
    assert r["facets"]["has_mesh"] is False
    assert "bbox_mm" not in r["mechanical"]


@pytest.mark.parametrize("bad", ["", "c123", "C12; rm -rf /", "../C123", "C"])
def test_lcsc_id_is_validated(bad):
    with pytest.raises(ValueError):
        f.valid_lcsc(bad)


def test_function_is_validated():
    with pytest.raises(ValueError):
        record(function="../etc")


def test_symbol_pins_sorted_and_cleaned():
    def pin(num, name):
        return SimpleNamespace(
            settings=SimpleNamespace(spice_pin_number=num), name=SimpleNamespace(text=name)
        )

    sym = SimpleNamespace(pins=[pin("10", "GND\n"), pin("2", "SCL"), pin("1", "SDA"), pin("", "x")])
    assert f.symbol_pins(sym) == {"1": "SDA", "2": "SCL", "10": "GND"}


def test_best_match_prefers_exact_mpn_in_stock_from_a_manufacturer():
    rows = [
        {"lcsc": "C9", "mpn": "MPU-6050", "brand": "JLCPCB Assembly", "stock": 0},
        {"lcsc": "C24112", "mpn": "MPU-6050", "brand": "TDK InvenSense", "stock": 5},
        {"lcsc": "C5", "mpn": "ZY-GYRO", "brand": "X", "stock": 99},
    ]
    assert f.best_match("MPU6050", rows)["lcsc"] == "C24112"
    assert f.best_match("nothing", rows) is None


def test_upsert_replaces_by_part_id(tmp_path):
    path = tmp_path / "fetched" / "fetched.jsonl"
    f.upsert(record(), path)
    f.upsert(record(glb=None), path)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(rows) == 1 and rows[0]["assets"][0]["status"] == "missing"


def test_catalog_source_loads_fetched_parts(tmp_path):
    f.upsert(record(), tmp_path / "fetched" / "fetched.jsonl")
    assert [p["part_id"] for p in load_fetched(tmp_path)] == ["lcsc:sht40_ad1b_r3_c2848306"]
    catalog = Catalog()
    source = open_part_source(catalog, tmp_path)
    pid = "lcsc:sht40_ad1b_r3_c2848306"
    assert source.get_part(pid)["mpn"] == "SHT40-AD1B-R3"
    assert [p["part_id"] for p in source.query(function="sense.humidity")] == [pid]
    assert catalog.cards[pid]["commercial_ok"] == "unknown"
