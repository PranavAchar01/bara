"""Persistent build library: record, list, get, delete, id validation."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import make_client

from bara.engine import BuildRun
from bara.library import Library
from bara.reducer import new_build


def _run(build_id: str, recorder: Library, created: str) -> BuildRun:
    return BuildRun(
        build_id=build_id,
        prompt="a handheld game console",
        options={},
        keep=100,
        state=new_build(build_id, "a handheld game console", created),
        recorder=recorder,
        device="game console",
    )


def _finish(run: BuildRun, kind: str = "build.done") -> None:
    run.emit("stage.started", {"stage": "brief"})
    run.emit(kind, {"summary": {}} if kind == "build.done" else {"error": {"code": "E_X"}})


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    with make_client(monkeypatch, BARA_DATA_DIR=str(tmp_path / "data")) as c:
        yield c


def test_record_list_get_delete(client) -> None:
    lib = client.app.state.services.engine.library
    _finish(_run("b_aaaa1111", lib, "2026-10-01T00:00:00Z"))
    _finish(_run("b_bbbb2222", lib, "2026-10-02T00:00:00Z"), "build.failed")
    rows = client.get("/v1/library").json()["builds"]
    assert [r["build_id"] for r in rows] == ["b_bbbb2222", "b_aaaa1111"]
    assert rows[0]["status"] == "failed" and rows[1]["status"] == "done"
    assert rows[1]["device"] == "game console" and rows[1]["hero_url"] is None
    got = client.get("/v1/library/b_aaaa1111").json()
    assert [e["type"] for e in got["events"]] == ["stage.started", "build.done"]
    assert got["events"][0]["seq"] == 1
    assert client.delete("/v1/library/b_aaaa1111").status_code == 200
    assert client.get("/v1/library/b_aaaa1111").status_code == 404
    assert client.delete("/v1/library/b_aaaa1111").status_code == 404
    assert [r["build_id"] for r in client.get("/v1/library").json()["builds"]] == ["b_bbbb2222"]


def test_unfinished_build_is_not_listed(client) -> None:
    lib = client.app.state.services.engine.library
    _run("b_cccc3333", lib, "2026-10-03T00:00:00Z").emit("stage.started", {"stage": "brief"})
    assert client.get("/v1/library").json()["builds"] == []


def test_delete_leaves_shared_caches(client) -> None:
    svc = client.app.state.services
    cache = svc.settings.assets_dir / "cache" / "hero"
    cache.mkdir(parents=True)
    hero = cache / "b_dddd4444.png"
    hero.write_bytes(b"png")
    other = svc.settings.assets_dir / "cache" / "boards" / "x.glb"
    other.parent.mkdir(parents=True)
    other.write_bytes(b"glb")
    _finish(_run("b_dddd4444", svc.engine.library, "2026-10-04T00:00:00Z"))
    row = client.get("/v1/library").json()["builds"][0]
    assert row["hero_url"] == "/assets/cache/hero/b_dddd4444.png"
    client.delete("/v1/library/b_dddd4444")
    assert other.is_file() and hero.is_file()


@pytest.mark.parametrize(
    "bad", ["..", "b_..%2f..%2fsecret", "%2e%2e%2fx", "b_a b", "x" * 80, "etc"]
)
def test_bad_ids_rejected(client, bad: str) -> None:
    assert client.get(f"/v1/library/{bad}").status_code == 404
    assert client.delete(f"/v1/library/{bad}").status_code in (404, 405)


def test_library_rejects_traversal_directly(tmp_path: Path) -> None:
    lib = Library(tmp_path / "lib", tmp_path)
    for bad in ("../x", "b_/../x", "b_a/b"):
        with pytest.raises(ValueError):
            lib.delete(bad)


def test_list_carries_product_shot_once_rendered(client) -> None:
    lib = client.app.state.services.engine.library
    _finish(_run("b_cccc3333", lib, "2026-10-03T00:00:00Z"))
    assert client.get("/v1/library").json()["builds"][0]["shot_url"] is None
    shot = lib.assets_dir / "cache" / "shots" / "b_cccc3333.webp"
    shot.parent.mkdir(parents=True, exist_ok=True)
    shot.write_bytes(b"RIFF0000WEBP")
    url = client.get("/v1/library").json()["builds"][0]["shot_url"]
    assert url.startswith("/assets/cache/shots/b_cccc3333.webp?v=")
