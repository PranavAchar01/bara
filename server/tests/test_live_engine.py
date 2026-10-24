"""Live engine (BARA_MOCK=0) contract tests.

The KiCad board build (Freerouting, about a minute per board) is replaced by a stub that
reports it unavailable, so these exercise every stage's event shape quickly; the real
board run is covered by e2e/ws_live.py.
"""

from __future__ import annotations

from typing import Any

import pytest
from conftest import TERMINAL, Ws, make_client

from bara.live import adapters

ORDER = ["classify", "reuse", "compose", "place", "enclose", "board", "firmware", "render"]

PROMPTS = [
    "a keyboard",
    (
        "wireless split keyboard, 38 keys, sage and cream, red trackball on the right thumb, "
        "knob top left, tented"
    ),
    "34-key split, no trackball, two knobs, black and orange",
    "small 5x4 macropad with a knob and a screen, white",
    "a handheld weather station with an e-ink screen",
    "a desk clock",
    "a plant monitor",
    "a rover",
]


@pytest.fixture(autouse=True)
def no_kicad(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(*_a: Any, **_k: Any) -> tuple[None, str]:
        return None, "KiCad board build disabled in unit tests"

    monkeypatch.setattr(adapters, "route_board", fake)


def stage_order(events: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for m in events:
        if m["type"] == "stage.started" and m["payload"]["stage"] not in out:
            out.append(m["payload"]["stage"])
    return out


def check_stream(events: list[dict[str, Any]]) -> None:
    open_stage = None
    for m in events:
        if m["type"] == "stage.started":
            assert open_stage is None, (open_stage, m["payload"]["stage"])
            open_stage = m["payload"]["stage"]
        elif m["type"] == "stage.completed":
            assert open_stage == m["payload"]["stage"]
            open_stage = None
    assert open_stage is None


@pytest.mark.parametrize("prompt", PROMPTS)
def test_live_prompt(monkeypatch: pytest.MonkeyPatch, prompt: str) -> None:
    with make_client(monkeypatch, BARA_MOCK="0", BARA_CLARIFY_TIMEOUT_MS="50") as c:
        with c.websocket_connect("/v1/ws") as sock:
            ws = Ws(sock)
            _, events = ws.build(prompt)
    check_stream(events)
    last = events[-1]
    types = [m["type"] for m in events]
    if last["type"] == "build.failed":
        assert last["payload"]["error"]["code"] == "E_OUT_OF_SCOPE", last["payload"]
        return
    assert last["type"] == "build.done", last["payload"]
    assert stage_order(events) == ORDER
    for t in ("spec.ready", "reuse.decided", "slots.ready", "scene.ready"):
        assert t in types, t


def test_live_keyboard_parts_and_firmware(monkeypatch: pytest.MonkeyPatch) -> None:
    with make_client(monkeypatch, BARA_MOCK="0") as c:
        with c.websocket_connect("/v1/ws") as sock:
            ws = Ws(sock)
            build_id, events = ws.build(PROMPTS[1])
            assert events[-1]["type"] == "build.done"
            state = c.get(f"/v1/builds/{build_id}").json()
    types = [m["type"] for m in events]
    assert "layout.added" in types
    assert "part.added" in types
    assert "firmware.ready" in types
    fw = next(m for m in events if m["type"] == "firmware.ready")["payload"]["firmware"]
    assert fw["framework"] == "zmk"
    assert state is not None


def test_live_clarify_round(monkeypatch: pytest.MonkeyPatch) -> None:
    with make_client(monkeypatch, BARA_MOCK="0") as c:
        with c.websocket_connect("/v1/ws") as sock:
            ws = Ws(sock)
            ws.send("build.start", {"prompt": "make me a cool gadget"})
            ack = ws.recv()
            build_id = ack["payload"]["build_id"]
            got = ws.until(lambda m: m["type"] in ("clarify.request", *TERMINAL))
            assert got[-1]["type"] == "clarify.request", [m["type"] for m in got]
            q = got[-1]["payload"]
            ws.send(
                "clarify.answer",
                {"build_id": build_id, "question_id": q["question_id"], "option_id": "o_weather"},
            )
            rest = ws.until(lambda m: m["type"] in TERMINAL)
    events = got + rest
    check_stream(events)
    types = [m["type"] for m in events]
    assert "clarify.resolved" in types
    assert rest[-1]["type"] == "build.done", rest[-1]["payload"]


def test_live_recolor_edit(monkeypatch: pytest.MonkeyPatch) -> None:
    with make_client(monkeypatch, BARA_MOCK="0") as c:
        with c.websocket_connect("/v1/ws") as sock:
            ws = Ws(sock)
            build_id, events = ws.build(PROMPTS[3])
            assert events[-1]["type"] == "build.done"
            enc = [m for m in events if m["type"] == "enclosure.updated"]
            assert enc
            eid = enc[-1]["payload"]["enclosure"]["enclosure_id"]
            ws.send(
                "edit.apply",
                {
                    "build_id": build_id,
                    "ops": [{"op": "recolor", "enclosure_id": eid, "color": {"hex": "#FF7F00"}}],
                },
            )
            got = ws.until(lambda m: m["type"] in ("edit.applied", "edit.rejected", "error"))
    assert got[-1]["type"] == "edit.applied", got[-1]["payload"]
