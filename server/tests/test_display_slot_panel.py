"""A display slot takes glass: never the ribbon connector a panel plugs into, a body too
narrow for a viewing area, or a panel far from the asked diagonal."""

from __future__ import annotations

from typing import Any

from bara.live.compose import not_a_panel, wrong_size


def _part(name: str, package: str, w: float, d: float) -> dict[str, Any]:
    return {
        "display_name": name,
        "facets": {"package": package},
        "mechanical": {"bbox_mm": {"min": [0, 0, 0], "max": [w, d, 3]}},
    }


def test_a_ribbon_connector_is_not_a_panel() -> None:
    assert not_a_panel(_part("FPC-05F-40PH20", "FPC-SMD_40P-P0.50", 24.0, 5.5))
    assert not_a_panel(_part("Display header", "PinHeader_1x08", 20.0, 2.5))


def test_real_panels_stay() -> None:
    assert not not_a_panel(_part("2.8 in TFT ILI9341", "LCD-TFT", 50.0, 69.0))
    assert not not_a_panel(_part("0.96 in OLED", "OLED-128x64", 27.0, 27.0))


def test_a_panel_far_from_the_asked_size_is_rejected() -> None:
    tft43 = _part('4.3" TFT 480x272', "LCD-TFT", 105.0, 67.0)
    tft28 = _part('2.8" TFT 240x320', "LCD-TFT", 50.0, 69.0)
    assert wrong_size(tft43, 2.8)
    assert not wrong_size(tft28, 2.8)
    assert not wrong_size(tft43, None)  # no asked size: any panel
