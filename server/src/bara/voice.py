"""Bara's voice: ElevenLabs text to speech (streamed) and speech to text (Scribe).

The key stays on the server (ELEVENLABS_API_KEY). The voice and model can be changed without a
code change: BARA_TTS_VOICE (default Charlotte, warm and conversational) and BARA_TTS_MODEL
(default eleven_v4, the most natural delivery; eleven_flash_v2_5 answers faster).
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


def key() -> str | None:
    return os.environ.get("ELEVENLABS_API_KEY") or None


def settings() -> dict[str, str | bool]:
    return {
        "tts": key() is not None,
        "stt": key() is not None,
        "voice": os.environ.get("BARA_TTS_VOICE", DEFAULT_VOICE),
        "model": os.environ.get("BARA_TTS_MODEL", DEFAULT_MODEL),
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


async def open_speech(text: str) -> tuple[httpx.AsyncClient, httpx.Response]:
    """Starts a streamed synthesis. The caller iterates the response and closes both."""
    k = key()
    if not k:
        raise RuntimeError("no ELEVENLABS_API_KEY")
    s = settings()
    client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))
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
        await client.aclose()
        raise RuntimeError(f"elevenlabs tts {resp.status_code}: {detail!r}")
    return client, resp


async def relay(client: httpx.AsyncClient, resp: httpx.Response) -> AsyncIterator[bytes]:
    try:
        async for chunk in resp.aiter_bytes():
            yield chunk
    finally:
        await resp.aclose()
        await client.aclose()


async def transcribe(audio: bytes, content_type: str, keyterms: list[str] | None = None) -> str:
    """Text of a short spoken clip. Part names from the build help it spell them right."""
    k = key()
    if not k:
        raise RuntimeError("no ELEVENLABS_API_KEY")
    ext = (
        "webm"
        if "webm" in content_type
        else "ogg"
        if "ogg" in content_type
        else "mp4"
        if "mp4" in content_type
        else "wav"
    )
    data: dict = {"model_id": STT_MODEL, "tag_audio_events": "false"}
    if keyterms:
        data["keyterms"] = [t[:50] for t in keyterms[:50]]
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{API}/speech-to-text",
            data=data,
            files={"file": (f"speech.{ext}", audio, content_type or "application/octet-stream")},
            headers={"xi-api-key": k},
        )
    if resp.status_code != 200:
        raise RuntimeError(f"elevenlabs stt {resp.status_code}: {resp.text[:200]}")
    return str(resp.json().get("text") or "").strip()
