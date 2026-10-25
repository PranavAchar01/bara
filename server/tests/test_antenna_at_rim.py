"""A module whose antenna keep-out is part of its courtyard (KiCad ESP32-S3-WROOM-1: 48 x 41 mm
with the clearance, 18 x 25.5 mm of body) goes to the board edge with the keep-out facing out,
so only its body has to fit the outline."""

from __future__ import annotations

from bara.board.generic import form_region, place_in_form
from bara.board.layout import Item
from bara.board.libs import find_footprint

PILL = [(-60, -20), (-40, -30), (40, -30), (60, -20), (60, 20), (40, 30), (-40, 30), (-60, 20)]


def test_a_module_antenna_hangs_past_the_edge() -> None:
    fp = find_footprint("RF_Module:ESP32-S3-WROOM-1")
    assert fp.keepouts and fp.courtyard[2] - fp.courtyard[0] > 40  # the clearance is courtyard
    mcu = Item("U1", "mcu", fp, 0, 0, 0, "top", meta={"slot_id": "controller"})
    pf = {"silhouette": [list(p) for p in PILL], "anchors": []}
    log: list[str] = []
    place_in_form([mcu], mcu, pf, log)
    assert pf["fit_report"]["ok"], log
    region = form_region(pf, 1.0)
    assert region.buffer(-0.4).contains(mcu.body_poly())
    keep = mcu.keepout_poly()
    assert keep is not None and keep.difference(region).area > 0.5 * keep.area  # mostly outside
