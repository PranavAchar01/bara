"""A named part the stock KiCad library carries comes from there, even under a reel suffix."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from bara.live import completeness as cp
from bara.live.completeness import Need
from bara.live.fetch import Overlay, Resolver, _names_part, recipe_for, stock_primitive

SYMBOLS = ["DRV8833PW", "DRV8833PWP", "DRV8833RTY"]


class Source:
    name = "stub"

    def query(self, *a: Any, **k: Any) -> list[dict[str, Any]]:
        return []

    def get_part(self, part_id: str) -> dict[str, Any]:
        raise KeyError(part_id)

    def search(self, text: str, kind: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        # whole-word index: DRV8833PWPR finds nothing, its stems do
        return [
            {"part_id": f"kicadgen:kicad:sym:Driver_Motor:{s}", "name": s, "fp_ok": True}
            for s in SYMBOLS
            if s.startswith(text)
        ]


def test_reel_suffix_finds_the_powerpad_symbol(tmp_path: Path) -> None:
    need = cp.Need(
        "drv", "output.motor_driver", "Motor driver", terms=("DRV8833PWPR",), kicad=("DRV8833PWPR",)
    )
    r = Resolver(Overlay(Source()), cli=lambda *a: (1, "no"), fetched_path=tmp_path / "f.jsonl")
    part = r.generated(need)
    assert part is not None and part["part_id"].endswith(":DRV8833PWP")


@pytest.mark.parametrize(
    ("query", "name", "ok"),
    [
        ("AP2112K-3.3TRG1", "AP2112K-3.3", True),
        ("DRV8838DSGR", "DRV8838", True),
        ("USBLC6-2SC6", "USBLC6-2SC6", True),
        ("ATmega328", "ATmega32", False),  # a digit suffix is another part
        ("LM3170", "LM317", False),
        ("MAX17048G+T10", "MAX1704", False),
    ],
)
def test_suffix_rule(query: str, name: str, ok: bool) -> None:
    assert _names_part(query, name) is ok


@pytest.mark.parametrize(
    ("label", "recipe"),
    [
        ("charge status led", "indicator LED"),
        ("power/standby status led (bicolor)", "bicolor LED"),
        ("Shoulder bumper switches", "tactile switch"),
        ("Face buttons A/B/X/Y", "tactile switch"),
    ],
)
def test_generic_parts_are_stock_first(label: str, recipe: str) -> None:
    need = Need("k", "x", label)
    assert recipe_for(need)[0] == recipe
    assert stock_primitive(need)


def test_a_haptic_driver_is_not_a_stock_primitive() -> None:
    assert not stock_primitive(Need("k", "output.haptic", "haptic driver"))


def test_a_cabled_particulate_sensor_gets_its_socket_not_a_header() -> None:
    pm = Need("k", "sense.particulate", "Laser particulate matter sensor module (PMSA003I)")
    assert recipe_for(pm)[0] == "socket for a cabled particulate sensor"
    assert not stock_primitive(pm)  # tried only after LCSC has no part
    header = Need("k", "sense.particulate", "PM2.54 pin header")
    assert recipe_for(header) is None
    fan = recipe_for(Need("k", "output.fan", "particulate filter fan"))
    assert fan[0] == "wire-to-board connector for an off-board load"  # not a sensor block
