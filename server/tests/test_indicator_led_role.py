"""An indicator LED is a light the case shows through a round hole, not a screen it frames."""

from __future__ import annotations

from bara.board.generic import _role
from bara.geometry.case import _feature_from_placement, _hidden


def _rec(fid: str) -> dict:
    return {"functions": [{"function_id": fid, "primary": True}]}


def test_display_roles() -> None:
    assert _role(_rec("display.indicator_led")) == "indicator_led"
    assert _role(_rec("display.oled")) == "screen"
    assert _role(_rec("display.tft")) == "screen"


def test_an_led_shows_through_the_shell() -> None:
    f = _feature_from_placement(
        {"ref": "D4", "role": "indicator_led", "size_mm": [1.6, 0.8], "lib_id": "LED_SMD:LED_0603"}
    )
    assert f is not None and f.role == "indicator_led"
    assert not _hidden(f)
