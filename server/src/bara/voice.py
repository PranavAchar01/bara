"""Bara's voice: text to speech (streamed) and speech to text, from OpenAI or ElevenLabs.

Voice models are the one paid part Bara does not front: a visitor brings their own OpenAI key
(held in memory per browser session, never logged or written). The engine's own keys speak only
when BARA_VOICE_SERVER_KEY=1 is set, as for a demo.

Keys stay on the server. OpenAI speaks and listens whenever OPENAI_API_KEY is set (the engine
reads it from the macOS keychain at start when the environment has none); ElevenLabs is used
only when that is the sole key, or when BARA_VOICE_PROVIDER=elevenlabs asks for it. The voice
and model can be changed without a code change: BARA_TTS_VOICE and BARA_TTS_MODEL. OpenAI
defaults to marin on gpt-4o-mini-tts (gpt-4o-transcribe listens), ElevenLabs to Charlotte.

Short lines Bara says again (a stage name, a greeting) are kept in a small memory so the second
time costs no round trip to the speech service.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from collections import OrderedDict
from collections.abc import AsyncIterator
from typing import Any

import httpx

log = logging.getLogger(__name__)

API = "https://api.elevenlabs.io/v1"
DEFAULT_VOICE = "XB0fDUnXU5powFXDhCwa"  # Charlotte
DEFAULT_MODEL = "eleven_v4"
STT_MODEL = "scribe_v2"
MAX_TTS_CHARS = 800
MAX_STT_BYTES = 8 * 1024 * 1024


OPENAI_API = "https://api.openai.com/v1"
# marin and cedar are the two top-quality voices; marin is the brighter, lighter one, which suits a
# small friendly builder robot better than cedar's deeper, calmer register (cedar stays the
# narration voice for video). coral and sage sound more like an announcer and a teacher.
OPENAI_VOICE = "marin"
OPENAI_TTS_MODEL = "gpt-4o-mini-tts-2025-12-15"
OPENAI_STT_MODEL = "gpt-4o-transcribe"
# gpt-4o-mini-tts takes delivery instructions. Bara is a small, curious maker that is always
# moving and says little, so it sounds like that: bright, a little playful, light on its feet.
OPENAI_STYLE = (
    "You are Bara, a small, curious hardware maker. Sound like a real person, not a narrator: "
    "warm, expressive and emotionally present. Let feeling show in the voice: real excitement "
    "when something works, a soft 'hmm' when thinking, a smile you can hear. Vary pace and pitch "
    "naturally, with small breaths and pauses. Keep it brief and light, never salesy or announcer-"
    "like."
)


KEYCHAIN_SERVICE = "OPENAI_API_KEY"
KEYCHAIN_ACCOUNT = "pranav"


def load_key_from_keychain() -> bool:
    """At engine start: when the environment has no OpenAI key, read it from the macOS keychain.

    The value goes into this process's environment only. It is never logged or written anywhere,
    and a missing item is simply "no key": voice then falls back to the browser's own speech.
    """
    if os.environ.get("OPENAI_API_KEY"):
        return True
    if sys.platform != "darwin":
        return False
    for args in (["-a", KEYCHAIN_ACCOUNT, "-s", KEYCHAIN_SERVICE], ["-s", KEYCHAIN_SERVICE]):
        try:
            out = subprocess.run(
                ["security", "find-generic-password", *args, "-w"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        value = out.stdout.strip() if out.returncode == 0 else ""
        if value:
            os.environ["OPENAI_API_KEY"] = value
            return True
    return False


MAX_SESSIONS = 256
_session_keys: OrderedDict[str, str] = OrderedDict()


def server_key_allowed() -> bool:
    return os.environ.get("BARA_VOICE_SERVER_KEY", "") == "1"


def set_session_key(sid: str, user_key: str | None) -> None:
    """Remember (or forget, for an empty key) a browser session's own OpenAI key. Memory only."""
    if not user_key:
        _session_keys.pop(sid, None)
        return
    _session_keys[sid] = user_key
    _session_keys.move_to_end(sid)
    while len(_session_keys) > MAX_SESSIONS:
        _session_keys.popitem(last=False)


def session_key(sid: str | None) -> str | None:
    return _session_keys.get(sid) if sid else None


def provider(user_key: str | None = None) -> str | None:
    """Which service speaks: the visitor's own OpenAI key first; the engine's keys only when
    BARA_VOICE_SERVER_KEY=1 (OpenAI when set, else ElevenLabs); else none."""
    if user_key:
        return "openai"
    if not server_key_allowed():
        return None
    has_openai = bool(os.environ.get("OPENAI_API_KEY"))
    has_eleven = bool(os.environ.get("ELEVENLABS_API_KEY"))
    if has_eleven and (not has_openai or os.environ.get("BARA_VOICE_PROVIDER") == "elevenlabs"):
        return "elevenlabs"
    if has_openai:
        return "openai"
    return None


def key(user_key: str | None = None) -> str | None:
    if user_key:
        return user_key
    p = provider()
    if p is None:
        return None
    return os.environ.get("ELEVENLABS_API_KEY" if p == "elevenlabs" else "OPENAI_API_KEY") or None


def settings(user_key: str | None = None) -> dict[str, str | bool]:
    p = provider(user_key)
    openai = p == "openai"
    return {
        "tts": p is not None,
        "stt": p is not None,
        "needs_user_key": not server_key_allowed(),
        "own_key": bool(user_key),
        "provider": p or "none",
        "voice": os.environ.get("BARA_TTS_VOICE", OPENAI_VOICE if openai else DEFAULT_VOICE),
        "model": os.environ.get("BARA_TTS_MODEL", OPENAI_TTS_MODEL if openai else DEFAULT_MODEL),
    }


def tts_body(text: str, model: str) -> dict:
    body: dict = {
        "text": text[:MAX_TTS_CHARS],
        "model_id": model,
        "apply_text_normalization": "auto",
    }
    # a little below the default stability: more of the natural rise and fall of speech
    body["voice_settings"] = {"stability": 0.42, "similarity_boost": 0.8}
    return body


_client: httpx.AsyncClient | None = None


def _shared() -> httpx.AsyncClient:
    """One kept-alive connection pool, so each spoken line skips the TLS handshake."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))
    return _client


MAX_CACHED_CHARS = 240
CACHE_LINES = 64
_phrases: OrderedDict[tuple[str, str, str], bytes] = OrderedDict()


def _cache_key(text: str, user_key: str | None = None) -> tuple[str, str, str]:
    s = settings(user_key)
    return (str(s["provider"]), str(s["voice"]), text[:MAX_TTS_CHARS])


class _Remembered:
    """A line already spoken once: the stored audio, shaped like a streamed response."""

    status_code = 200
    cache_key: tuple[str, str, str] | None = None

    def __init__(self, audio: bytes) -> None:
        self._audio = audio

    async def aiter_bytes(self) -> AsyncIterator[bytes]:
        for i in range(0, len(self._audio), 16384):
            yield self._audio[i : i + 16384]

    async def aclose(self) -> None:
        return None


async def open_speech(text: str, user_key: str | None = None) -> tuple[Any, Any]:
    """Starts a streamed synthesis, or replays a line spoken before. Iterate it with `relay`."""
    k = key(user_key)
    if not k:
        raise RuntimeError("voice needs your own OpenAI key")
    s = settings(user_key)
    ck = _cache_key(text, user_key)
    hit = _phrases.get(ck)
    if hit is not None:
        _phrases.move_to_end(ck)
        return None, _Remembered(hit)
    client = _shared()
    if s["provider"] == "openai":
        req = client.build_request(
            "POST",
            f"{OPENAI_API}/audio/speech",
            json={
                "model": s["model"],
                "voice": s["voice"],
                "input": text[:MAX_TTS_CHARS],
                "instructions": OPENAI_STYLE,
                "response_format": "mp3",
            },
            headers={"authorization": f"Bearer {k}", "accept": "audio/mpeg"},
        )
    else:
        req = client.build_request(
            "POST",
            f"{API}/text-to-speech/{s['voice']}/stream",
            params={"output_format": "mp3_44100_128"},
            json=tts_body(text, str(s["model"])),
            headers={"xi-api-key": k, "accept": "audio/mpeg"},
        )
    resp = await client.send(req, stream=True)
    if resp.status_code != 200:
        await resp.aread()
        await resp.aclose()
        raise RuntimeError(f"{s['provider']} tts {resp.status_code}")
    if len(text) <= MAX_CACHED_CHARS:
        resp.extensions["bara_cache_key"] = ck
    return client, resp


async def relay(client: Any, resp: Any) -> AsyncIterator[bytes]:
    """The audio as it arrives. A short line that played out in full is remembered."""
    ck = getattr(resp, "extensions", {}).get("bara_cache_key")
    kept: list[bytes] = []
    complete = False
    try:
        async for chunk in resp.aiter_bytes():
            if ck is not None:
                kept.append(chunk)
            yield chunk
        complete = True
    finally:
        await resp.aclose()
        if complete and ck is not None and kept:
            _phrases[ck] = b"".join(kept)
            while len(_phrases) > CACHE_LINES:
                _phrases.popitem(last=False)


async def transcribe(
    audio: bytes, content_type: str, keyterms: list[str] | None = None, user_key: str | None = None
) -> str:
    """Text of a short spoken clip. Part names from the build help it spell them right."""
    k = key(user_key)
    if not k:
        raise RuntimeError("voice needs your own OpenAI key")
    ext = (
        "webm"
        if "webm" in content_type
        else "ogg"
        if "ogg" in content_type
        else "mp4"
        if "mp4" in content_type
        else "mp3"
        if "mpeg" in content_type or "mp3" in content_type
        else "wav"
    )
    upload = {"file": (f"speech.{ext}", audio, content_type or "application/octet-stream")}
    if provider(user_key) == "openai":
        # A clean, fluent example steers it away from writing down ums and false starts, and the
        # build's part names help it spell them right.
        hint = "Build me a split keyboard with an OLED."
        if keyterms:
            hint += " Parts: " + ", ".join(t[:50] for t in keyterms[:50])
        form: dict = {"model": OPENAI_STT_MODEL, "prompt": hint}
        resp = await _shared().post(
            f"{OPENAI_API}/audio/transcriptions",
            data=form,
            files=upload,
            headers={"authorization": f"Bearer {k}"},
        )
        if resp.status_code != 200:
            raise RuntimeError(f"openai stt {resp.status_code}")
        return str(resp.json().get("text") or "").strip()
    data: dict = {"model_id": STT_MODEL, "tag_audio_events": "false"}
    if keyterms:
        data["keyterms"] = [t[:50] for t in keyterms[:50]]
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{API}/speech-to-text",
            data=data,
            files=upload,
            headers={"xi-api-key": k},
        )
    if resp.status_code != 200:
        raise RuntimeError(f"elevenlabs stt {resp.status_code}: {resp.text[:200]}")
    return str(resp.json().get("text") or "").strip()
