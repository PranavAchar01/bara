"""The schematic is drawn from the board's own pad-to-net map: real library symbols, one
framed block per function, power symbols, net labels, a title block, and a netlist that
matches the copper."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from bara.board import schematic as S
from bara.board.kicad import KICAD_CLI
from bara.board.layout import Item
from bara.board.libs import find_footprint

if not Path(KICAD_CLI).exists():
    pytest.skip("kicad-cli is missing", allow_module_level=True)


def _has(text: str, head: str, value: str) -> bool:
    return re.search(r"\(" + head + r'\s+"' + re.escape(value) + '"', text) is not None


def _items() -> list[Item]:
    res = find_footprint("Resistor_SMD:R_0603_1608Metric")
    led = find_footprint("LED_SMD:LED_0603_1608Metric")
    soic = find_footprint("Package_SO:SOIC-8_3.9x4.9mm_P1.27mm")
    assert res and led and soic
    mcu = Item(
        "U1",
        "mcu",
        soic,
        0,
        0,
        pads={"1": "3V3", "2": "LED_A", "3": "BTN", "8": "GND"},
        label="8-pin controller",
        meta={"slot_id": "controller", "pins": {"1": "VDD", "2": "PA0", "3": "PA1", "8": "VSS"}},
    )
    return [
        mcu,
        Item(
            "R1",
            "passive",
            res,
            0,
            0,
            pads={"1": "LED_A", "2": "LED_K"},
            label="1 k",
            meta={"near": mcu},
        ),
        Item(
            "D1",
            "led",
            led,
            0,
            0,
            pads={"1": "GND", "2": "LED_K"},
            label="status light",
            meta={"slot_id": "status_light"},
        ),
        Item(
            "R2",
            "passive",
            res,
            0,
            0,
            pads={"1": "BTN", "2": "3V3"},
            label="10 k",
            meta={"slot_id": "status_light"},
        ),
    ]


def test_the_schematic_matches_the_board_and_reads_by_block(tmp_path: Path) -> None:
    items = _items()
    sch = tmp_path / "main.kicad_sch"
    sheet = S.write(items, sch, title="desk lamp")
    text = sch.read_text()
    # stock symbols for the passives and the light, a pin box only for the bare package
    assert sheet.symbols["R1"] == "Device.kicad_sym"
    assert sheet.symbols["D1"] == "Device.kicad_sym"
    assert sheet.symbols["U1"] == "pin box"
    # the support resistor sits in its host's block; one block per function
    assert sheet.blocks == ["Controller", "Status light"]
    assert _has(text, "lib_id", "power:GND") and _has(text, "lib_id", "power:+3V3")
    assert _has(text, "label", "LED_A") and _has(text, "label", "BTN")
    assert _has(text, "title", "desk lamp")
    assert "(no_connect" in text  # the controller's unwired pins
    drawn = S.netlist(sch, KICAD_CLI)
    assert S.mismatches(items, drawn) == []
    assert drawn[("U1", "8")] == drawn[("D1", "1")] == "GND"
    files = S.export(sch, tmp_path / "out", KICAD_CLI)
    assert files["svg"].stat().st_size > 1000 and files["pdf"].stat().st_size > 1000


def test_a_miswired_drawing_is_caught() -> None:
    items = _items()
    drawn = {("U1", "2"): "LED_A", ("R1", "1"): "OTHER"}
    assert S.mismatches(items, drawn)


FETCHED = Path(__file__).parents[1] / "data/catalog/fetched/src/C50506"


@pytest.mark.skipif(not FETCHED.exists(), reason="the fetched part is missing")
def test_a_fetched_part_takes_the_symbol_fetched_beside_its_footprint(tmp_path: Path) -> None:
    fp = find_footprint("easyeda:C50506")
    assert fp is not None
    drv = Item("U1", "driver", fp, 0, 0, pads={"1": "GND", "17": "GND"}, label="motor driver")
    sheet = S.write([drv], tmp_path / "main.kicad_sch", title="t")
    assert sheet.symbols["U1"] == "C50506.kicad_sym"
    text = (tmp_path / "main.kicad_sch").read_text()
    assert '"Manufacturer"' not in text  # vendor fields stay out of the drawing
