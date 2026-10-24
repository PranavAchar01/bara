"""CatalogDB: unit tests on a tiny generated catalog, plus checks on the built catalog."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from bara.catalog_db import DEFAULT_PATH, CatalogDB, facet_matches, write_catalog
from bara.schemas import SchemaSet

SPEC = Path(__file__).resolve().parents[2] / "spec"


def _part(pid: str, fn: str, facets: dict[str, Any], ifaces: list[str], **kw: Any) -> dict:
    return {
        "part_id": pid,
        "kind": "component",
        "display_name": kw.get("name", pid),
        "summary": kw.get("summary"),
        "functions": [{"function_id": fn, "primary": True}],
        "interfaces": [
            {"id": t, "type": t, "role": "provides", "params": {}, "pins": []} for t in ifaces
        ],
        "licence": {"spdx": "MIT", "commercial_ok": "yes"},
        "provenance": {"route": "test"},
        "facets": {"has_mesh": kw.get("mesh", True), **facets},
    }


@pytest.fixture
def tiny(tmp_path: Path) -> CatalogDB:
    parts = [
        _part("sw:mx_red", "input.key", {"switch_family": "mx", "force_gf": 45}, [], name="MX Red"),
        _part(
            "sw:choc_red",
            "input.key",
            {"switch_family": "choc_v1", "force_gf": 50},
            [],
            name="Kailh Choc Red",
            summary="low profile linear switch",
        ),
        _part(
            "mod:nano",
            "compute.mcu",
            {"wireless": "ble", "power_source": ["usb", "battery"]},
            ["i2c", "gpio"],
            name="nice!nano v2",
            mesh=False,
        ),
    ]
    design = {"design_id": "d1", "name": "Demo"}
    path = tmp_path / "catalog.sqlite"
    write_catalog(path, [(p, {"part_id": p["part_id"], "models": []}) for p in parts], [design], {})
    return CatalogDB(path)


def test_get_part_and_unknown(tiny: CatalogDB) -> None:
    assert tiny.get_part("sw:mx_red")["display_name"] == "MX Red"
    with pytest.raises(KeyError):
        tiny.get_part("sw:nope")


def test_get_part_returns_a_copy(tiny: CatalogDB) -> None:
    tiny.get_part("sw:mx_red")["display_name"] = "changed"
    assert tiny.get_part("sw:mx_red")["display_name"] == "MX Red"


def test_query_function_facets_interfaces(tiny: CatalogDB) -> None:
    ids = [p["part_id"] for p in tiny.query(function="input.key")]
    assert ids == ["sw:choc_red", "sw:mx_red"]
    assert [p["part_id"] for p in tiny.query(facets={"switch_family": "MX"})] == ["sw:mx_red"]
    assert [p["part_id"] for p in tiny.query(facets={"force_gf": {"gte": 48}})] == ["sw:choc_red"]
    assert [p["part_id"] for p in tiny.query(facets={"power_source": "battery"})] == ["mod:nano"]
    assert [p["part_id"] for p in tiny.query(interfaces=["i2c"])] == ["mod:nano"]
    assert tiny.query(interfaces=["i2c", "spi"]) == []
    assert len(tiny.query(limit=1)) == 1


def test_query_orders_meshed_parts_first(tiny: CatalogDB) -> None:
    assert [p["part_id"] for p in tiny.query()][-1] == "mod:nano"


def test_search(tiny: CatalogDB) -> None:
    assert tiny.search("choc")[0]["part_id"] == "sw:choc_red"
    assert tiny.search("low prof")[0]["part_id"] == "sw:choc_red"
    assert tiny.search("nice nano")[0]["part_id"] == "mod:nano"
    assert {p["part_id"] for p in tiny.search("choc nano")} == {"sw:choc_red", "mod:nano"}
    assert tiny.search("   ") == []
    assert isinstance(tiny.search('"; DROP TABLE parts; -- *'), list)
    assert tiny.get_part("sw:mx_red")


def test_lists(tiny: CatalogDB) -> None:
    assert tiny.functions() == ["compute.mcu", "input.key"]
    assert "switch_family" in tiny.facet_keys()
    assert tiny.designs() == [{"design_id": "d1", "name": "Demo"}]


def test_facet_matches_rules() -> None:
    assert facet_matches(["a", "b"], ["b", "c"])
    assert not facet_matches(None, "x")
    assert facet_matches(3.0, 3)
    assert not facet_matches(True, "true")
    assert facet_matches("mx", {"ne": "choc_v1"})
    assert not facet_matches("x", {"gte": 1})


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        CatalogDB(tmp_path / "nope.sqlite")


built = pytest.mark.skipif(not DEFAULT_PATH.is_file(), reason="catalog not built")


@built
def test_built_catalog_is_schema_valid() -> None:
    db = CatalogDB()
    assert len(db) >= 150
    schemas = SchemaSet(SPEC / "schemas")
    for pid in db.part_ids():
        part = db.get_part(pid)
        assert schemas.errors("part.schema.json", part, strict=True) == [], pid
        for asset in part.get("assets", []):
            assert asset["url"].startswith("/assets/parts/")
    for design in db.designs():
        assert schemas.errors("design.schema.json", design) == [], design["design_id"]


@built
def test_built_catalog_keyboard_family() -> None:
    db = CatalogDB()
    for fn in ("input.key", "mech.keycap", "compute.mcu", "display.oled", "interconnect.jack"):
        assert db.query(function=fn), fn
    nano = db.get_part("mod:nice_nano_v2")
    assert nano["facets"]["wireless"] == "ble"
    assert db.query(function="input.key", facets={"switch_family": "choc_v1"})
    assert db.search("nice nano")[0]["part_id"] == "mod:nice_nano_v2"
    fp = db.footprint_for("mod:nice_nano_v2")
    assert fp is not None and fp.endswith(".kicad_mod")
    assert db.kicad("sw:cherry_mx2a_brown")["footprint"]["pads"]


@built
def test_built_catalog_meshes_exist() -> None:
    db = CatalogDB()
    server = Path(__file__).resolve().parents[1]
    if not any((server / "data" / "assets" / "parts").glob("*.glb")):
        pytest.skip("part GLBs are gitignored; they exist only where the catalog was built")
    for pid in db.part_ids():
        part = db.get_part(pid)
        asset = part["assets"][0]
        if asset["status"] == "ready":
            glb = server / "data" / asset["url"].removeprefix("/")
            assert glb.is_file(), pid
            assert glb.stat().st_size == asset["bytes"], pid
