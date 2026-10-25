"""The main cell's chemistry comes from the part that charges or runs from it, never from a
second cell holder (a backup coin cell) elsewhere on the board."""

from __future__ import annotations

from bara.live.compose import _chemistry_fits, _chemistry_of, _holds_cell


def _cell(pid: str, chem: str | None, fn: str = "power.battery", iface: bool = True) -> dict:
    return {
        "part_id": pid,
        "functions": [{"function_id": fn, "primary": True}],
        "interfaces": (
            [{"type": "battery", "role": "requires", "params": {"chemistry": chem}}]
            if iface and chem
            else []
        ),
        "facets": {"chemistry": chem} if chem else {},
    }


COIN = _cell("coin", "coin_lithium", "power.coin_cell")
POUCH = _cell("pouch", "lipo")
CELL_18650 = _cell("18650", "liion")
NINE_VOLT_UNKNOWN = _cell("9v", None)
JST = {
    "part_id": "jst",
    "functions": [
        {"function_id": "interconnect.connector", "primary": True},
        {"function_id": "power.battery", "primary": False},
    ],
}
CHARGER = {"part_id": "chg", "functions": [{"function_id": "power.charger", "primary": True}],
           "facets": {"chemistry": "lipo"}}  # fmt: skip


def test_the_lithium_ion_family_is_one_chemistry() -> None:
    assert _chemistry_of(POUCH) == _chemistry_of(CELL_18650) == _chemistry_of(CHARGER) == "li_ion"


def test_a_coin_cell_holder_holds_its_own_cell() -> None:
    assert _holds_cell(COIN) and _holds_cell(POUCH)
    assert not _holds_cell(JST) and not _holds_cell(CHARGER)


def test_the_charger_chemistry_keeps_cells_of_its_kind_and_connectors() -> None:
    want = _chemistry_of(CHARGER)
    assert _chemistry_fits(POUCH, want) and _chemistry_fits(CELL_18650, want)
    assert _chemistry_fits(JST, want)  # wires a cell off the board
    assert not _chemistry_fits(COIN, want)
    assert not _chemistry_fits(NINE_VOLT_UNKNOWN, want)  # a holder of unknown kind
