"""Part sourcing rules that hold for every device: a block's function decides which generic
KiCad primitive may stand in for it, and a part whose catalog model was never made is drawn
from its own footprint's model (or the same body's sibling)."""

from __future__ import annotations

import pytest

from bara.kicad_generated import KicadIndex
from bara.live.completeness import Need
from bara.live.compose import _model_from_footprint
from bara.live.fetch import recipe_for, stock_primitive


def need(function_id: str, label: str, requirement: str = "") -> Need:
    return Need(key="k", function_id=function_id, label=label, requirement=requirement)


def test_a_screen_whose_words_mention_its_backlight_is_never_an_led() -> None:
    screen = need("display.tft", "2.8 in color TFT LCD", "ILI9341, white LED backlight")
    assert recipe_for(screen) is None
    assert not stock_primitive(screen)


def test_a_chip_named_after_what_it_drives_is_not_that_primitive() -> None:
    driver = need("display.indicator_led", "TFT white LED backlight boost driver")
    assert not stock_primitive(driver)
    assert not stock_primitive(need("input.button", "button debounce controller"))


def test_plain_primitives_still_come_from_the_library() -> None:
    led = recipe_for(need("display.indicator_led", "Charge status LED"))
    assert led is not None and led[0] == "indicator LED"
    sw = recipe_for(need("input.button", "Reset and boot buttons"))
    assert sw is not None and sw[0] == "tactile switch"
    load = recipe_for(need("output.haptic", "vibration motor module"))
    assert load is not None and load[0].startswith("wire-to-board")


index = KicadIndex.open()
needs_index = pytest.mark.skipif(index is None, reason="kicad index not built")


@needs_index
def test_a_footprint_without_a_model_borrows_the_same_body() -> None:
    assert index is not None
    lent = index.model_footprint("Package_DFN_QFN:VQFN-16-1EP_3x3mm_P0.5mm_EP1.68x1.68mm")
    assert lent is not None and "16-1EP_3x3mm" in lent
    own = index.model_footprint("LED_SMD:LED_0603_1608Metric")
    assert own is not None and own.endswith("LED_0603_1608Metric")
    assert index.model_footprint("Package_DFN_QFN:NoSuchBody_1x1mm") is None


@needs_index
def test_a_missing_catalog_model_is_replaced_by_the_footprint_model() -> None:
    part = {"footprint": "Package_DFN_QFN:VQFN-16-1EP_3x3mm_P0.5mm_EP1.68x1.68mm"}
    assets = [{"kind": "glb", "url": "/assets/parts/never_made.glb", "status": "missing"}]
    _model_from_footprint(part, assets)
    assert assets[0]["url"].startswith("/assets/parts/kicad_gen/")
    assert "16-1EP_3x3mm" in assets[0]["url"]
    kept = [{"kind": "glb", "url": "/assets/parts/never_made.glb", "status": "missing"}]
    _model_from_footprint({}, kept)  # no footprint: nothing to borrow
    assert kept[0]["url"] == "/assets/parts/never_made.glb"


def test_the_form_is_told_each_control_part_real_size() -> None:
    from bara.live import form as fm
    from bara.live.runner import _footprint_size

    screen = {"mechanical": {"bbox_mm": {"min": [-25.0, -35.0, 0], "max": [25.0, 35.0, 4]}}}
    size = _footprint_size(screen)
    assert size == (50.0, 70.0)
    assert _footprint_size({}) is None
    text = fm._prompt("a handheld", [fm.Touch("scr", "Screen", "display.tft", 1, (), size)], [], "")
    assert "each 50 x 70 mm" in text


def test_a_chip_package_is_never_the_panel() -> None:
    from bara.live.compose import is_chip

    assert is_chip({"facets": {"package": "TSSOP-56"}, "datasheet": ""})
    assert not is_chip({"facets": {"package": "Module"}, "datasheet": "TFT LCD module"})


def test_case_anchors_follow_the_board_record_frame() -> None:
    """A y-up record (build space) takes form anchors as they are; a KiCad y-down one mirrors
    them. Mixing the two put a handheld's screen hole by its controls and its D-pad up top."""
    from bara.geometry.shell import sites_from_anchors

    screen = [{"name": "Main screen", "mount": "front", "pattern": "single",
               "centre": [0, 33], "count": 1}]  # fmt: skip
    assert sites_from_anchors(screen, [], y_down=False)[0].y == 33
    assert sites_from_anchors(screen, [], y_down=True)[0].y == -33


def test_a_button_cap_never_lands_on_a_card_slot() -> None:
    """A handheld's A button anchor landed beside its microSD slot, claimed it, and the case cut
    an 18 mm cap over the slot with the card's board showing through. Slots, sockets and
    speakers are never pressed: the cap goes to the switch."""
    from bara.geometry.case import Feature
    from bara.geometry.shell import sites_from_anchors

    sd = Feature(
        ref="u_microsdslo",
        role="other",
        x=0,
        y=-102,
        rot_deg=0,
        side="top",
        height=2,
        w=18,
        d=15,
        lib_id="conn:microsd_hirose_dm3at",
        touch=True,
    )
    sw = Feature(ref="u_actionbutt[1]", role="other", x=14, y=-104, rot_deg=0, side="top",
                 height=5, w=6, d=6, lib_id="btn:tact_6mm_tht", touch=True)  # fmt: skip
    a = [{"name": "A button", "mount": "front", "pattern": "single", "centre": [3, -102],
          "count": 1}]  # fmt: skip
    site = sites_from_anchors(a, [sd, sw], y_down=False)[0]
    assert site.ref != "u_microsdslo"


def test_a_speaker_gets_sound_slots_and_a_named_led_stays_a_light() -> None:
    from bara.geometry.shell import classify

    assert classify({"name": "Speaker grille", "purpose": "sound out"}) == "grille"
    assert (
        classify({"name": "Status LEDs", "purpose": "charge state next to the display"}) == "light"
    )
