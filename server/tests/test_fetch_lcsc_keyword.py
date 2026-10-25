"""A plain-words LCSC fetch takes the part the block asks for, not its mating connector."""

from __future__ import annotations

from catalog_build.fetch_lcsc import best_stocked


def _row(mpn: str, category: str, stock: int = 100) -> dict:
    return {"lcsc": "C1", "mpn": mpn, "brand": "Maker", "category": category, "stock": stock}


ROWS = [
    _row("FH12-14S-0.5SH(55)", "FFC, FPC (Flat Flexible) Connector Assemblies"),
    _row("HS20HS072RX", "LCD Screen"),
]


def test_a_display_search_skips_the_panel_connector() -> None:
    assert best_stocked(ROWS, "display.tft")["mpn"] == "HS20HS072RX"


def test_an_interconnect_block_may_take_the_connector() -> None:
    assert best_stocked(ROWS, "interconnect.connector")["mpn"] == "FH12-14S-0.5SH(55)"


def _desc(mpn: str, description: str, stock: int) -> dict:
    return {**_row(mpn, "Display Modules", stock), "description": description}


def test_an_unstocked_listing_that_is_the_described_part_still_resolves() -> None:
    rows = [
        _desc("5inch HDMI LCD", "5inch HDMI LCD 800x480", 0),
        _desc("2.9inch e-Paper Module", "2.9inch E-Ink display module", 0),
    ]
    hit = best_stocked(rows, "display.epaper", "2.9 inch e-paper display")
    assert hit is not None and hit["mpn"] == "2.9inch e-Paper Module"


def test_an_unstocked_unrelated_listing_is_not_taken() -> None:
    rows = [_desc("5inch HDMI LCD", "5inch HDMI LCD 800x480", 0)]
    assert best_stocked(rows, "display.epaper", "2.9 inch e-paper display") is None
    assert best_stocked(rows, "display.epaper") is None
