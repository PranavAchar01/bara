"""A part a person touches is never cut off: its body lies inside the outline, the case open
over it; and a wired part larger than the product outline is reported as not fitting."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from shapely.geometry import Polygon

from bara.board.generic import _off_board_fit
from bara.board.layout import Item
from bara.geometry import enclose_report
from bara.geometry.samples import macropad_board


def _clipped(board: dict[str, Any], brief: dict[str, Any]) -> dict[str, Any]:
    checks = enclose_report(board, [], brief).checks
    return next(c for c in checks if c["rule_id"] == "mech.access.clipped")


@pytest.fixture(scope="module")
def sample(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict, dict]:
    board, brief = macropad_board()
    for p in board["placements"]:
        if p.get("role") == "switch":
            p["touch"] = True
    return board, brief


def test_touched_parts_inside_the_outline_pass(sample, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("BARA_DATA_DIR", str(tmp_path))
    board, brief = sample
    check = _clipped(copy.deepcopy(board), brief)
    assert check["status"] == "pass", check["message"]


def test_a_touched_part_over_the_edge_fails(sample, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("BARA_DATA_DIR", str(tmp_path))
    board, brief = copy.deepcopy(sample[0]), sample[1]
    sw = next(p for p in board["placements"] if p["ref"] == "SW5")
    sw["x_mm"] += 9.0  # half its body past the right edge of the outline
    board["placements"] = [p for p in board["placements"] if p["ref"] not in ("SW5_CAP",)]
    check = _clipped(board, brief)
    assert check["status"] == "fail" and "SW5" in check["message"]


def _cell(w: float, h: float) -> Item:
    return Item("M1", "module", None, 0, 0, 0, "bottom", label="plate", on_pcb=False,
                size_mm=(w, h), meta={"instance_id": "m1"})  # fmt: skip


def test_a_wired_part_larger_than_the_outline_does_not_fit() -> None:
    outline = Polygon([(-50, -30), (50, -30), (50, 30), (-50, 30)])
    pf: dict[str, Any] = {"fit_report": {"ok": True}}
    log: list[str] = []
    _off_board_fit([_cell(135.0, 94.0)], outline, pf, log)
    assert pf["fit_report"]["ok"] is False
    assert pf["fit_report"]["stuck"]["instance_id"] == "m1"
    assert any(line.startswith("FORM_OVERFLOW") for line in log)


def test_a_wired_part_that_fits_turned_is_turned() -> None:
    outline = Polygon([(-20, -50), (20, -50), (20, 50), (-20, 50)])
    pf: dict[str, Any] = {"fit_report": {"ok": True}}
    cell = _cell(60.0, 30.0)
    _off_board_fit([cell], outline, pf, [])
    assert pf["fit_report"]["ok"] is True and cell.rot == 90.0
