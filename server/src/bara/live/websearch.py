"""Pictures of the real product from a You.com web search for its name plus "3d model", so
the form and the identity judge see what the device looks like instead of drawing it from
memory.

The key comes from the environment only (YOU_API_KEY). Search results and downloaded images
are untrusted data: they are only ever shown to the model as pictures, never as instructions.
Answers are cached on disk by query, so a repeat build makes no network call.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

import httpx

from bara.llm import record_usage

log = logging.getLogger(__name__)
SEARCH_URL = "https://ydc-index.io/v1/search"
_DEFAULT_CACHE = Path(__file__).resolve().parents[3] / "data/cache/web"
CACHE = Path(os.environ.get("BARA_WEB_CACHE_DIR") or _DEFAULT_CACHE)
MAX_IMAGE_BYTES = 3_000_000
MIN_IMAGE_BYTES = 4_000  # favicons and blank placeholders
TIMEOUT_S = 15.0


def media_type(data: bytes) -> str | None:
    """The image format by magic bytes, for the formats the model accepts."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _query(product: str) -> str:
    # the plain product name plus "3d model" finds clean studio renders of the whole device
    words = product.strip().split()
    if words and words[0].lower() in ("a", "an", "the", "my"):
        words = words[1:]
    return f"{' '.join(words)[:120]} 3d model"


async def _search(client: httpx.AsyncClient, query: str, key: str) -> list[dict[str, Any]]:
    resp = await client.get(
        SEARCH_URL, params={"query": query, "count": 10}, headers={"X-API-Key": key}
    )
    resp.raise_for_status()
    return list((resp.json().get("results") or {}).get("web") or [])


async def _fetch(client: httpx.AsyncClient, url: str) -> bytes | None:
    try:
        resp = await client.get(url, follow_redirects=True)
    except httpx.HTTPError:
        return None
    data = resp.content
    if resp.status_code != 200 or not MIN_IMAGE_BYTES <= len(data) <= MAX_IMAGE_BYTES:
        return None
    return data if media_type(data) else None


async def reference_photos(product: str, limit: int = 3) -> tuple[list[bytes], list[str], str]:
    """(images, source pages, note). Empty with a reason in note when nothing was usable."""
    query = _query(product)
    folder = CACHE / hashlib.sha256(query.encode()).hexdigest()[:24]
    index = folder / "index.json"
    try:
        sources = json.loads(index.read_text())
        imgs = [(folder / f"{i}.img").read_bytes() for i in range(len(sources))]
        return imgs, sources, "ok (cached)"
    except (OSError, ValueError):
        pass
    key = os.environ.get("YOU_API_KEY")
    if not key:
        return [], [], "no YOU_API_KEY"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            hits = await _search(client, query, key)
            record_usage("you.com", "search", "websearch", {"searches": 1})
            hits = [h for h in hits if h.get("thumbnail_url")]
            got = await asyncio.gather(*(_fetch(client, h["thumbnail_url"]) for h in hits))
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("web reference search failed: %s", exc)
        return [], [], f"search failed: {type(exc).__name__}"
    imgs: list[bytes] = []
    sources: list[str] = []
    for hit, data in zip(hits, got, strict=True):
        if data is not None and data not in imgs:
            imgs.append(data)
            sources.append(str(hit.get("url", "")))
        if len(imgs) == limit:
            break
    if not imgs:
        return [], [], "no usable product photos in the results"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        for i, data in enumerate(imgs):
            (folder / f"{i}.img").write_bytes(data)
        index.write_text(json.dumps(sources))
    except OSError:
        log.warning("web reference photos not cached")
    return imgs, sources, "ok"
