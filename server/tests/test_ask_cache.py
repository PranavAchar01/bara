"""A question answered once is answered from disk the next time, without a model call."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from bara.live import ask

SCHEMA = {"type": "object", "properties": {"x": {"type": "integer"}}}


def test_a_cached_answer_needs_no_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ask, "CACHE", tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    path = ask._cache_path(ask.model_name(fast=True), "sys", "q", SCHEMA, [])
    path.write_text(json.dumps({"x": 3}))
    data, note = asyncio.run(ask.ask_json("sys", "q", SCHEMA, name="t", fast=True))
    assert data == {"x": 3} and note == "ok (cached)"
    # another model is a different question
    monkeypatch.setenv("BARA_FORM_MODEL", "claude-opus-5-5")
    data, note = asyncio.run(ask.ask_json("sys", "q", SCHEMA, name="t"))
    assert data is None and note == "no ANTHROPIC_API_KEY"
