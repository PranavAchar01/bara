"""A slot is filled by what a part is, not only by the facets it happens to carry: a digit
from the KiCad library is a seven-segment display by its function, a driver chip tagged with
a display's function is never the display, and the generic display the brief implied is the
same block as the named display the device concept asked for."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from bara.live.compose import Composer, Slot, _function_names, is_chip, not_a_panel


def _part(pid: str, fn: str, facets: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "part_id": pid,
        "display_name": pid,
        "functions": [{"function_id": fn, "primary": True}],
        "facets": facets or {},
    }


DIGIT = _part("kicad:7seg_digit", "display.seven_segment", {"package": "DIP-10"})
DRIVER = _part("lcsc:tm1637", "display.seven_segment", {"package": "SOP-20_L12.8-W7.5"})
OLED = _part("lcsc:oled", "display.oled", {"display_type": "oled"})


def test_a_part_with_no_facet_is_the_type_its_function_names() -> None:
    assert _function_names(DIGIT, "display_type", "eq", "seven_segment")
    assert not _function_names(DIGIT, "display_type", "eq", "oled")
    assert not _function_names(OLED, "display_type", "eq", "seven_segment")  # its own facet rules


def test_a_driver_chip_is_not_glass() -> None:
    assert is_chip(DRIVER) or not_a_panel(DRIVER)
    assert not (is_chip(DIGIT) or not_a_panel(DIGIT))


def _slot(sid: str, fn: str, chosen: dict[str, Any] | None, need: object = None) -> Slot:
    s = Slot(sid, sid, fn, "critical", 0, [], chosen=chosen)
    s.need = need  # type: ignore[assignment]
    return s


def test_the_generic_display_is_covered_by_the_named_one() -> None:
    generic = _slot("display", "display.seven_segment", None)
    named = _slot("segment_glass", "display.seven_segment", DIGIT, need=object())
    button = _slot("buttons", "input.button", None)
    marked: list[tuple[str, str]] = []
    fake = SimpleNamespace(
        slots=[generic, named, button],
        mark_covered=lambda s, c, step, emit: marked.append((s.slot_id, c.slot_id)),
    )
    Composer.cover_generic(fake, lambda *a, **k: None)  # type: ignore[arg-type]
    assert marked == [("display", "segment_glass")]
