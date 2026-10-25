"""Builds outlive the engine: a stored build comes back editable, and any earlier revision can be restored."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import make_client

from bara.engine import BuildRun
from bara.library import Library
from bara.reducer import new_build


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    with make_client(monkeypatch, BARA_DATA_DIR=str(tmp_path / "data")) as c:
        yield c


def _stored(build_id: str, lib: Library) -> BuildRun:
    """A finished build with two edits (revisions 2 and 3), written to the library but not running."""
    run = BuildRun(
        build_id=build_id,
        prompt="a macropad",
        options={},
        keep=100,
        state=new_build(build_id, "a macropad", "2026-10-01T00:00:00Z"),
        recorder=lib,
        device="macropad",
    )
    run.emit("part.added", {"part": {"instance_id": "k1", "part_id": "keycap:white"}}, revision=1)
    run.emit("build.done", {"summary": {}})
    run.emit("part.updated", {"part": {"instance_id": "k1", "part_id": "keycap:blue"}}, revision=2)
    run.emit("part.added", {"part": {"instance_id": "n1", "part_id": "knob:metal"}}, revision=3)
    run.emit("edit.applied", {"edit_id": "ed_1", "msg_id": "m1", "ops": [], "revision": 3, "duration_ms": 1}, revision=3)
    return run


def _parts(run: BuildRun) -> dict[str, str]:
    return {p["instance_id"]: p["part_id"] for p in run.state["parts"]}


def test_a_stored_build_comes_back_editable(client) -> None:
    engine = client.app.state.services.engine
    _stored("b_hist0001", engine.library)
    assert "b_hist0001" not in engine.builds
    run = engine.get("b_hist0001")
    assert run is not None and run.terminal == "build.done" and engine.edit_not_ready(run) is None
    assert _parts(run) == {"k1": "keycap:blue", "n1": "knob:metal"}
    assert run.state["revision"] == 3 and run.edit_counter == 1
    assert engine.get("b_nope0001") is None


def test_restore_goes_back_and_forward_as_new_revisions(client) -> None:
    engine = client.app.state.services.engine
    _stored("b_hist0002", engine.library)
    r = client.post("/v1/builds/b_hist0002/restore", json={"revision": 1})
    assert r.status_code == 200 and r.json()["revision"] == 4
    run = engine.get("b_hist0002")
    assert _parts(run) == {"k1": "keycap:white"}
    # forward again to revision 3, then back to 4 (which is revision 1's content)
    assert client.post("/v1/builds/b_hist0002/restore", json={"revision": 3}).json()["revision"] == 5
    assert _parts(run) == {"k1": "keycap:blue", "n1": "knob:metal"}
    assert client.post("/v1/builds/b_hist0002/restore", json={"revision": 4}).json()["revision"] == 6
    assert _parts(run) == {"k1": "keycap:white"}
    last = engine.library.get("b_hist0002")["events"][-1]
    assert last["type"] == "build.snapshot" and last["payload"]["reason"] == "restore" and last["payload"]["restored_from"] == 4


def test_restore_survives_a_restart(client) -> None:
    engine = client.app.state.services.engine
    _stored("b_hist0003", engine.library)
    client.post("/v1/builds/b_hist0003/restore", json={"revision": 2})
    engine.builds.clear()
    assert _parts(engine.get("b_hist0003")) == {"k1": "keycap:blue"}


def test_restore_rejects_bad_targets(client) -> None:
    engine = client.app.state.services.engine
    _stored("b_hist0004", engine.library)
    assert client.post("/v1/builds/b_hist0004/restore", json={"revision": 3}).status_code == 400
    assert client.post("/v1/builds/b_hist0004/restore", json={"revision": "1"}).status_code == 400
    assert client.post("/v1/builds/b_nope0004/restore", json={"revision": 1}).status_code == 404
