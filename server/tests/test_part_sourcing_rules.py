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
