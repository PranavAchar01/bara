"""Real KiCad + Freerouting builds of the three acceptance briefs (P1, P2, P3).

Slow (one to two minutes cold, under a second from the board cache) and needs KiCad 10,
Java and the Freerouting jar, so it only runs with BARA_BOARD_INTEGRATION=1.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from bara.board import kicad as K
from bara.board.libs import KICAD_PYTHON, LIBRARIES

if os.environ.get("BARA_BOARD_INTEGRATION") != "1":
    pytest.skip("set BARA_BOARD_INTEGRATION=1 to run real board builds", allow_module_level=True)
if not (
    Path(K.KICAD_CLI).exists()
    and KICAD_PYTHON.exists()
    and K.FREEROUTING_JAR.exists()
    and (Path(K.JAVA).exists() or shutil.which(K.JAVA))
    and all(lib["footprints"] is None or lib["footprints"].exists() for lib in LIBRARIES.values())
):
    pytest.skip(
        "KiCad, Java, Freerouting or the part libraries are missing", allow_module_level=True
    )

from bara.board import build_board  # noqa: E402
from bara.geometry.case import enclose_report  # noqa: E402

P1 = {
    "prompt": "wireless split keyboard, 38 keys, sage and cream, red trackball on the right "
    "thumb, knob top left, tented",
    "device_class": "keyboard",
    "layout_style": "split",
    "split": True,
    "key_count": 38,
    "wireless": True,
    "tented": True,
    "features": [
        {"kind": "trackball", "hint": "right thumb"},
        {"kind": "knob", "hint": "top left"},
    ],
}
P2 = {
    "prompt": "34-key split, no trackball, two knobs, black and orange",
    "device_class": "keyboard",
    "layout_style": "split",
    "split": True,
    "key_count": 34,
    "wireless": True,
    "knob_count": 2,
    "features": ["knob", "knob"],
}
P3 = {
    "prompt": "small 5x4 macropad with a knob and a screen, white",
    "device_class": "keyboard",
    "layout_style": "macropad",
    "key_count": 20,
    "rows": 4,
    "cols": 5,
    "wireless": True,
    "features": ["knob", "screen"],
}


@pytest.mark.parametrize(
    ("brief", "names"),
    [(P1, {"left", "right", "right_sensor"}), (P2, {"left", "right"}), (P3, {"main"})],
    ids=["P1", "P2", "P3"],
)
def test_brief_routes_clean_and_encloses(brief: dict, names: set[str]) -> None:
    res = build_board(brief, [])
    assert {bd["name"] for bd in res["boards"]} == names
    for bd in res["boards"]:
        drc = bd["drc"]
        assert drc["errors"] == 0, f"{bd['name']}: {drc['by_type']}"
        assert drc["unconnected"] == 0, f"{bd['name']}: open nets {drc['unconnected_nets']}"
        assert Path(bd["kicad_pcb_path"]).exists()
        assert bd["glb"]["url"].startswith("/assets/")
        # the case is built from this real board; no part may cut into it
        rep = enclose_report(bd, [], brief)
        bad = [(c["rule_id"], c["message"]) for c in rep.checks if c["status"] == "fail"]
        assert not bad, f"{bd['name']}: {bad}"
