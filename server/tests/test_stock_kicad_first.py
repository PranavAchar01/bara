"""A named part the stock KiCad library carries comes from there, even under a reel suffix."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from bara.live import completeness as cp
from bara.live.fetch import Overlay, Resolver

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
