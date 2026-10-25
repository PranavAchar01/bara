"""A track that lands a micron inside its clearance (router grid rounding) is not a DRC error."""

from bara.board.kicad import _within_router_grid


def _v(actual: str) -> dict:
    return {"type": "clearance", "description": f"Clearance violation ( clearance 0.1500 mm; actual {actual} mm)"}


def test_rounding_shortfall_is_ignored() -> None:
    assert _within_router_grid(_v("0.1492"))


def test_real_shortfall_still_counts() -> None:
    assert not _within_router_grid(_v("0.1200"))
    assert not _within_router_grid({"type": "shorting_items", "description": "x"})


def _items(*d: str) -> dict:
    return {"type": "clearance", "items": [{"description": x} for x in d]}


def test_pad_to_pad_inside_one_footprint_is_the_part_own_geometry() -> None:
    from bara.board.kicad import _inside_one_footprint

    assert _inside_one_footprint(_items("PTH pad [<no net>] of U3", "Pad 3 [GND] of U3 on F.Cu"))
    assert not _inside_one_footprint(_items("Pad 3 [GND] of U3 on F.Cu", "Pad 1 [VCC] of U4 on F.Cu"))
    assert not _inside_one_footprint(_items("PTH pad 16 [<no net>] of U4", "Track [PIN15_J1] on B.Cu"))
