"""Bara's voice: says whether it can speak, refuses empty input, and passes part names to Scribe."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from bara import voice


def test_settings_follow_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setenv("BARA_TTS_MODEL", "eleven_flash_v2_5")
    s = voice.settings()
    assert s["tts"] is False and s["model"] == "eleven_flash_v2_5"
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    assert voice.settings()["tts"] is True


def test_long_text_is_cut_and_tuned() -> None:
    body = voice.tts_body("a" * 2000, "eleven_v4")
    assert len(body["text"]) == voice.MAX_TTS_CHARS
    assert set(body["voice_settings"]) == {"stability", "similarity_boost"}


def test_transcribe_sends_part_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.read()
        return httpx.Response(200, json={"text": " swap the switches "})

    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )
    text = asyncio.run(voice.transcribe(b"RIFF", "audio/webm", ["Gateron Yellow"]))
    assert text == "swap the switches"
    assert seen["url"].endswith("/speech-to-text")
    assert b"scribe_v2" in seen["body"] and b"Gateron Yellow" in seen["body"]


def test_no_key_no_voice(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        asyncio.run(voice.open_speech("hi"))
