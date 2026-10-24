"""The edge keep-out band is a ring: its hole is a hole, so the board's middle stays routable."""

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
from kicad_script import _rule_area, _mm
board = pcbnew.BOARD()
outer = [[0, 0], [50, 0], [50, 30], [0, 30]]
hole = [[0.5, 0.5], [49.5, 0.5], [49.5, 29.5], [0.5, 29.5]]
_rule_area(board, outer, [hole], ["F.Cu"], "edge_band_0")
ring = board.Zones()[0].Outline()
inside = lambda x, y: ring.Contains(pcbnew.VECTOR2I(_mm(x), _mm(y)))
print(json.dumps({"holes": ring.HoleCount(0), "outer_pts": ring.Outline(0).PointCount(),
                  "middle": inside(25, 15), "edge": inside(0.2, 15)}))
"""


def test_the_band_hole_stays_a_hole() -> None:
    proc = subprocess.run(
        [str(KICAD_PYTHON), "-c", PROBE, str(SCRIPT.parent)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["holes"] == 1 and out["outer_pts"] == 4
    assert out["edge"] and not out["middle"]  # only the band is kept out
