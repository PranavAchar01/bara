"""A prompt over an open build: a device of its own beside it, or a change to it. The model
decides; these tests stand in for its answers and check what the engine does with them."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from bara import intent
from bara.router import own_part


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
        fake(
            {
                "kind": "companion",
                "device": "mouse",
                "device_prompt": "a wireless mouse that pairs with a 75% keyboard",
            },
            seen,
        ),
    )
    r = asyncio.run(
        intent.classify("add a mouse to the keyboard", True, "a 75% keyboard", ["Switch", "PCB"])
    )
    assert r["kind"] == "companion" and r["thing"] == "mouse"
    assert "pairs with" in r["prompt"]
    assert "75% keyboard" in seen[0] and "Switch, PCB" in seen[0]


def test_change_keeps_the_request_as_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        intent, "ask_json", fake({"kind": "modify", "device": "", "device_prompt": "rewritten"})
    )
    r = asyncio.run(intent.classify("add a speaker to it", True))
    assert r["kind"] == "modify" and r["prompt"] == "add a speaker to it"


def test_no_open_build_or_no_answer_starts_a_build(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        intent, "ask_json", fake({"kind": "companion", "device": "x", "device_prompt": "x"})
    )
    assert asyncio.run(intent.classify("a mouse", False))["kind"] == "new"
    monkeypatch.setattr(intent, "ask_json", fake(None))
    r = asyncio.run(intent.classify("a gameboy with a big screen", True))
    assert r["kind"] == "new" and r["prompt"] == "a gameboy with a big screen" and r["note"]


@pytest.mark.parametrize(
    "line",
    [
        "add a mouse to this keyboard",
        "Add a mouse to the keyboard.",
        "I want to add a mouse to the keyboard",
        "connect a mouse",
        "connect a mouse to it",
        "I want to connect this keyboard to a mouse",
        "pair this with a numpad",
        "make a matching mouse",
        "can you make me a matching mouse",
        "a numpad beside it",
        "build a trackball to go with this",
        "add a mouse next to it",
    ],
)
def test_shape_reads_a_device_of_its_own(line: str) -> None:
    r = intent.read_shape(line)
    assert r is not None and r["kind"] == "companion", line


@pytest.mark.parametrize(
    ("line", "thing"),
    [
        ("add a knob to it", "knob"),
        ("put an OLED screen on the keyboard", "oled screen"),
        ("add a speaker to it", "speaker"),
    ],
)
def test_shape_reads_a_part_for_this_device(line: str, thing: str) -> None:
    assert intent.read_shape(line) == {"kind": "modify", "thing": thing}


@pytest.mark.parametrize(
    "line",
    ["a gameboy", "make the keycaps blue", "connect this keyboard to the wifi", "why this switch?"],
)
def test_shape_leaves_other_lines_alone(line: str) -> None:
    assert intent.read_shape(line) is None


def test_device_kind_names_the_head_device() -> None:
    assert intent.device_kind("a wireless mouse that pairs with a 75% keyboard") == "mouse"
    assert intent.device_kind("A 75% mechanical keyboard") == "keyboard"
    assert intent.device_kind("a Game Boy style handheld") == "handheld"
    assert intent.device_kind("numpads") == "keyboard"
    assert intent.device_kind("a desk lamp") is None


STYLE = {
    "device": "75% keyboard",
    "palette": {"body": "#1f2a44", "trim": "#e8e1d0", "bogus": "red; drop table"},
    "material": "plastic",
    "finish": "matte",
    "connector": "USB-C",
}


def test_no_model_companion_inherits_the_parent_look(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(intent, "ask_json", fake(None))
    r = asyncio.run(
        intent.classify("add a mouse to this keyboard", True, "a 75% keyboard", [], STYLE)
    )
    assert r["kind"] == "companion" and r["thing"] == "mouse" and r["device_kind"] == "mouse"
    p = r["prompt"]
    assert p.startswith("a mouse that pairs with the 75% keyboard")
    assert "body #1f2a44" in p and "trim #e8e1d0" in p and "drop table" not in p
    assert "matte plastic case" in p and "USB-C like the 75% keyboard" in p


def test_model_companion_also_carries_the_parent_look(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        intent,
        "ask_json",
        fake({"kind": "companion", "device": "mouse", "device_prompt": "a wireless mouse"}),
    )
    r = asyncio.run(intent.classify("make a matching mouse", True, "a 75% keyboard", [], STYLE))
    assert r["kind"] == "companion" and r["device_kind"] == "mouse"
    assert r["prompt"].startswith(
        "a wireless mouse; it pairs with the 75% keyboard as a matching set"
    )
    assert "#1f2a44" in r["prompt"]


def test_no_model_part_request_stays_a_change(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(intent, "ask_json", fake(None))
    r = asyncio.run(intent.classify("add a knob to it", True, "a macropad"))
    assert r["kind"] == "modify" and r["thing"] == "knob" and r["prompt"] == "add a knob to it"


def test_route(client, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        intent,
        "ask_json",
        fake({"kind": "companion", "device": "mouse", "device_prompt": "a mouse for it"}),
    )
    r = client.post(
        "/v1/intent",
        json={
            "prompt": "add a mouse to the keyboard",
            "has_build": True,
            "build_prompt": "a keyboard",
            "part_names": ["Switch"],
        },
    )
    assert r.status_code == 200
    assert r.json()["kind"] == "companion"
    assert client.post("/v1/intent", json={}).status_code == 400


def test_route_passes_the_parent_style(client, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(intent, "ask_json", fake(None))
    r = client.post(
        "/v1/intent",
        json={
            "prompt": "connect a mouse",
            "has_build": True,
            "build_prompt": "a keyboard",
            "parent_style": STYLE,
        },
    )
    assert r.status_code == 200
    got = r.json()
    assert (
        got["kind"] == "companion" and got["device_kind"] == "mouse" and "#1f2a44" in got["prompt"]
    )


@pytest.mark.parametrize(
    ("prompt", "own"),
    [
        ("a mouse that pairs with the keyboard; case colours the same as the keyboard", "a mouse"),
        ("a numpad to go with my keyboard", "a numpad"),
        ("a speaker paired with the handheld", "a speaker"),
        ("a gameboy with a big screen", "a gameboy with a big screen"),
        ("a keyboard; rgb", "a keyboard"),
    ],
)
def test_the_device_asked_for_is_not_the_one_it_pairs_with(prompt: str, own: str) -> None:
    # the router matches designs on this part, so a companion never reuses its parent's design
    assert own_part(prompt) == own
