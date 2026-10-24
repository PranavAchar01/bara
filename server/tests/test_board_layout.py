"""Fast checks of the BOARD layout planner (no KiCad run, no router)."""

from __future__ import annotations

import itertools

import pytest
from shapely.geometry import Point, box

from bara.board.libs import LIBRARIES

if not all(LIBRARIES[k]["footprints"].exists() for k in ("kicad", "kiswitch", "marbastlib")):
    pytest.skip("KiCad libraries not installed under bara-sources", allow_module_level=True)

from bara.board.layout import plan_boards  # noqa: E402

P1 = {
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
    "layout_style": "split",
    "split": True,
    "key_count": 34,
    "wireless": True,
    "knob_count": 2,
    "features": ["knob", "knob"],
}
P3 = {
    "layout_style": "macropad",
    "key_count": 20,
    "wireless": True,
    "rows": 4,
    "cols": 5,
    "features": ["knob", "screen"],
}


def _plans(brief: dict) -> dict:
    _, plans, _ = plan_boards(brief)
    return {p.name: p for p in plans}


@pytest.mark.parametrize("brief", [P1, P2, P3, {**P1, "switch_family": "mx"}])
def test_parts_do_not_overlap_and_fit_the_outline(brief: dict) -> None:
    for plan in _plans(brief).values():
        on_pcb = [it for it in plan.items if it.on_pcb and it.fp is not None]
        for a, b in itertools.combinations(on_pcb, 2):
            if a.side != b.side:
                continue
            overlap = a.world(a.local_poly()).intersection(b.world(b.local_poly())).area
            assert overlap < 0.05, f"{plan.name}: {a.ref} courtyard overlaps {b.ref}"
        caps = [
            it.world(box(-w / 2, -h / 2, w / 2, h / 2))
            for it in plan.items
            if it.role == "switch"
            for w, h in [it.meta["keycap_mm"]]
        ]
        for i, j in itertools.combinations(range(len(caps)), 2):
            assert caps[i].intersection(caps[j]).area < 0.5, f"{plan.name}: keycaps {i} {j}"
        grown = plan.outline.buffer(0.01)
        for it in on_pcb:
            assert grown.contains(it.envelope()), f"{plan.name}: {it.ref} leaves the outline"


def test_key_counts_and_controller_upgrade() -> None:
    plans = _plans(P1)
    assert {"left", "right", "right_sensor"} <= set(plans)
    n = sum(1 for p in plans.values() for it in p.items if it.role == "switch")
    assert n == 38
    # the trackball half needs more GPIO than the XIAO has, so it moves to the nice!nano
    assert plans["right"].controller["id"] == "nice_nano_v2"
    assert plans["left"].controller["id"] == "xiao_nrf52840"
    budget = plans["right"].pin_budget
    assert budget["needed"] <= budget["available"]


def test_macropad_has_screen_and_encoder_inside_the_board() -> None:
    main = _plans(P3)["main"]
    roles = [it.role for it in main.items]
    assert roles.count("switch") == 20
    assert "screen" in roles and "encoder" in roles
    enc = next(it for it in main.items if it.role == "encoder")
    assert main.outline.contains(Point(*enc.centre()).buffer(10.0))


def test_right_half_is_mirrored() -> None:
    plans = _plans(P2)
    lx = [it.x for it in plans["left"].items if it.role == "switch"]
    rx = [it.x for it in plans["right"].items if it.role == "switch"]
    assert len(lx) == len(rx) == 17
    # same key cloud, reflected: spans match to within a key
    assert abs((max(lx) - min(lx)) - (max(rx) - min(rx))) < 1.0
