"""A footprint rule area we drop stays alive, or SaveBoard reads freed memory (Pico "USB Cable")."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from bara.board.kicad import SCRIPT
from bara.board.libs import KICAD_PYTHON

if not KICAD_PYTHON.exists():
    pytest.skip("KiCad is not installed", allow_module_level=True)

PICO = KICAD_PYTHON.parents[5] / "SharedSupport/footprints/Module.pretty"

PROBE = """
import sys
sys.path.insert(0, sys.argv[1])
import pcbnew
from kicad_script import _place_footprint
board = pcbnew.BOARD()
spec = {"lib_dir": sys.argv[2], "name": "RaspberryPi_Pico_Common_THT", "ref": "U1",
        "x": 50.0, "y": 50.0}
_place_footprint(board, {}, spec)
pcbnew.SaveBoard(sys.argv[3], board)
print("saved", [z.GetZoneName() for z in board.Footprints()[0].Zones()])
"""


def test_a_pico_with_its_cable_area_dropped_saves(tmp_path: Path) -> None:
    if not (PICO / "RaspberryPi_Pico_Common_THT.kicad_mod").exists():
        pytest.skip("KiCad Module library not installed")
    proc = subprocess.run(
        [
            str(KICAD_PYTHON),
            "-c",
            PROBE,
            str(SCRIPT.parent),
            str(PICO),
            str(tmp_path / "t.kicad_pcb"),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-500:]
    assert "'Antenna Copper Keep Out'" in proc.stdout and "USB Cable" not in proc.stdout
