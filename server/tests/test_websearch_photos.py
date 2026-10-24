"""Web reference photos: format sniffing, and a cached search needs no key or network."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from bara.live import websearch

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 16


def test_media_type_is_read_from_the_bytes() -> None:
    assert websearch.media_type(PNG) == "image/png"
    assert websearch.media_type(b"\xff\xd8\xff\xe0rest") == "image/jpeg"
    assert websearch.media_type(b"RIFF\0\0\0\0WEBPVP8 ") == "image/webp"
    assert websearch.media_type(b"<html>") is None


def test_cached_photos_need_no_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(websearch, "CACHE", tmp_path)
    monkeypatch.delenv("YOU_API_KEY", raising=False)
    q = websearch._query("a game boy")
    folder = tmp_path / hashlib.sha256(q.encode()).hexdigest()[:24]
    folder.mkdir()
    (folder / "0.img").write_bytes(PNG)
    (folder / "index.json").write_text(json.dumps(["https://example.org/gb"]))
    imgs, sources, note = asyncio.run(websearch.reference_photos("a game boy"))
    assert imgs == [PNG] and sources == ["https://example.org/gb"] and note == "ok (cached)"
    imgs, _, note = asyncio.run(websearch.reference_photos("a walkie talkie"))
    assert imgs == [] and note == "no YOU_API_KEY"
