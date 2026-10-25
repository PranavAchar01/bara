"""A bare multiplexed seven-segment display gets a driver chip, wired net by net, and the
firmware then has a platform to run it. An LCSC chip whose footprint names no KiCad one is
still drawn from the KiCad footprint with the same package."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from bara.board import generic
from bara.board.layout import Item
from bara.catalog import load_catalog
from bara.kicad_generated import GLB_URL, KicadIndex, easyeda_package_sig
from bara.live import firmware, seven_seg
from bara.live.catalog_source import open_part_source
from bara.live.completeness import Need
from bara.live.compose import Composer, Instance, Slot, _model_from_footprint

ROOT = Path(__file__).resolve().parents[1]

CA56 = {
    "part_id": "kicadgen:kicad:sym:Display_Character:CA56-12SURKWA",
    "name": "CA56-12SURKWA",
    "display_name": "CA56-12SURKWA (Display_Character)",
    "descr": "4 digit 7 segment hyper red LED, common anode",
    "facets": {"pin_count": 12},
    "functions": [{"function_id": "display.seven_segment", "primary": True}],
}
CC56 = {**CA56, "descr": "4 digit 7 segment hyper red LED, common cathode"}
MODULE = {
    **CA56,
    "part_id": "mod:tm1637_4digit",
    "display_name": "4 digit 7 segment module with TM1637 driver",
}
TM1637 = {
    "part_id": "lcsc:tm1637_c20001",
    "display_name": "TM1637 (TM)",
    "functions": [{"function_id": "display.seven_segment", "primary": True}],
    "facets": {"package": "SOP-20_L12.8-W7.5-P1.27-LS10.4-BL"},
}


def test_a_bare_multi_digit_display_needs_a_driver_a_module_does_not() -> None:
    assert seven_seg.needs_driver(CA56) and seven_seg.needs_driver(CC56)
    assert not seven_seg.needs_driver(MODULE)
    assert not seven_seg.needs_driver({**CA56, "interfaces": [{"type": "i2c", "role": "requires"}]})
    one = {**CA56, "descr": "One digit 7 segment red, common cathode", "facets": {"pin_count": 10}}
    assert not seven_seg.needs_driver(one)
    assert not seven_seg.needs_driver(TM1637)  # a chip is not glass


def test_the_driver_follows_the_glass_polarity() -> None:
    assert seven_seg.driver_for(CA56).key == "tm1637"
    assert seven_seg.driver_for(CC56).key == "max7219"
    assert firmware.driver_key(TM1637) == "tm1637"


def test_pin_names_map_to_segments_and_digits() -> None:
    ca56 = ["a", "b", "c", "d", "e", "f", "g", "DPX", "CA1", "CA4"]
    assert [seven_seg.segment_index(n) for n in ca56] == [1, 2, 3, 4, 5, 6, 7, 8, None, None]
    assert [seven_seg.digit_index(n) for n in ("CA1", "CC4", "GRID2", "DIG_0", "DIG_3")] == [
        1,
        4,
        2,
        1,
        4,
    ]
    assert seven_seg.segment_index("SG1KS3") == 3 and seven_seg.segment_index("SEG_DP") == 8
    assert seven_seg.segment_index("SEG_C") == 3
    assert seven_seg.segment_index("DIO") is None and seven_seg.digit_index("VDD") is None


def _item(ref: str, role: str, pins: dict[str, str]) -> Item:
    it = Item(ref, role, SimpleNamespace(), 0, 0)  # type: ignore[arg-type]
    it.meta["pins"] = pins
    # what _pads_from_pins hands over: every pin on a net of its own
    it.pads = {n: f"{name}_{ref}" for n, name in pins.items()}
    return it


def test_display_and_driver_share_segment_and_digit_nets() -> None:
    disp = _item(
        "DS1",
        "screen",
        {"1": "e", "2": "d", "3": "DPX", "4": "c", "5": "g", "6": "CA4"}
        | {"7": "b", "8": "CA3", "9": "CA2", "10": "f", "11": "a", "12": "CA1"},
    )
    drv = _item(
        "U2",
        "led_driver",
        {"1": "GND", "2": "SG1KS1", "3": "SG1KS2", "4": "SG1KS3", "5": "SG1KS4", "6": "SG1KS5"}
        | {"7": "SG1KS6", "8": "SG1KS7", "9": "SG1KS8", "10": "GRID6", "11": "GRID5"}
        | {"12": "GRID4", "13": "GRID3", "14": "GRID2", "15": "GRID1", "16": "VDD"}
        | {"17": "DIO", "18": "CLK", "19": "K1", "20": "K2"},
    )
    log: list[str] = []
    generic._wire_segment_displays([disp, drv], log)
    assert disp.pads["11"] == drv.pads["2"] == "SEGBUS_1"  # a
    assert disp.pads["3"] == drv.pads["9"] == "SEGBUS_8"  # the point
    assert disp.pads["12"] == drv.pads["15"] == "SEGBUS_D1"  # digit 1
    assert disp.pads["6"] == drv.pads["12"] == "SEGBUS_D4"  # digit 4
    assert "11" not in drv.pads and "10" not in drv.pads  # grids 5 and 6: no digit there
    assert drv.pads["17"] == "DIO_U2" and drv.pads["18"] == "CLK_U2"  # not a shared SPI bus
    assert drv.pads["16"] == "3V3"
    assert all(v.startswith(generic.INTERNAL_NETS) for v in disp.pads.values())


def test_a_max7219_gets_its_segment_current_resistor_net() -> None:
    drv = _item("U3", "led_driver", {"1": "DIN", "2": "ISET", "3": "V+", "4": "LOAD"})
    disp = _item("DS1", "screen", {"1": "a", "2": "CC1"})
    generic._wire_segment_displays([disp, drv], [])
    assert drv.pads["2"] == "ISET_U3" and drv.pads["3"] == "VBUS"
    assert drv.pads["4"] == "LOAD_U3" and drv.pads["1"] == "DIN_U3"


def test_the_driver_chip_is_not_a_panel_to_the_board() -> None:
    assert generic._role(TM1637) == "led_driver"
    assert generic._role(CA56) == "screen"


@pytest.fixture(scope="module")
def composer() -> Composer:
    catalog_dir = ROOT / "data" / "catalog"
    source = open_part_source(load_catalog(ROOT.parent / "spec", catalog_dir), catalog_dir)
    functions = ["display.seven_segment", "compute.mcu"]
    brief = {"device": "clock", "functions": functions, "features": []}
    spec = {"functions": [{"function_id": f, "required": True, "count": 1} for f in functions]}
    return Composer(source, spec, brief, None, None)


def emit_to(events: list[tuple[str, Any]]) -> Any:
    return lambda kind, payload, **_: events.append((kind, payload))


def test_the_composer_adds_a_driver_slot_behind_a_bare_display(composer: Composer) -> None:
    disp = next(s for s in composer.slots if s.function_id == seven_seg.FUNCTION_ID)
    disp.chosen = CA56
    events: list[tuple[str, Any]] = []
    assert composer.add_segment_driver(disp, emit_to(events))
    driver = composer.slots[composer.slots.index(disp) + 1]
    assert driver.drives == disp.slot_id and driver.need is not None
    assert driver.need.names == ("tm1637",) and driver.need.pin_kind == "seg_driver_2wire"
    assert [s.order for s in composer.slots] == list(range(len(composer.slots)))
    assert events and events[0][0] == "slot.updated"
    assert not composer.add_segment_driver(disp, emit_to(events))  # once


def test_the_display_behind_a_driver_costs_the_drivers_wires(composer: Composer) -> None:
    disp = next(s for s in composer.slots if s.function_id == seven_seg.FUNCTION_ID)
    driver = next(s for s in composer.slots if s.drives == disp.slot_id)
    n, items = composer.pin_need_for("none")
    assert n == 2 and sum("display" in i.lower() or "driver" in i.lower() for i in items) == 1
    driver.need = Need(**{**driver.need.__dict__, "pin_kind": "seg_driver_3wire"})  # type: ignore[union-attr]
    assert composer.pin_need_for("none")[0] == 3


def test_a_module_with_its_own_driver_gets_none(composer: Composer) -> None:
    other = Slot(
        "d2", "Display", seven_seg.FUNCTION_ID, "critical", 9, [Instance("u_d2", "none", 1)]
    )
    other.chosen = MODULE
    assert not composer.add_segment_driver(other, lambda *a, **k: None)


def test_firmware_runs_the_display_through_its_driver() -> None:
    disp = SimpleNamespace(
        slot_id="b_display", function_id="display.seven_segment", chosen=CA56, drives=None
    )
    drv = SimpleNamespace(
        slot_id="b_display_driver",
        function_id="component.ic",
        chosen=TM1637,
        drives="b_display",
        instances=[SimpleNamespace(instance_id="u_segdrv")],
    )
    ctrl = SimpleNamespace(
        slot_id="controller",
        function_id="compute.mcu",
        chosen={"part_id": "rf:esp32_c3_wroom_02", "display_name": "ESP32-C3-WROOM-02"},
        instances=[SimpleNamespace(instance_id="u_mcu", side="none")],
    )
    fw, checks = firmware.make_firmware({"device": "clock"}, None, [disp, drv, ctrl], None)
    yaml = next(f["content"] for f in fw["files"] if f["path"] == "bara.yaml")
    assert "platform: tm1637" in yaml and "no ESPHome config known" not in yaml
    assert [c["status"] for c in checks if "driver" in c["check_key"]] == ["pass"]


def _index(tmp_path: Path, rows: list[tuple[str, str, str, int]]) -> KicadIndex:
    path = tmp_path / "kicad_index.sqlite"
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE kicad_parts (part_id TEXT, name TEXT, lib TEXT, kind TEXT, has_model INT,"
        " source TEXT, row_json TEXT)"
    )
    for pid, name, lib, has in rows:
        con.execute(
            "INSERT INTO kicad_parts VALUES (?, ?, ?, 'footprint', ?, 'kicad', '{}')",
            (pid, name, lib, has),
        )
    con.commit()
    con.close()
    return KicadIndex(path)


SOIC16W = "kicadgen:kicad:fp:Package_SO:SOIC-16W_7.5x10.3mm_P1.27mm"


def _so(name: str, has_model: int = 1) -> tuple[str, str, str, int]:
    return (f"kicadgen:kicad:fp:Package_SO:{name}", name, "Package_SO", has_model)


ROWS = [
    _so("SOIC-16W_7.5x10.3mm_P1.27mm"),
    _so("SOIC-16_3.9x9.9mm_P1.27mm"),
    _so("SOIC-20W_7.5x12.8mm_P1.27mm"),
    _so("SOIC-14_3.9x8.7mm_P1.27mm", 0),
]


def test_an_lcsc_package_finds_the_kicad_footprint_with_the_same_outline(tmp_path: Path) -> None:
    index = _index(tmp_path, ROWS)
    assert easyeda_package_sig("SOIC-16_L10.3-W7.5-P1.27-LS10.3-BL") == (
        "SOIC",
        "16",
        "7.5x10.3",
        "1.27",
    )
    assert index.package_lender("SOIC-16_L10.3-W7.5-P1.27-LS10.3-BL") == SOIC16W
    assert index.package_lender(TM1637["facets"]["package"]).endswith("SOIC-20W_7.5x12.8mm_P1.27mm")
    assert index.package_lender("SOIC-14_L8.7-W3.9-P1.27-LS6.0-BL") is None  # no model there
    assert index.package_lender("SOIC-16_L10.3-W7.5-P1.27") == SOIC16W
    assert index.package_lender("BGA-9_L2-W2-P0.5") is None and index.package_lender("") is None


def test_an_lcsc_chip_with_no_served_model_is_drawn_from_its_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index = _index(tmp_path, ROWS)
    monkeypatch.setattr(KicadIndex, "open", classmethod(lambda cls, path=None: index))
    ds3231 = {
        "part_id": "lcsc:ds3231sn_t_r_c9866",
        "footprint": "easyeda:C9866",
        "facets": {"package": "SOIC-16_L10.3-W7.5-P1.27-LS10.3-BL"},
    }
    assets = [
        {
            "kind": "glb",
            "role": "model",
            "url": "/assets/parts/fetched/NOT-HERE-C9866.glb",
            "status": "ready",
        }
    ]
    _model_from_footprint(ds3231, assets)
    assert assets[0]["url"].startswith(GLB_URL + "/") and assets[0]["status"] == "pending"
    assert "SOIC-16W_7.5x10.3mm" in assets[0]["url"]
