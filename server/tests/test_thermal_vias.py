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


UNWIRED = PROBE.replace('"pads": {"17": "GND"}', '"pads": {}').replace(
    "if not p.GetNumber()]", "if p.GetNumber() in ('', '17')]"
)


def test_an_unwired_exposed_pad_shares_one_net_with_its_vias() -> None:
    proc = subprocess.run(
        [str(KICAD_PYTHON), "-c", UNWIRED, str(SCRIPT.parent), str(LIB)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    nets = json.loads(proc.stdout.strip().splitlines()[-1])
    assert len(nets) > 1 and set(nets) == {"unconnected-(U1-Pad17)"}


OPEN_COURTYARD = """(footprint "OPEN" (layer "F.Cu")
  (fp_line (start -2 -1) (end 2 -1) (layer "F.CrtYd") (stroke (width 0.05) (type solid)))
  (fp_line (start -2 1) (end 2 1) (layer "F.CrtYd") (stroke (width 0.05) (type solid)))
  (pad "1" smd rect (at -1 0) (size 0.8 0.8) (layers "F.Cu" "F.Paste" "F.Mask"))
  (pad "2" smd rect (at 1 0) (size 0.8 0.8) (layers "F.Cu" "F.Paste" "F.Mask"))
)
"""

COURTYARD_PROBE = """
import json, sys
sys.path.insert(0, sys.argv[1])
import pcbnew
from kicad_script import _place_footprint
board = pcbnew.BOARD()
spec = {"lib_dir": sys.argv[2], "name": "OPEN", "ref": "U1", "x": 0, "y": 0, "rot": 0,
        "pads": {}}
_place_footprint(board, {}, spec)
fp = board.GetFootprints()[0]
fp.BuildCourtyardCaches()
print(json.dumps([bool(fp.GetFlags() & pcbnew.MALFORMED_COURTYARDS),
                  fp.GetCourtyard(pcbnew.F_CrtYd).OutlineCount()]))
"""


def test_an_open_courtyard_is_closed_around_the_pads(tmp_path: Path) -> None:
    lib = tmp_path / "t.pretty"
    lib.mkdir()
    (lib / "OPEN.kicad_mod").write_text(OPEN_COURTYARD)
    proc = subprocess.run(
        [str(KICAD_PYTHON), "-c", COURTYARD_PROBE, str(SCRIPT.parent), str(lib)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    malformed, outlines = json.loads(proc.stdout.strip().splitlines()[-1])
    assert not malformed and outlines == 1
