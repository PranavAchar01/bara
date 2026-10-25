"""A prompt over an open build: a device of its own beside it, or a change to it. The model
decides; these tests stand in for its answers and check what the engine does with them."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from bara import intent


def fake(answer: dict[str, Any] | None, seen: list[str] | None = None):  # type: ignore[no-untyped-def]
    async def ask(system: str, prompt: str, schema: dict, **kw: Any):  # type: ignore[no-untyped-def]
        if seen is not None:
            seen.append(prompt)
        return answer, "ok" if answer else "no answer"

    return ask


def test_companion_carries_what_it_pairs_with(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    monkeypatch.setattr(
        intent,
        "ask_json",
        fake({"kind": "companion", "device": "mouse", "device_prompt": "a wireless mouse that pairs with a 75% keyboard"}, seen),
    )
    r = asyncio.run(intent.classify("add a mouse to the keyboard", True, "a 75% keyboard", ["Switch", "PCB"]))
    assert r["kind"] == "companion" and r["thing"] == "mouse"
    assert "pairs with" in r["prompt"]
    assert "75% keyboard" in seen[0] and "Switch, PCB" in seen[0]


def test_change_keeps_the_request_as_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(intent, "ask_json", fake({"kind": "modify", "device": "", "device_prompt": "rewritten"}))
    r = asyncio.run(intent.classify("add a speaker to it", True))
    assert r["kind"] == "modify" and r["prompt"] == "add a speaker to it"


def test_no_open_build_or_no_answer_starts_a_build(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(intent, "ask_json", fake({"kind": "companion", "device": "x", "device_prompt": "x"}))
    assert asyncio.run(intent.classify("a mouse", False))["kind"] == "new"
    monkeypatch.setattr(intent, "ask_json", fake(None))
    r = asyncio.run(intent.classify("add a mouse to the keyboard", True))
    assert r["kind"] == "new" and r["prompt"] == "add a mouse to the keyboard" and r["note"]


def test_route(client, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(intent, "ask_json", fake({"kind": "companion", "device": "mouse", "device_prompt": "a mouse for it"}))
    r = client.post("/v1/intent", json={"prompt": "add a mouse to the keyboard", "has_build": True, "build_prompt": "a keyboard", "part_names": ["Switch"]})
    assert r.status_code == 200
    assert r.json()["kind"] == "companion"
    assert client.post("/v1/intent", json={}).status_code == 400
