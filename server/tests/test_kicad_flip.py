"""A bottom-side footprint placed by kicad_script lands where the packer laid it out."""

from __future__ import annotations

import json
import subprocess

import pytest
from shapely.geometry import Point

from bara.board.kicad import SCRIPT
from bara.board.layout import Item
from bara.board.libs import KICAD_PYTHON, KICAD_SHARE

LIB = KICAD_SHARE / "footprints/Button_Switch_THT.pretty"
NAME = "SW_CK_JS202011CQN_DPDT_Straight"  # six pads in a 2x3 grid, asymmetric about both axes

if not (KICAD_PYTHON.exists() and LIB.exists()):
    pytest.skip("KiCad is not installed", allow_module_level=True)

PROBE = """
import json, sys
sys.path.insert(0, sys.argv[1])
import pcbnew
from kicad_script import _place_footprint
spec = json.loads(sys.argv[2])
board = pcbnew.BOARD()
_place_footprint(board, {}, dict(spec, ref="T", x=0, y=0, rot=0, side="top"))
_place_footprint(board, {}, dict(spec, ref="B"))
out = {}
for fp in board.GetFootprints():
    out[fp.GetReference()] = {
        p.GetNumber(): [p.GetPosition().x / 1e6, p.GetPosition().y / 1e6] for p in fp.Pads()
    }
print(json.dumps(out))
"""


@pytest.mark.parametrize("rot", [0.0, 90.0, 30.0])
def test_bottom_footprint_pads_match_the_packer_mirror(rot: float) -> None:
    spec = {"lib_dir": str(LIB), "name": NAME, "x": 10.0, "y": 20.0, "rot": rot, "side": "bottom"}
    run = subprocess.run(
        [str(KICAD_PYTHON), "-c", PROBE, str(SCRIPT.parent), json.dumps(spec)],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    pads = json.loads(run.stdout.strip().splitlines()[-1])
    item = Item(ref="B", role="switch", fp=None, x=10.0, y=20.0, rot=rot, side="bottom")
    for num, (lx, ly) in pads["T"].items():
        want = item.world(Point(lx, ly))
        got = pads["B"][num]
        assert want.distance(Point(got)) < 1e-3, (num, got, (want.x, want.y))


HOLES = """
import json, sys
sys.path.insert(0, sys.argv[1])
import pcbnew
from kicad_script import _place_footprint
board = pcbnew.BOARD()
ds = board.GetDesignSettings()
ds.m_MinThroughDrill, ds.m_ViasMinAnnularWidth = pcbnew.FromMM(0.3), pcbnew.FromMM(0.1)
_place_footprint(board, {}, dict(json.loads(sys.argv[2]), ref="U1", x=0, y=0))
out = []
for p in board.GetFootprints()[0].Pads():
    if p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH:
        d, s = p.GetDrillSize(), p.GetSize(pcbnew.F_Cu)
        out.append([p.GetNumber(), d.x / 1e6, min(s.x - d.x, s.y - d.y) / 2e6])
print(json.dumps(out))
"""
FETCHED = SCRIPT.parents[3] / "data/catalog/fetched/src/C2913198"


@pytest.mark.skipif(not (FETCHED / "C2913198.kicad_mod").exists(), reason="no fetched ESP32")
def test_converted_footprint_holes_meet_the_board_rules() -> None:
    spec = {"lib_dir": str(FETCHED), "name": "C2913198"}
    run = subprocess.run(
        [str(KICAD_PYTHON), "-c", HOLES, str(SCRIPT.parent), json.dumps(spec)],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    # swig prints leak notes for the dropped pads after the result
    holes = json.loads(next(ln for ln in run.stdout.splitlines() if ln.startswith("[")))
    assert all(drill >= 0.3 and ring >= 0.1 for _, drill, ring in holes), holes
