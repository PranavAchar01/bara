"""A handheld's parts compose the way the product reads: the panel nearest the asked size, a
screen window that lies the way the glass does, a D-pad that stays a plus at the board edge, and
a card slot that opens at the rim."""

from __future__ import annotations

import math
from types import SimpleNamespace

from shapely.geometry import box

from bara.board.generic import CABLE_ROLES, _anchor_targets, _keep_cross_inside
from bara.board.layout import Item
from bara.geometry.shell import classify, sites_from_anchors, window_size
from bara.live.compose import closest_size
from bara.live.runner import LiveRunner


def _panel(name: str) -> dict:
    return {"part_id": name, "display_name": name, "summary": ""}


def test_the_nearest_panel_wins_a_size_ask() -> None:
    tft43 = _panel("EA eDIP TFT 4.3 in")
    tft32 = _panel("EA eDIP TFT 3.2 in")
    assert closest_size([tft43, tft32], 2.4) is tft32
    assert closest_size([tft43, tft32], None) is tft43  # no ask: the first stands


def test_a_quarter_turned_panel_gives_a_landscape_window() -> None:
    assert window_size(71.5, 107.3, 90.0) == (107.3, 71.5)
    assert window_size(71.5, 107.3, 270.0) == (107.3, 71.5)
    assert window_size(71.5, 107.3, 0.0) == (71.5, 107.3)


def test_a_dpad_near_the_edge_slides_in_whole() -> None:
    region = box(-104, -61, 104, 61)
    pitch = 9.15
    cx, cy = -100.0, -17.0
    spots = [(cx, cy + pitch), (cx + pitch, cy), (cx, cy - pitch), (cx - pitch, cy)]
    up, right, down, left = _keep_cross_inside(spots, 4.75, region)
    assert math.isclose(up[0], down[0], abs_tol=1e-6)
    assert math.isclose(left[1], right[1], abs_tol=1e-6)
    assert math.isclose(right[0] - left[0], 2 * pitch, abs_tol=1e-6)
    assert math.isclose(up[1] - down[1], 2 * pitch, abs_tol=1e-6)
    assert left[0] - 4.75 > -104


def test_dpad_anchor_targets_form_a_plus() -> None:
    region = box(-104, -61, 104, 61)
    anchor = {
        "slot_id": "dpad",
        "name": "D-pad",
        "mount": "front",
        "pattern": "diamond",
        "centre": [-98.0, 17.0],
        "pitch_mm": 9.0,
        "count": 4,
    }
    items = []
    for i in range(4):
        it = Item(ref=f"SW{i}", role="button", fp=None, x=0, y=0)
        it.meta["slot_id"] = "dpad"
        items.append(it)
    out = _anchor_targets({"anchors": [anchor]}, items, 1.0, region)
    xs = sorted(round(out[id(it)][0], 3) for it in items)
    ys = sorted(round(out[id(it)][1], 3) for it in items)
    assert xs[1] == xs[2] and ys[1] == ys[2]  # up and down share a column, left and right a row
    assert xs[3] - xs[0] == 18.0 and ys[3] - ys[0] == 18.0


def test_a_tight_dpad_pitch_opens_to_the_switch_size() -> None:
    from pathlib import Path

    from bara.board.generic import PART_GAP, _extent
    from bara.board.libs import FootprintInfo, Pad

    fp = FootprintInfo(
        lib="t",
        lib_dir=Path("t.pretty"),
        name="sw",
        pads=[Pad("1", "thru_hole", 0, 0, 1.5, 1.5, ["F.Cu", "B.Cu"])],
        courtyard=(-4.75, -3.75, 4.75, 3.75),
        courtyard_back=None,
        models=[],
    )
    anchor = {
        "slot_id": "dpad",
        "name": "D-pad",
        "mount": "front",
        "pattern": "diamond",
        "centre": [0.0, 0.0],
        "pitch_mm": 7.0,
        "count": 4,
    }
    items = []
    for i in range(4):
        it = Item(ref=f"SW{i}", role="button", fp=fp, x=0, y=0)
        it.meta["slot_id"] = "dpad"
        items.append(it)
    out = _anchor_targets({"anchors": [anchor]}, items, 1.0, box(-60, -60, 60, 60))
    xs = sorted(out[id(it)][0] for it in items)
    assert xs[3] - xs[0] >= 2 * (min(_extent(items[0])) + PART_GAP) - 1e-6


def test_a_card_slot_is_a_port_at_the_rim() -> None:
    assert classify({"name": "microSD slot", "purpose": "game files"}) == "port"
    assert "sd_card" in CABLE_ROLES
    feat = SimpleNamespace(
        ref="U4",
        role="sd_card",
        x=40.0,
        y=-10.0,
        w=14.0,
        d=14.0,
        rot_deg=0.0,
        lib_id="C91145",
        z_range=lambda top: (0.0, 2.0),
    )
    anchor = {
        "slot_id": "sd",
        "name": "microSD slot",
        "mount": "edge",
        "pattern": "single",
        "centre": [42.0, -10.0],
        "edge_normal_deg": 90.0,
        "count": 1,
    }
    sites = sites_from_anchors([anchor], [feat], y_down=False)
    assert sites[0].kind == "port" and sites[0].ref == "U4"


def test_a_card_slot_stays_a_card_slot_in_the_case() -> None:
    from bara.geometry.case import _feature_from_placement

    f = _feature_from_placement(
        {"ref": "U4", "role": "sd_card", "lib_id": "C91145:C91145", "size_mm": [14.0, 14.0]}
    )
    assert f is not None and f.role == "sd_card"  # not re-read from its LCSC id as "other"


def test_the_card_slot_gets_an_anchor_from_the_form_stage() -> None:
    slot = SimpleNamespace(
        chosen={"part_id": "x"},
        quantity=1,
        function_id="storage.sd_card",
        slot_id="sd",
        label="microSD",
        need=None,
    )
    touches = LiveRunner._touches(SimpleNamespace(slots=[slot]))
    assert [t.slot_id for t in touches] == ["sd"]


def test_a_generic_display_slot_is_filled_by_the_named_screen() -> None:
    from bara.live import compose as cmp

    comp = object.__new__(cmp.Composer)
    generic = cmp.Slot("display", "Display", "display.lcd_char", "critical", 1, [])
    named = cmp.Slot("tft", "2.4 in TFT", "display.tft", "critical", 2, [])
    named.chosen = {"part_id": "disp:eadip_tft32", "display_name": "TFT 3.2", "functions": []}
    lamp = cmp.Slot("led", "Charge LED", "display.indicator_led", "critical", 3, [])
    lamp.chosen = {"part_id": "led", "display_name": "LED", "functions": []}
    comp.slots = [generic, named, lamp]
    comp.mark_covered = lambda slot, cover, step, emit: setattr(  # type: ignore[method-assign]
        slot, "covered_by", cover.slot_id
    )
    comp.cover_generic(lambda *a, **k: None)
    assert generic.covered_by == "tft"  # not the charge lamp, which is no screen
    lone = cmp.Slot("display", "Display", "display.lcd_char", "critical", 1, [])
    comp.slots = [lone, lamp]
    comp.cover_generic(lambda *a, **k: None)
    assert lone.covered_by is None
