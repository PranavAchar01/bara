"""Bara's voice: says whether it can speak, refuses empty input, and passes part names to Scribe."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import httpx
import pytest

from bara import voice


@pytest.fixture(autouse=True)
def _server_voice(monkeypatch: pytest.MonkeyPatch) -> None:
    """The engine's own keys speak only on a demo box (BARA_VOICE_SERVER_KEY=1)."""
    monkeypatch.setenv("BARA_VOICE_SERVER_KEY", "1")
    voice._session_keys.clear()


def test_settings_follow_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
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
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        asyncio.run(voice.open_speech("hi"))


def test_openai_speaks_when_it_is_the_only_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("BARA_TTS_VOICE", raising=False)
    monkeypatch.delenv("BARA_TTS_MODEL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    s = voice.settings()
    assert s["provider"] == "openai" and s["tts"] is True
    assert s["voice"] == voice.OPENAI_VOICE and s["model"] == voice.OPENAI_TTS_MODEL
    # OpenAI keeps the job when both keys exist, unless ElevenLabs is asked for by name
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    assert voice.settings()["provider"] == "openai"
    monkeypatch.setenv("BARA_VOICE_PROVIDER", "elevenlabs")
    assert voice.settings()["provider"] == "elevenlabs"


def test_keychain_key_is_read_into_the_environment_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(voice.sys, "platform", "darwin")
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kw: Any) -> Any:
        calls.append(cmd)
        found = "-a" in cmd

        class R:
            returncode = 0 if found else 44
            stdout = "sk-from-keychain\n" if found else ""

        return R()

    monkeypatch.setattr(voice.subprocess, "run", fake_run)
    assert voice.load_key_from_keychain() is True
    assert os.environ["OPENAI_API_KEY"] == "sk-from-keychain"
    assert voice.settings()["provider"] == "openai"
    monkeypatch.delenv("OPENAI_API_KEY")


def test_missing_keychain_item_means_no_voice_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setattr(voice.sys, "platform", "darwin")

    class R:
        returncode = 44
        stdout = ""

    monkeypatch.setattr(voice.subprocess, "run", lambda *a, **k: R())
    assert voice.load_key_from_keychain() is False
    assert voice.settings()["tts"] is False


def test_a_short_line_said_twice_is_fetched_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    voice._phrases.clear()
    hits: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hits.append(str(request.url))
        return httpx.Response(200, content=b"ID3-audio-bytes")

    voice._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def say(text: str) -> bytes:
        client, resp = await voice.open_speech(text)
        return b"".join([c async for c in voice.relay(client, resp)])

    async def run() -> tuple[bytes, bytes]:
        return await say("Routing the board."), await say("Routing the board.")

    first, second = asyncio.run(run())
    voice._client = None
    assert first == second == b"ID3-audio-bytes"
    assert len(hits) == 1


def test_openai_transcribe_sends_part_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = request.read()
        return httpx.Response(200, json={"text": " swap the switches "})

    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )
    text = asyncio.run(voice.transcribe(b"RIFF", "audio/webm", ["Gateron Yellow"]))
    assert text == "swap the switches"
    assert seen["url"].endswith("/audio/transcriptions") and seen["auth"] == "Bearer sk-test"
    assert b"gpt-4o-transcribe" in seen["body"] and b"Gateron Yellow" in seen["body"]


def test_dotenv_fills_only_what_the_shell_left_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bara.config import load_dotenv

    env = tmp_path / ".env"
    env.write_text('# secrets\nBARA_T_A=from-file\nBARA_T_B="quoted"\n\nnot a pair\n')
    monkeypatch.delenv("BARA_T_A", raising=False)
    monkeypatch.setenv("BARA_T_B", "from-shell")
    load_dotenv(env)
    assert os.environ["BARA_T_A"] == "from-file"
    assert os.environ["BARA_T_B"] == "from-shell"
    monkeypatch.delenv("BARA_T_A")


def test_server_key_needs_the_demo_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "server-key")
    assert voice.settings()["tts"] is True
    monkeypatch.delenv("BARA_VOICE_SERVER_KEY")
    s = voice.settings()
    assert s["tts"] is False and s["needs_user_key"] is True
    with pytest.raises(RuntimeError):
        asyncio.run(voice.open_speech("hi"))


def test_session_key_speaks_without_the_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BARA_VOICE_SERVER_KEY")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    voice.set_session_key("sess-1234", "sk-mine")
    mine = voice.session_key("sess-1234")
    s = voice.settings(mine)
    assert s["tts"] is True and s["provider"] == "openai" and s["own_key"] is True
    assert voice.key(mine) == "sk-mine" and voice.session_key("other-sess") is None
    voice.set_session_key("sess-1234", "")
    assert voice.session_key("sess-1234") is None
