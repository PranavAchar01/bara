"""A footprint is named by the part's card, so a maker and series never reach the board,
the schematic or the viewer."""

from __future__ import annotations

from bara.board.generic import _label


def test_the_card_name_labels_the_footprint_not_the_record() -> None:
    part = {"label": "Number keys", "card": {"display_name": "Key switch"}}
    record = {"display_name": "B3F-1000 (OMRON)"}
    assert _label(part, record, "fp") == "Key switch"
    assert _label({"label": "Number keys"}, record, "fp") == "Number keys"
    assert _label({}, {}, "fp") == "fp"


def test_natural_pin_order_mixes_numbers_and_letters():
    from bara.board.schematic import _natural

    assert sorted(["A2", "10", "2", "A1", "1"], key=_natural) == ["1", "2", "10", "A1", "A2"]
