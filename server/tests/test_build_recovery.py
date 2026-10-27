"""Builds survive a dropped socket and an engine restart: every event is kept on disk as it is
sent, a build cut off mid-run comes back with what it had and ends cleanly, and a browser that
reconnects picks up from its last event."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import Ws, make_client

from bara.engine import BuildRun
from bara.library import Library
from bara.reducer import new_build


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    with make_client(monkeypatch, BARA_DATA_DIR=str(tmp_path / "data")) as c:
        yield c


def _half_built(build_id: str, lib: Library) -> BuildRun:
    """A live build that got as far as one part in its second stage, then the engine stopped."""
    run = BuildRun(
        build_id=build_id,
        prompt="a macropad",
        options={},
        keep=100,
        state=new_build(build_id, "a macropad", "2026-10-24T00:00:00Z"),
        recorder=lib,
        device="macropad",
    )
    run.emit("stage.started", {"stage": "classify", "label": "x", "budget_ms": 1}, stage="classify")
    run.emit(
        "stage.completed",
        {"stage": "classify", "status": "ok", "duration_ms": 1},
        stage="classify",
    )
    run.emit("stage.started", {"stage": "compose", "label": "x", "budget_ms": 1}, stage="compose")
    run.emit("part.added", {"part": {"instance_id": "k1", "part_id": "keycap:white"}}, revision=1)
    return run


def _restart(client) -> None:
    """What a new engine process sees: nothing in memory, only the files on disk."""
    client.app.state.services.engine.builds.clear()


def test_unfinished_build_is_kept_on_disk_but_not_listed(client) -> None:
    lib = client.app.state.services.engine.library
    _half_built("b_cut00001", lib)
    entry = lib.get("b_cut00001")
    assert entry is not None and entry["status"] == "running" and entry["prompt"] == "a macropad"
    assert [e["seq"] for e in entry["events"]] == [1, 2, 3, 4]
    assert client.get("/v1/library").json()["builds"] == []


def test_build_cut_off_by_a_restart_comes_back_and_ends(client) -> None:
    engine = client.app.state.services.engine
    _half_built("b_cut00002", engine.library)
    _restart(client)
    run = engine.get("b_cut00002")
    assert run is not None and run.terminal == "build.failed"
    assert [p["instance_id"] for p in run.state["parts"]] == ["k1"]
    types = [e["type"] for e in run.log]
    # the open stage is closed, then the build ends with a plain reason
    assert types[-2:] == ["stage.completed", "build.failed"]
    assert run.log[-2]["payload"]["stage"] == "compose"
    assert "restarted" in run.log[-1]["payload"]["error"]["message"]
    assert run.state["status"] == "failed"
    # and it stays ended: another restart does not add a second failure
    _restart(client)
    again = engine.get("b_cut00002")
    assert again is not None and again.seq == run.seq
    assert client.get("/v1/library").json()["builds"][0]["status"] == "failed"


def test_reconnect_after_restart_resumes_from_last_event(client) -> None:
    engine = client.app.state.services.engine
    _half_built("b_cut00003", engine.library)
    _restart(client)
    with client.websocket_connect("/v1/ws") as sock:
        ws = Ws(sock)
        mid = ws.send("build.resume", {"build_id": "b_cut00003", "last_seq": 4})
        ack = ws.recv()
        assert ack["type"] == "ack" and ack["payload"]["msg_id"] == mid
        assert ack["payload"]["accepted"]
        got = ws.until(lambda m: m["type"] == "build.failed")
    assert [e["seq"] for e in got] == [5, 6]
    assert [e["type"] for e in got] == ["stage.completed", "build.failed"]


def test_events_endpoint_serves_a_cut_off_build_after_restart(client) -> None:
    engine = client.app.state.services.engine
    _half_built("b_cut00004", engine.library)
    _restart(client)
    body = client.get("/v1/builds/b_cut00004/events?after_seq=2").json()
    assert [e["seq"] for e in body["events"]] == [3, 4, 5, 6] and body["complete"]


def test_truncated_last_line_is_skipped(client) -> None:
    lib = client.app.state.services.engine.library
    _half_built("b_cut00005", lib)
    with (lib.root / "b_cut00005.jsonl").open("a", encoding="utf-8") as fh:
        fh.write('{"type":"part.added","seq":5,"pay')
    entry = lib.get("b_cut00005")
    assert entry is not None and [e["seq"] for e in entry["events"]] == [1, 2, 3, 4]


def test_live_socket_drop_then_resume_gets_only_missed_events(client) -> None:
    with client.websocket_connect("/v1/ws") as sock:
        ws = Ws(sock)
        build_id, events = ws.build("a keyboard")
    assert len(events) > 4
    cut = events[2]["seq"]
    with client.websocket_connect("/v1/ws") as sock:
        ws = Ws(sock)
        ws.send("build.resume", {"build_id": build_id, "last_seq": cut})
        ws.recv()
        got = ws.until(lambda m: m["type"] in ("build.done", "build.failed"))
    assert [e["seq"] for e in got] == [e["seq"] for e in events if e["seq"] > cut]


def test_library_dir_can_be_moved(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    lib_dir = tmp_path / "side-library"
    with make_client(
        monkeypatch, BARA_DATA_DIR=str(tmp_path / "data"), BARA_LIBRARY_DIR=str(lib_dir)
    ) as c:
        assert c.app.state.services.engine.library.root == lib_dir
