"""A part fetched from LCSC sits on the board by its own footprint, not as a wired module."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from bara.board import libs
from bara.board.generic import plan_device_board

SRC = Path(__file__).resolve().parents[1] / "data/catalog/fetched/src/C351410"

if not (SRC / "C351410.kicad_mod").exists():
    pytest.skip("fetched part C351410 is not in the catalog", allow_module_level=True)


def test_a_fetched_chip_is_placed_on_the_board(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shutil.copytree(SRC, tmp_path / "C351410")
    monkeypatch.setattr(libs, "FETCHED_SRC", tmp_path)
    fp = libs.find_footprint("easyeda:C351410")
    assert fp is not None and len(fp.pads) == 6
    assert fp.models == [str(tmp_path / "C351410/C351410.step")]
    assert fp.extra["model_xforms"][fp.models[0]]["rotate"] == [0.0, 0.0, 270.0]
    record = {
        "part_id": "lcsc:dw01a_c351410",
        "display_name": "DW01A",
        "footprint": "easyeda:C351410",
        "functions": [{"function_id": "power.protection", "primary": True}],
        "mechanical": {"bbox_mm": {"min": [-1.5, -0.8, 0], "max": [1.5, 0.8, 1.2]}},
    }
    part = {"part_id": record["part_id"], "instance_id": "i1", "quantity": 1, "record": record}
    plan = plan_device_board([part], [])
    assert not [it for it in plan.items if it.role == "module"]
    assert [it.fp.name for it in plan.items if it.fp is not None] == ["C351410"]
