from __future__ import annotations

import itertools
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from bara.main import create_app
from bara.schemas import SchemaSet, server_def

SPEC_DIR = Path(__file__).resolve().parents[2] / "spec"
FIXTURES = SPEC_DIR / "fixtures"
SCHEMAS = SchemaSet(SPEC_DIR / "schemas")
TERMINAL = {"build.done", "build.failed", "build.cancelled"}
_IDS = itertools.count(1)


def fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def make_client(monkeypatch: pytest.MonkeyPatch, **env: str) -> TestClient:
    monkeypatch.delenv("CEREBRAS_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("BARA_SPEED", "0")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return TestClient(create_app())


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    with make_client(monkeypatch) as c:
        yield c


class Ws:
    """Thin client over a TestClient socket that schema-checks every server message."""

    def __init__(self, sock: Any) -> None:
        self.sock = sock
        self.seen: list[dict[str, Any]] = []
        self.hello = self.recv()
        assert self.hello["type"] == "hello"

    def recv(self) -> dict[str, Any]:
        msg = self.sock.receive_json()
        errs = SCHEMAS.errors(server_def(msg["type"]), msg)
        assert not errs, (msg["type"], errs[:2])
        self.seen.append(msg)
        return msg

    def send(self, msg_type: str, payload: dict[str, Any], msg_id: str | None = None) -> str:
        mid = msg_id or f"m_test_{next(_IDS):06d}"
        self.sock.send_json(
            {
                "spec_version": "1.1.0",
                "type": msg_type,
                "msg_id": mid,
                "ts": "2026-10-23T12:00:00.000Z",
                "payload": payload,
            }
        )
        return mid

    def until(self, pred) -> list[dict[str, Any]]:
        out = []
        for _ in range(2000):
            msg = self.recv()
            out.append(msg)
            if pred(msg):
                return out
        raise AssertionError("predicate never matched")

    def build(self, prompt: str) -> tuple[str, list[dict[str, Any]]]:
        self.send("build.start", {"prompt": prompt})
        ack = self.recv()
        assert ack["type"] == "ack" and ack["payload"]["accepted"], ack
        events = self.until(lambda m: m["type"] in TERMINAL)
        return ack["payload"]["build_id"], events
