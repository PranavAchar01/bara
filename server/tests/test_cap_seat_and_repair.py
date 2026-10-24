"""A knob or keycap rides its host's shaft (never a wired off-board module), and a failing
required check goes back for repair until it passes or a round makes no progress."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from bara.board.generic import CAP_ROLES, _role
from bara.live.runner import LiveRunner, _seat_caps


def _rec(fid: str, z: float = 8.0) -> dict[str, Any]:
    return {
        "functions": [{"function_id": fid, "primary": True}],
        "mechanical": {"bbox_mm": {"min": [0, 0, 0], "max": [10, 10, z]}},
    }


def _move(x: float, z: float) -> dict[str, Any]:
    return {"placement": {"position_mm": [x, 0.0, z], "rotation_deg": [0.0, 0.0, 0.0]}}


def test_a_knob_is_a_cap_not_a_module() -> None:
    assert _role(_rec("mech.knob")) in CAP_ROLES
    assert _role(_rec("mech.keycap")) in CAP_ROLES


def test_caps_sit_on_the_matching_shaft() -> None:
    parts = [
        {"instance_id": "u_enc", "label": "Rotary encoder", "quantity": 2,
         "record": _rec("input.rotary_encoder", 20.0)},
        {"instance_id": "u_stick", "label": "Analog thumbsticks with click", "quantity": 2,
         "record": _rec("input.joystick", 12.0)},
        {"instance_id": "u_cap", "label": "Thumbstick caps", "quantity": 2,
         "record": _rec("mech.knob")},
    ]  # fmt: skip
    moves = {"u_enc": _move(-25.0, 1.6), "u_stick": _move(-47.0, 1.6)}
    (cap,) = _seat_caps(parts, moves)
    assert cap["instance_id"] == "u_cap"
    x, _, z = cap["placement"]["position_mm"]
    assert x == -47.0 and z == 1.6 + 12.0  # on top of the stick, not inside it


class _Run:
    def __init__(self, fails: list[str | None]) -> None:
        self.fails = fails
        self.state: dict[str, Any] = {"checks": []}
        self.events: list[str] = []
        self.render_once()

    def render_once(self) -> None:
        msg = self.fails.pop(0) if self.fails else None
        self.state["checks"].append(
            {"rule_id": "mech.fit.collision", "status": "fail" if msg else "pass",
             "message": msg or "No keep-out overlaps."}
        )  # fmt: skip

    def emit(self, kind: str, payload: Any, **_: Any) -> None:
        self.events.append(kind)


def _runner() -> LiveRunner:
    r = LiveRunner.__new__(LiveRunner)

    async def place(run: _Run, *a: Any) -> None:
        return None

    async def enclose(*a: Any) -> None:
        return None

    async def board_stage(run: _Run, board: Any, *a: Any) -> None:
        return None

    r.place = place  # type: ignore[method-assign]
    r.enclose = enclose  # type: ignore[method-assign]
    r.board_stage = board_stage  # type: ignore[method-assign]
    r.firmware = lambda *a: None  # type: ignore[method-assign]
    r.render = lambda run, *a: run.render_once()  # type: ignore[method-assign]
    r._warn = lambda run, *a: run.events.append("repair")  # type: ignore[method-assign]
    return r


def _repair(run: _Run) -> Any:
    return asyncio.run(_runner().repair(run, {}, None, SimpleNamespace(), None, {}))  # type: ignore[arg-type]


def test_a_failure_is_sent_back_until_it_passes() -> None:
    run = _Run(["2 overlaps: U3/M1", "1 overlaps: U3/M1"])  # progress, then a pass
    assert _repair(run) is None
    assert run.events.count("repair") == 2


def test_the_same_failure_twice_is_reported_as_impossible() -> None:
    run = _Run(["2 overlaps: U3/M1"] * 10)
    failure = _repair(run)
    assert failure is not None and "Could not be built after 1 repair round" in failure["message"]
    assert run.events.count("repair") == 1


def test_a_repairable_fault_is_sent_back_but_not_fatal() -> None:
    run = _Run([])
    run.state["checks"] = [
        {"rule_id": "mech.access.panel", "check_key": "mech.access.panel:encoder_U1",
         "status": "fail", "message": "Bezel overhangs encoder U1"},
        {"rule_id": "mech.access.panel", "check_key": "mech.access.panel:usb_U17",
         "status": "pass", "message": "ok"},
    ]  # fmt: skip
    assert _repair(run) is None  # reported, sent back once, never fails the build
    assert run.events.count("repair") == 1
