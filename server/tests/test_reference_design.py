"""Reference designs match by function blocks and are reused only under a licence that allows
it. No network: the board file fetch is stubbed."""

from __future__ import annotations

import asyncio
from typing import Any

from bara.live import reference_design as R

PCB = """(kicad_pcb (version 20221018)
  (footprint "Battery:BatteryHolder_Keystone_1042_1x18650" (layer "F.Cu"))
  (footprint "Button_Switch_SMD:SW_SPST_TL3342" (layer "F.Cu"))
  (footprint "Resistor_SMD:R_0603_1608Metric" (layer "F.Cu"))
)"""


def test_footprints_are_read_from_both_board_formats() -> None:
    assert R.footprints(PCB)[0] == "Battery:BatteryHolder_Keystone_1042_1x18650"
    old = "(module Button_Switch_SMD:SW_SPST_TL3342 (layer F.Cu))"
    assert R.footprints(old) == ["Button_Switch_SMD:SW_SPST_TL3342"]


def test_match_is_by_function_blocks_and_ignores_passives() -> None:
    cov, matched, by_fn = R.score(R.footprints(PCB), ["power.battery", "sense.light"])
    assert matched == ["power.battery"] and cov == 0.5
    assert not any(fn.startswith("component.") for fn in by_fn)


def _run(designs: list[dict[str, Any]], wanted: list[str], monkeypatch: Any) -> R.Match | None:
    async def fetch(client: Any, repo: str, path: str) -> str:
        return PCB

    monkeypatch.setattr(R, "_fetch", fetch)
    return asyncio.run(R.match(designs, wanted))


def test_reusable_match_prefers_its_footprints(monkeypatch: Any) -> None:
    d = {"repo": "https://github.com/a/b", "kicad_pcb": "b.kicad_pcb", "licence": "CERN-OHL-S-2.0"}
    m = _run([d], ["power.battery", "input.button"], monkeypatch)
    assert m is not None and m.reusable and m.coverage == 1.0
    pref = R.preferred(m)
    assert "Battery:BatteryHolder_Keystone_1042_1x18650" in pref["power.battery"]


def test_a_design_with_no_licence_is_compared_only(monkeypatch: Any) -> None:
    d = {"repo": "https://github.com/a/b", "kicad_pcb": "b.kicad_pcb", "licence": "none stated"}
    m = _run([d], ["power.battery", "input.button"], monkeypatch)
    assert m is not None and not m.reusable and R.preferred(m) == {}


def test_paths_outside_the_repo_are_never_fetched() -> None:
    async def go() -> str | None:
        import httpx

        async with httpx.AsyncClient() as c:
            return await R._fetch(c, "https://github.com/a/b", "../../etc/x.kicad_pcb")

    assert asyncio.run(go()) is None
