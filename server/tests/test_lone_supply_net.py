"""A supply pin nothing draws from is left open rather than reported as a one-pin net."""

from __future__ import annotations

from types import SimpleNamespace

from bara.board import _drop_lone_supplies, _nets


def _it(ref: str, pads: dict[str, str]) -> SimpleNamespace:
    return SimpleNamespace(ref=ref, on_pcb=True, pads=pads)


def test_an_unused_3v3_output_is_not_a_net() -> None:
    mcu = _it("U1", {"16": "3V3", "3": "GND", "5": "ROW0"})
    sw = _it("SW1", {"1": "ROW0", "2": "GND"})
    plan = SimpleNamespace(items=[mcu, sw])
    _drop_lone_supplies(plan)  # type: ignore[arg-type]
    names = {n["name"]: len(n["members"]) for n in _nets(plan, "main")}  # type: ignore[arg-type]
    assert names == {"GND": 2, "ROW0": 2}


def test_a_powered_3v3_stays() -> None:
    plan = SimpleNamespace(items=[_it("U1", {"16": "3V3"}), _it("U2", {"1": "3V3"})])
    _drop_lone_supplies(plan)  # type: ignore[arg-type]
    assert [n["name"] for n in _nets(plan, "main")] == ["3V3"]  # type: ignore[arg-type]
