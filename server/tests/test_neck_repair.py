"""A Freerouting neck below the minimum width is widened and slid clear of the pad it passed."""

from __future__ import annotations

import json
import subprocess

import pytest

from bara.board.kicad import SCRIPT
from bara.board.libs import KICAD_PYTHON

if not KICAD_PYTHON.exists():
    pytest.skip("KiCad is not installed", allow_module_level=True)

PROBE = """
import json, sys
sys.path.insert(0, sys.argv[1])
import pcbnew
from kicad_script import _repair_necks, _set_rules, _vec, _mm
board = pcbnew.BOARD()
_set_rules(board, {"clearance_mm": 0.15, "track_mm": 0.2, "via_mm": 0.5, "via_drill_mm": 0.3,
                   "min_track_mm": 0.15, "edge_clearance_mm": 0.3})
nets = {}
for name in ("N", "P"):
    nets[name] = pcbnew.NETINFO_ITEM(board, name)
    board.Add(nets[name])
fp = pcbnew.FOOTPRINT(board)
pad = pcbnew.PAD(fp)
pad.SetShape(pcbnew.PAD_SHAPE_RECTANGLE)
pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
pad.SetLayerSet(pad.SMDMask())
pad.SetSize(pcbnew.F_Cu, _vec(0.3, 0.3))
fp.Add(pad)
board.Add(fp)
pad.SetPosition(_vec(0.5, 0.36))
pad.SetNet(nets["P"])
def track(x0, x1, w):
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(_vec(x0, 0)); t.SetEnd(_vec(x1, 0)); t.SetWidth(_mm(w))
    t.SetLayer(pcbnew.F_Cu); t.SetNet(nets["N"]); board.Add(t)
    return t
left, neck, right = track(-1, 0, 0.2), track(0, 1, 0.12), track(1, 2, 0.2)
fixed = _repair_necks(board)
shape = pad.GetEffectiveShape(pcbnew.F_Cu)
clear = not neck.GetEffectiveShape(pcbnew.F_Cu).Collide(shape, _mm(0.15))
print(json.dumps({"fixed": fixed, "w": neck.GetWidth() / 1e6, "y": neck.GetStart().y / 1e6,
                  "joined": left.GetEnd() == neck.GetStart() and right.GetStart() == neck.GetEnd(),
                  "clear": clear}))
"""


def test_a_neck_is_widened_and_slid_clear() -> None:
    proc = subprocess.run(
        [str(KICAD_PYTHON), "-c", PROBE, str(SCRIPT.parent)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["fixed"] == 1
    assert out["w"] == pytest.approx(0.15)
    assert out["y"] < 0  # slid away from the pad above it
    assert out["joined"] and out["clear"]
