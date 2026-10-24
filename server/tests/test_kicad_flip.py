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
