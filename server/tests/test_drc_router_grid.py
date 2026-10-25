"""A track that lands a micron inside its clearance (router grid rounding) is not a DRC error."""

from bara.board.kicad import _within_router_grid


def _v(actual: str) -> dict:
    return {"type": "clearance", "description": f"Clearance violation ( clearance 0.1500 mm; actual {actual} mm)"}


def test_rounding_shortfall_is_ignored() -> None:
    assert _within_router_grid(_v("0.1492"))


def test_real_shortfall_still_counts() -> None:
    assert not _within_router_grid(_v("0.1200"))
    assert not _within_router_grid({"type": "shorting_items", "description": "x"})
