"""A controller with no pin map in its record takes the symbol its footprint library ships, so
the pin budget and the board planner both see its GPIO."""

from __future__ import annotations

import pytest

from bara.board.generic import gpio_pins
from bara.board.libs import LIBRARIES, library_symbol

if not LIBRARIES.get("marbastlib", {}).get("symbols"):
    pytest.skip("marbastlib is not installed", allow_module_level=True)


def test_the_footprint_library_names_its_symbol() -> None:
    lib, _, name = library_symbol("marbastlib", "SuperMini_nRF52840_H_USBup") or ("", "", "")
    assert (lib, name) == ("marbastlib", "SuperMini_nRF52840")


def test_a_bare_controller_record_has_gpio() -> None:
    record = {"part_id": "mod:supermini_nrf52840",
              "footprint": "marbastlib-xp-promicroish:SuperMini_nRF52840_H_USBup"}  # fmt: skip
    assert (gpio_pins(record) or 0) >= 18  # enough for a d-pad, four face buttons and more
