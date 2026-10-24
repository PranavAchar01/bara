"""Lean contract tests: WS stream, edits, resume, dedupe, REST. Full live run is e2e/ws_smoke.py."""

from __future__ import annotations

import pytest
from conftest import SCHEMAS, Ws, fixture, make_client


def _fixture_types(name: str) -> list[str]:
    return [
        s["msg"]["type"]
        for s in fixture(name)["steps"]
        if s["dir"] == "server" and s["msg"]["seq"] > 0
    ]


def test_health_and_catalog(client):
    r = client.get("/v1/health")
    assert r.status_code == 200 and r.json()["part_count"] > 0
    assert client.get("/v1/parts?limit=2").status_code == 200
    r = client.get("/v1/parts/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "E_UNKNOWN_PART"


def test_exact_build_matches_fixture_shape(client):
    with client.websocket_connect("/v1/ws") as sock:
        ws = Ws(sock)
        build_id, events = ws.build("a keyboard")
    types = [e["type"] for e in events]
    assert types == _fixture_types("exact_keyboard")
    seqs = [e["seq"] for e in events]
    assert seqs == list(range(1, len(seqs) + 1))
    body = client.get(f"/v1/builds/{build_id}").json()
    assert not SCHEMAS.errors("rest.schema.json#/$defs/BuildResponse", body)
    assert body["build"]["status"] == "done"
    assert body["build"]["last_seq"] == seqs[-1]


def test_edit_swap_then_reject(client):
    with client.websocket_connect("/v1/ws") as sock:
        ws = Ws(sock)
        build_id, _ = ws.build("a keyboard")
        swap = next(
            s["msg"] for s in fixture("edit_swap_switches")["steps"] if s["dir"] == "client"
        )
        payload = dict(swap["payload"], build_id=build_id, base_revision=1)
        ws.send("edit.apply", payload)
        ack = ws.recv()
        assert ack["payload"]["accepted"] and ack["payload"]["edit_id"]
        done = ws.until(lambda m: m["type"] in ("edit.applied", "edit.rejected"))
        assert done[-1]["type"] == "edit.applied" and done[-1]["payload"]["revision"] == 2

        stale = dict(payload, base_revision=1)
        ws.send("edit.apply", stale)
        ws.recv()
        res = ws.until(lambda m: m["type"] in ("edit.applied", "edit.rejected"))
        assert res[-1]["type"] == "edit.rejected"


def test_duplicate_msg_id_and_bad_message(client):
    with client.websocket_connect("/v1/ws") as sock:
        ws = Ws(sock)
        build_id, _ = ws.build("a keyboard")
        mid = ws.send("build.resume", {"build_id": build_id, "last_seq": 62})
        first = ws.recv()
        ws.send("build.resume", {"build_id": build_id, "last_seq": 62}, msg_id=mid)
        again = ws.recv()
        assert first["payload"]["duplicate"] is False and again["payload"]["duplicate"] is True

        sock.send_text("{not json")
        err = ws.recv()
        assert err["type"] == "error" and err["payload"]["error"]["code"] == "E_BAD_MESSAGE"

        ws.send("ping", {})
        assert ws.recv()["type"] == "pong"

        ws.send("build.resume", {"build_id": "b_doesnotexist", "last_seq": 0})
        ack = ws.recv()
        assert ack["payload"]["error"]["code"] == "E_UNKNOWN_BUILD"


def test_resume_gap_sends_error_then_snapshot(monkeypatch: pytest.MonkeyPatch):
    with make_client(monkeypatch, BARA_EVENT_LOG_KEEP="10") as client:
        with client.websocket_connect("/v1/ws") as sock:
            ws = Ws(sock)
            build_id, events = ws.build("a keyboard")
            last = events[-1]["seq"]
        with client.websocket_connect("/v1/ws") as sock:
            ws = Ws(sock)
            ws.send("build.resume", {"build_id": build_id, "last_seq": 3})
            assert ws.recv()["payload"]["accepted"]
            err = ws.recv()
            assert err["payload"]["error"]["code"] == "E_RESUME_GAP"
            snap = ws.recv()
            assert snap["type"] == "build.snapshot" and snap["payload"]["reason"] == "resume_gap"
            assert snap["seq"] == last

            ws.send("build.resume", {"build_id": build_id, "last_seq": last - 2})
            ws.recv()
            assert [ws.recv()["seq"], ws.recv()["seq"]] == [last - 1, last]
        r = client.get(f"/v1/builds/{build_id}/events?after_seq=0")
        assert r.status_code == 409


def test_export_and_csv(client):
    with client.websocket_connect("/v1/ws") as sock:
        build_id, _ = Ws(sock).build("a keyboard")
    r = client.get(f"/v1/builds/{build_id}/export?format=bom_csv")
    assert r.status_code == 200 and r.text.startswith("part_id,")
    assert client.get(f"/v1/builds/{build_id}/export?format=zip").status_code == 200
    assert client.get(f"/v1/builds/{build_id}/export?format=bogus").status_code == 400
