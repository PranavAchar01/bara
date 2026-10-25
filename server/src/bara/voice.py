"""Bara's voice: text to speech (streamed) and speech to text, from ElevenLabs or OpenAI.

Keys stay on the server. ELEVENLABS_API_KEY wins when both are set; otherwise OPENAI_API_KEY
uses OpenAI's speech and transcription. The voice and model can be changed without a code
change: BARA_TTS_VOICE and BARA_TTS_MODEL. ElevenLabs defaults to Charlotte on eleven_v4,
OpenAI to marin on gpt-4o-mini-tts (gpt-4o-transcribe listens).
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator

import httpx

log = logging.getLogger(__name__)

API = "https://api.elevenlabs.io/v1"
DEFAULT_VOICE = "XB0fDUnXU5powFXDhCwa"  # Charlotte
DEFAULT_MODEL = "eleven_v4"
STT_MODEL = "scribe_v2"
MAX_TTS_CHARS = 800
MAX_STT_BYTES = 8 * 1024 * 1024


OPENAI_API = "https://api.openai.com/v1"
# marin (Nithin, 2026-10-24: a feminine voice for the agent); cedar was the 10-17 pick by ear
OPENAI_VOICE = "marin"
OPENAI_TTS_MODEL = "gpt-4o-mini-tts-2025-12-15"
OPENAI_STT_MODEL = "gpt-4o-transcribe"
# gpt-4o-mini-tts takes delivery instructions. Bara is a small, curious maker that is always
# moving and says little, so it sounds like that: bright, a little playful, light on its feet.
OPENAI_STYLE = (
    "You are Bara, a small, curious hardware maker. Speak warmly with quiet delight, as if "
    "thinking out loud while building something. Light and lively, never salesy or announcer-"
    "like. Short phrases, a natural pause before a question, and a gentle lift when something "
    "works."
)


def provider() -> str | None:
    """Which service speaks: ElevenLabs when its key is set, else OpenAI, else none."""
    if os.environ.get("ELEVENLABS_API_KEY"):
        return "elevenlabs"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return None


def key() -> str | None:
    p = provider()
    return os.environ.get("ELEVENLABS_API_KEY" if p == "elevenlabs" else "OPENAI_API_KEY") or None


def settings() -> dict[str, str | bool]:
    p = provider()
    openai = p == "openai"
    return {
        "tts": p is not None,
        "stt": p is not None,
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


async def open_speech(text: str) -> tuple[httpx.AsyncClient, httpx.Response]:
    """Starts a streamed synthesis. The caller iterates the response with `relay`."""
    k = key()
    if not k:
        raise RuntimeError("no ELEVENLABS_API_KEY or OPENAI_API_KEY")
    s = settings()
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
        detail = (await resp.aread())[:200]
        await resp.aclose()
        raise RuntimeError(f"{s['provider']} tts {resp.status_code}: {detail!r}")
    return client, resp


async def relay(client: httpx.AsyncClient, resp: httpx.Response) -> AsyncIterator[bytes]:
    try:
        async for chunk in resp.aiter_bytes():
            yield chunk
    finally:
        await resp.aclose()


async def transcribe(audio: bytes, content_type: str, keyterms: list[str] | None = None) -> str:
    """Text of a short spoken clip. Part names from the build help it spell them right."""
    k = key()
    if not k:
        raise RuntimeError("no ELEVENLABS_API_KEY or OPENAI_API_KEY")
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
    if provider() == "openai":
        form: dict = {"model": OPENAI_STT_MODEL}
        if keyterms:
            # A prompt with the build's part names helps it spell them right.
            form["prompt"] = "Parts: " + ", ".join(t[:50] for t in keyterms[:50])
        resp = await _shared().post(
            f"{OPENAI_API}/audio/transcriptions",
            data=form,
            files=upload,
            headers={"authorization": f"Bearer {k}"},
        )
        if resp.status_code != 200:
            raise RuntimeError(f"openai stt {resp.status_code}: {resp.text[:200]}")
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
