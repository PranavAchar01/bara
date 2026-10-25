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
