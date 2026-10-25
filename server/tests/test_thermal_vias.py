"""Unnumbered holes inside an exposed pad are its thermal vias and carry its net."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from bara.board.kicad import SCRIPT
from bara.board.libs import KICAD_PYTHON

LIB = Path(__file__).parents[1] / "data/catalog/fetched/src/C50506"  # DRV8833PWPR, HTSSOP-16 + EP

if not (KICAD_PYTHON.exists() and LIB.exists()):
    pytest.skip("KiCad or the fetched footprint is missing", allow_module_level=True)

PROBE = """
import json, sys
sys.path.insert(0, sys.argv[1])
import pcbnew
from kicad_script import _place_footprint
board = pcbnew.BOARD()
spec = {"lib_dir": sys.argv[2], "name": "C50506", "ref": "U1", "x": 0, "y": 0, "rot": 0,
        "pads": {"17": "GND"}}
_place_footprint(board, {}, spec)
fp = board.GetFootprints()[0]
print(json.dumps([p.GetNetname() for p in fp.Pads() if not p.GetNumber()]))
"""


def test_thermal_vias_take_the_exposed_pad_net() -> None:
    proc = subprocess.run(
        [str(KICAD_PYTHON), "-c", PROBE, str(SCRIPT.parent), str(LIB)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    vias = json.loads(proc.stdout.strip().splitlines()[-1])
    assert vias and set(vias) == {"GND"}
