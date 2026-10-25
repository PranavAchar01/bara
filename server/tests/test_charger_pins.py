"""A charger's supply input sits on VBUS and its set pins take resistors, never controller pins."""

from types import SimpleNamespace

from bara.board.generic import _pads_from_pins, _support_parts
from bara.board.layout import Item

# BQ24075 pin table (datasheet): the parts that came back wired to GPIO in a handheld build
BQ24075 = {"2": "BAT", "3": "BAT", "4": "~{CE}", "5": "EN2", "6": "EN1", "9": "~{CHG}",
           "12": "ILIM", "13": "IN", "16": "ISET", "14": "TMR", "8": "VSS"}  # fmt: skip


def _charger() -> Item:
    fp = SimpleNamespace(pads=[SimpleNamespace(number=n) for n in BQ24075])
    return Item("U10", "charger", fp, 0, 0, meta={"pins": BQ24075})  # type: ignore[arg-type]


def test_charger_input_joins_vbus_and_set_pins_get_resistors():
    chg = _charger()
    _pads_from_pins([chg], [])
    assert chg.pads["13"] == "VBUS"
    assert chg.pads["2"] == "VBAT"
    sets = {chg.pads[n] for n in ("12", "16", "14")}
    assert sets == {"SET_ILIM_U10", "SET_ISET_U10", "SET_TMR_U10"}
    support = _support_parts([chg], [])
    to_ground = {it.pads["1"] for it in support if it.pads.get("2") == "GND"}
    assert sets <= to_ground
    assert chg.pads["5"] == "EN2_U10"  # mode pins stay controller signals


def test_ground_pins_typed_as_outputs_become_inputs():
    from bara.board.schematic import _parse, _symbol_from

    text = """(symbol "MCU" (symbol "MCU_0_1"
      (pin power_out line (at 0 0 0) (length 2.54) (name "GND") (number "3"))
      (pin power_out line (at 0 2.54 0) (length 2.54) (name "AGND") (number "33"))
      (pin power_out line (at 0 5.08 0) (length 2.54) (name "3V3OUT") (number "1"))))"""
    sym = _symbol_from(_parse(text), "lib", "test")
    assert sym is not None
    kinds = {p.number: p.kind for p in sym.pins}
    assert kinds == {"3": "power_in", "33": "power_in", "1": "power_out"}
    assert "power_out line (at 0 0" not in str(sym.node)
