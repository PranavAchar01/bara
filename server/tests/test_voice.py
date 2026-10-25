"""Bara's voice: says whether it can speak, refuses empty input, and passes part names to Scribe."""

from __future__ import annotations

import array
import asyncio
import base64
import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import websockets

from bara import voice


@pytest.fixture(autouse=True)
def _server_voice(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The engine's own keys speak for every visitor (BARA_VOICE_SERVER_KEY=0 turns that off)."""
    monkeypatch.setenv("BARA_VOICE_SERVER_KEY", "1")
    monkeypatch.setattr(voice, "RETRY_S", 0)
    voice._session_keys.clear()
    voice._phrases.clear()
    voice._lines.clear()
    voice._client = None
    yield
    voice._client = None
    voice._lines.clear()


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


QUIET = array.array("h", [3] * 2400).tobytes()  # a tenth of a second of near silence
LOUD = array.array("h", [9000, -9000] * 1200).tobytes()


async def _say(text: str) -> bytes:
    speech = await voice.open_speech(text)
    return b"".join([c async for c in voice.relay(speech)])


def test_a_short_line_said_twice_is_fetched_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("BARA_TTS_MODEL", "gpt-4o-mini-tts")
    hits: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hits.append(json.loads(request.read()))
        return httpx.Response(200, content=QUIET + LOUD)

    voice._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def run() -> tuple[bytes, bytes]:
        return await _say("Routing the board."), await _say("Routing the board.")

    first, second = asyncio.run(run())
    assert first == second
    assert len(hits) == 1 and hits[0]["response_format"] == "pcm"
    assert hits[0]["voice"] == "marin" and "salesy" in hits[0]["instructions"]
    # the quiet before the first sound is cut, all but a short lead-in
    assert first.endswith(LOUD) and len(first) == len(LOUD) + voice.KEEP_LEAD_SAMPLES * 2


def test_each_kind_of_line_is_said_in_its_own_tone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("BARA_TTS_MODEL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    hits: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hits.append(json.loads(request.read()))
        return httpx.Response(200, content=LOUD)

    voice._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def run() -> None:
        for mood in ("success", "failure", "success", "nonsense"):
            speech = await voice.open_speech("Done!", None, mood)
            _ = [c async for c in voice.relay(speech)]

    asyncio.run(run())
    # the speech endpoint by default; a tone per mood, each remembered on its own
    assert {h["model"] for h in hits} == {voice.OPENAI_SPEECH_MODEL}
    assert len(hits) == 3
    assert "delighted" in hits[0]["instructions"] and "sympathetic" in hits[1]["instructions"]
    assert "never a newsreader" in hits[0]["instructions"]
    assert voice.MOODS["reply"] in hits[2]["instructions"]  # an unknown mood is a plain reply


def test_the_quiet_after_the_last_word_is_cut_short(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    pause = QUIET * 3

    def handler(request: httpx.Request) -> httpx.Response:
        # a short pause between words is kept; the long quiet at the end is not
        return httpx.Response(200, content=LOUD + pause + LOUD + QUIET * 8)

    voice._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    said = asyncio.run(_say("Okay, nice. Got it"))
    assert said == LOUD + pause + LOUD + (QUIET * 8)[: voice.KEEP_TAIL_BYTES]


def test_a_busy_speech_service_gets_one_more_try(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("BARA_TTS_MODEL", "gpt-4o-mini-tts")
    codes = iter([429, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        code = next(codes)
        return httpx.Response(code, content=LOUD if code == 200 else b"slow down")

    voice._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert asyncio.run(_say("Placing the switches")) == LOUD


class FakeRealtime:
    """A realtime session that says each line as three pieces of audio, quiet first."""

    def __init__(self, fail: bool) -> None:
        self.state = websockets.State.OPEN
        self.sent: list[dict] = []
        self.inbox: asyncio.Queue[dict] = asyncio.Queue()
        self.fail = fail

    async def send(self, msg: str) -> None:
        m = json.loads(msg)
        self.sent.append(m)
        kind = m["type"]
        if kind == "session.update":
            await self.inbox.put({"type": "session.updated"})
        elif kind == "response.create" and self.fail:
            await self.inbox.put({"type": "error", "error": {"code": "rate_limit_exceeded"}})
        elif kind == "response.create":
            for piece in (QUIET, LOUD, LOUD):
                delta = base64.b64encode(piece).decode()
                await self.inbox.put({"type": "response.output_audio.delta", "delta": delta})
            await self.inbox.put({"type": "response.done", "response": {"status": "completed"}})
        elif kind == "response.cancel":
            # the whole line was already sent: the service says there is nothing to cancel
            await self.inbox.put({"type": "error", "error": {"code": "response_cancel_not_active"}})

    async def recv(self) -> str:
        return json.dumps(await self.inbox.get())

    async def close(self) -> None:
        self.state = websockets.State.CLOSED


def _realtime(monkeypatch: pytest.MonkeyPatch, fail: bool = False) -> list[FakeRealtime]:
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    # the realtime voice is opt-in: quicker, but not always word for word
    monkeypatch.setenv("BARA_TTS_MODEL", "gpt-realtime-2.1-mini")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    made: list[FakeRealtime] = []

    async def connect(url: str, **kw: Any) -> FakeRealtime:
        assert url.endswith("?model=gpt-realtime-2.1-mini")
        assert kw["additional_headers"]["authorization"] == "Bearer sk-test"
        made.append(FakeRealtime(fail))
        return made[-1]

    monkeypatch.setattr(voice.websockets, "connect", connect)
    return made


def test_openai_says_lines_word_for_word_on_one_open_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    made = _realtime(monkeypatch)

    async def run() -> list[bytes]:
        return [await _say("Got a rotary encoder"), await _say("Placing the switches")]

    first, second = asyncio.run(run())
    assert len(made) == 1  # the second line reuses the open session
    session = made[0].sent[0]["session"]
    assert session["audio"]["output"]["voice"] == "marin"
    assert session["audio"]["output"]["format"] == {"type": "audio/pcm", "rate": 24000}
    assert "word for word" in session["instructions"] and "salesy" in session["instructions"]
    said = [m["response"]["instructions"] for m in made[0].sent if m["type"] == "response.create"]
    assert "Say exactly" in said[0] and said[0].endswith("\nGot a rotary encoder")
    assert first.endswith(LOUD + LOUD) and len(first) < len(QUIET + LOUD + LOUD)


def test_a_line_cut_short_leaves_the_session_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    made = _realtime(monkeypatch)
    cut = "A long line that gets interrupted"

    async def run() -> bytes:
        stream = voice.relay(await voice.open_speech(cut))
        await stream.__anext__()
        await stream.aclose()  # the listener talked over it
        return await _say("Next line")

    assert asyncio.run(run()).endswith(LOUD)
    assert [m["type"] for m in made[0].sent].count("response.cancel") == 1
    assert len(made) == 1
    # a line that was cut off is not remembered as the whole line
    assert not any(cut in k for k in voice._phrases)


def test_a_failing_realtime_session_falls_back_to_the_speech_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    made = _realtime(monkeypatch, fail=True)
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.read())["model"])
        return httpx.Response(200, content=LOUD)

    voice._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert asyncio.run(_say("Done!")) == LOUD
    assert len(made) == 2  # one more try on a fresh session first
    assert seen == [voice.OPENAI_SPEECH_MODEL]


def test_warm_opens_the_session_before_the_first_line(monkeypatch: pytest.MonkeyPatch) -> None:
    made = _realtime(monkeypatch)

    async def run() -> None:
        await voice.warm()
        await voice.warm()  # already open: nothing more
        await _say("Hello")

    asyncio.run(run())
    assert len(made) == 1


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
    assert b"gpt-4o-mini-transcribe" in seen["body"] and b"Gateron Yellow" in seen["body"]


def test_transcribe_moves_to_the_newer_model_when_one_is_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("BARA_STT_MODEL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read()
        asked.append("new" if b"\r\n\r\ngpt-transcribe\r\n" in body else "mini")
        if asked[-1] == "mini":
            return httpx.Response(404, json={"error": {"code": "model_not_found"}})
        return httpx.Response(200, json={"text": "hello"})

    voice._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert asyncio.run(voice.transcribe(b"RIFF", "audio/webm")) == "hello"
    assert asked == ["mini", "new"]


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


def test_the_engine_key_speaks_for_every_visitor_unless_turned_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "server-key")
    monkeypatch.delenv("BARA_VOICE_SERVER_KEY")
    s = voice.settings()
    assert s["tts"] is True and s["needs_user_key"] is False and s["provider"] == "openai"
    monkeypatch.setenv("BARA_VOICE_SERVER_KEY", "0")
    s = voice.settings()
    assert s["tts"] is False and s["needs_user_key"] is True
    with pytest.raises(RuntimeError):
        asyncio.run(voice.open_speech("hi"))


def test_session_key_speaks_when_the_engine_key_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BARA_VOICE_SERVER_KEY", "0")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    voice.set_session_key("sess-1234", "sk-mine")
    mine = voice.session_key("sess-1234")
    s = voice.settings(mine)
    assert s["tts"] is True and s["provider"] == "openai" and s["own_key"] is True
    assert voice.key(mine) == "sk-mine" and voice.session_key("other-sess") is None
    voice.set_session_key("sess-1234", "")
    assert voice.session_key("sess-1234") is None
