"""A prompt over an open build: a device of its own beside it, or a change to it."""

from __future__ import annotations

from bara import intent

PARTS = {"speaker", "led", "key", "matrix", "display", "screen", "battery"}


def test_new_thing_beside_the_build_is_a_companion() -> None:
    for p in ("add a mouse to the keyboard", "Connect a mouse to it.", "a mouse to go with this"):
        r = intent.classify(p, True, PARTS)
        assert r["kind"] == "companion", p
        assert r["thing"] == "mouse"
        assert r["prompt"] == "a mouse"


def test_a_part_of_a_build_is_a_change() -> None:
    for p in ("add a speaker to the keyboard", "add some LEDs to it", "attach a screen to this"):
        assert intent.classify(p, True, PARTS)["kind"] == "modify", p


def test_plain_prompts_and_empty_canvases_start_over() -> None:
    assert intent.classify("a gameboy", True, PARTS)["kind"] == "new"
    assert intent.classify("add a mouse to the keyboard", False, PARTS)["kind"] == "new"


def test_route(client) -> None:  # type: ignore[no-untyped-def]
    r = client.post("/v1/intent", json={"prompt": "add a mouse to the keyboard", "has_build": True})
    assert r.status_code == 200
    assert r.json()["kind"] == "companion"
    assert client.post("/v1/intent", json={}).status_code == 400
