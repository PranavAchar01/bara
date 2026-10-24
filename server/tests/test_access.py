"""BARA_ACCESS_TOKEN gates everything but /v1/health."""

from __future__ import annotations

import pytest
from conftest import make_client
from starlette.websockets import WebSocketDisconnect

TOKEN = "t-123"


def test_no_token_configured_leaves_the_server_open(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BARA_ACCESS_TOKEN", raising=False)
    with make_client(monkeypatch) as c:
        assert c.get("/v1/vocab").status_code == 200


def test_token_gates_rest_ws_and_assets(monkeypatch: pytest.MonkeyPatch) -> None:
    with make_client(monkeypatch, BARA_ACCESS_TOKEN=TOKEN) as c:
        assert c.get("/v1/health").status_code == 200
        denied = c.get("/v1/vocab")
        assert denied.status_code == 401
        assert denied.json()["error"]["code"] == "E_UNAUTHORIZED"
        assert c.get("/v1/vocab", headers={"X-Bara-Token": "wrong"}).status_code == 401
        assert c.get("/v1/vocab", headers={"X-Bara-Token": TOKEN}).status_code == 200
        assert c.get(f"/v1/vocab?token={TOKEN}").status_code == 200
        assert c.get("/assets/nothing.glb").status_code == 401
        assert c.get(f"/assets/nothing.glb?token={TOKEN}").status_code == 404
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("/v1/ws") as ws:
                ws.receive_json()
        with c.websocket_connect(f"/v1/ws?token={TOKEN}") as ws:
            assert ws.receive_json()["type"] == "hello"


def test_preflight_passes_with_cors_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    with make_client(monkeypatch, BARA_ACCESS_TOKEN=TOKEN) as c:
        res = c.options(
            "/v1/vocab",
            headers={
                "Origin": "https://bara-ivory-five.vercel.app",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "x-bara-token",
            },
        )
        assert res.status_code == 200
        denied = c.get("/v1/vocab", headers={"Origin": "https://bara-ivory-five.vercel.app"})
        assert denied.status_code == 401
        assert denied.headers["access-control-allow-origin"] == "https://bara-ivory-five.vercel.app"
