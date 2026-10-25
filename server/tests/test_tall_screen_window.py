"""A display module taller than the shell gets a closed boss; its window must cut through the
boss, or a thin lid is left floating over the screen."""

from __future__ import annotations

import json
from pathlib import Path

from bara.geometry import enclose_report

CASE = Path(__file__).parent / "fixtures" / "tall_screen_handheld_case.json"


def test_tall_screen_window_leaves_no_floating_lid() -> None:
    d = json.loads(CASE.read_text())
    r = enclose_report(d["board"], d["parts"], d["brief"])
    failed = [c["message"] for c in r.checks if c["status"] == "fail"]
    assert failed == []
    assert len(r.world_bezel.decompose()) == 1
