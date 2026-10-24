"""Questions about one part: grounded in the build, short, with the backup model as fallback."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from bara import part_ask

BUILD: dict[str, Any] = {
    "prompt": "a keyboard",
    "parts": [
        {
            "instance_id": "sw_l",
            "part_id": "sw:yellow",
            "quantity": 21,
            "label": "left",
            "card": {"display_name": "Gateron Yellow", "summary": "Linear switch"},
        },
        {
            "instance_id": "sw_r",
            "part_id": "sw:yellow",
            "quantity": 21,
            "label": "right",
            "card": {"display_name": "Gateron Yellow"},
        },
        {
            "instance_id": "pcb",
            "part_id": "pcb:corne",
            "quantity": 1,
            "card": {"display_name": "Corne PCB"},
        },
    ],
    "decisions": [
        {"slot_id": "switches", "chosen_part_id": "sw:yellow", "reason": "Smooth and light."}
    ],
    "connections": [
        {"from": {"instance_id": "sw_l"}, "to": {"instance_id": "pcb"}, "kind": "solder"}
    ],
    "checks": [
        {"status": "pass", "message": "Fits the plate", "subjects": [{"instance_id": "sw_r"}]}
    ],
}


def test_facts_cover_every_instance_of_the_part() -> None:
    facts = part_ask.part_facts(BUILD, "sw:yellow")
    assert facts is not None
    assert facts["part"]["count"] == 42
    assert facts["why_chosen"][0]["reason"] == "Smooth and light."
    assert facts["connects_to"] == [{"to": "Corne PCB", "kind": "solder"}]
    assert facts["checks"][0]["message"] == "Fits the plate"
    assert part_ask.part_facts(BUILD, "nope") is None


def test_backup_model_answers_when_the_first_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CEREBRAS_API_KEY", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "y")

    async def broken(*_: Any) -> dict[str, Any]:
        raise RuntimeError("down")

    async def fine(prompt: str, *_: Any) -> dict[str, Any]:
        assert "Gateron Yellow" in prompt and "Why these?" in prompt
        return part_ask._check(
            {"answer": " Smooth and light. ", "follow_ups": ["Quieter?", "", "Louder?", "Pricier?"]}
        )

    monkeypatch.setattr(part_ask, "_cerebras", broken)
    monkeypatch.setattr(part_ask, "_anthropic", fine)
    result, note = asyncio.run(
        part_ask.answer(BUILD, "sw:yellow", "Why these?", cerebras_model="c", anthropic_model="a")
    )
    assert note == "ok" and result is not None
    assert result.provider == "anthropic" and result.answer == "Smooth and light."
    assert result.follow_ups == ["Quieter?", "Louder?", "Pricier?"]


def test_no_keys_is_a_clear_no(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CEREBRAS_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result, note = asyncio.run(
        part_ask.answer(BUILD, "sw:yellow", "Why?", cerebras_model="c", anthropic_model="a")
    )
    assert result is None and note == "no LLM key set"
