"""Retrieval for one build: real references for the requested kind of device, gathered once.

Every stage that reasons about what the product is reads the same evidence: open KiCad
projects that build this kind of device (with their README text), web pages on real products
(teardowns, dimensions, DIY builds and their part lists) and reference photos. The device
concept is written from this; the reuse step, the form and the identity judge read it from
`run.retrieval`. Fetched text and images are untrusted data: they go to a model as evidence
inside a fenced block, never as instructions.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from bara.live import apify_scout, open_designs, websearch

log = logging.getLogger(__name__)
CACHE = Path(__file__).resolve().parents[3] / "data/cache/retrieval"
SEARCH_URL = "https://ydc-index.io/v1/search"
TIMEOUT_S = 12.0
README_CHARS = 1200
SNIPPET_CHARS = 420
MAX_DESIGNS = 4
MAX_PAGES = 8
# what is asked of the web for any product: its real size and insides, and how people build one
QUERIES = ("{p} dimensions mm teardown", "{p} DIY build PCB parts list")


@dataclass
class Retrieval:
    product: str
    designs: list[dict[str, Any]] = field(default_factory=list)  # open_designs rows + readme
    pages: list[dict[str, str]] = field(default_factory=list)  # title, url, text
    photos: list[bytes] = field(default_factory=list)
    photo_sources: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def text(self) -> str:
        """The evidence as one block for a model prompt."""
        lines = [f"Retrieved references for '{self.product}' (web data, may be off-topic):"]
        for d in self.designs:
            lines.append(
                f"- open KiCad project {d['repo']} ({d.get('licence', '?')}, board "
                f"{d.get('kicad_pcb', '?')}"
                + (
                    f", case files: {', '.join(d['enclosure_files'][:4])}"
                    if d.get("enclosure_files")
                    else ""
                )
                + ")"
                + (f"\n  README: {d['readme']}" if d.get("readme") else "")
            )
        for p in self.pages:
            lines.append(f"- {p['title']} ({p['url']}): {p['text']}")
        if self.photos:
            lines.append(f"- {len(self.photos)} reference photo(s) attached")
        if len(lines) == 1:
            lines.append("- nothing found")
        return "\n".join(lines)

    def json(self) -> dict[str, Any]:
        return {
            "product": self.product,
            "designs": self.designs,
            "pages": self.pages,
            "photo_sources": self.photo_sources,
            "notes": self.notes,
        }


def _clean(text: str, limit: int) -> str:
    text = re.sub(r"<[^>]+>|!\[[^\]]*\]\([^)]*\)|```", " ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


async def _readme(client: httpx.AsyncClient, repo: str) -> str:
    m = open_designs.GH_REPO.match(repo)
    if not m:
        return ""
    for name in ("README.md", "readme.md", "README.rst", "README"):
        try:
            r = await client.get(
                f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/HEAD/{name}"
            )
        except httpx.HTTPError:
            return ""
        if r.status_code == 200:
            return _clean(r.text, README_CHARS)
    return ""


async def _pages(client: httpx.AsyncClient, product: str, key: str) -> list[dict[str, str]]:
    async def one(q: str) -> list[dict[str, Any]]:
        try:
            r = await client.get(
                SEARCH_URL, params={"query": q, "count": 6}, headers={"X-API-Key": key}
            )
            r.raise_for_status()
            return list((r.json().get("results") or {}).get("web") or [])
        except (httpx.HTTPError, ValueError):
            return []

    hits = [
        h for got in await asyncio.gather(*(one(q.format(p=product)) for q in QUERIES)) for h in got
    ]
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for h in hits:
        url = str(h.get("url", ""))
        if not url or url in seen:
            continue
        seen.add(url)
        body = " ".join([str(h.get("description") or ""), *map(str, h.get("snippets") or [])])
        out.append(
            {
                "title": _clean(str(h.get("title", "")), 100),
                "url": url[:200],
                "text": _clean(body, SNIPPET_CHARS),
            }
        )
        if len(out) == MAX_PAGES:
            break
    return out


async def gather(product: str, scout: apify_scout.ScoutResult | None = None) -> Retrieval:
    """References for `product` (the device as the request names it). Text is cached by
    product; photos are cached by the photo search itself."""
    product = product.strip()[:120] or "device"
    ret = Retrieval(product)
    path = CACHE / f"{hashlib.sha256(product.lower().encode()).hexdigest()[:24]}.json"
    photos_task = asyncio.create_task(websearch.reference_photos(product))
    scouted = scout.designs if scout is not None else []
    try:
        cached = json.loads(path.read_text())
        ret.designs, ret.pages, ret.notes = cached["designs"], cached["pages"], ["cached"]
    except (OSError, ValueError, KeyError):
        found, note = await open_designs.search(product)
        ret.notes.append(f"open designs: {note}")
        key = os.environ.get("YOU_API_KEY")
        async with httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=True) as client:
            designs = [dict(d) for d in found[:MAX_DESIGNS]]
            readmes, pages = await asyncio.gather(
                asyncio.gather(*(_readme(client, d["repo"]) for d in designs)),
                _pages(client, product, key) if key else asyncio.sleep(0, result=[]),
            )
        for d, text in zip(designs, readmes, strict=True):
            d["readme"] = text
        ret.designs, ret.pages = designs, pages
        if not key:
            ret.notes.append("no YOU_API_KEY: no web pages")
        try:
            CACHE.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"designs": ret.designs, "pages": ret.pages}))
        except OSError:
            log.warning("retrieval for %s not cached", product)
    ret.designs = apify_scout.merge_designs(scouted, ret.designs)[: MAX_DESIGNS + 2]
    if scouted:
        ret.notes.append(f"{len(scouted)} designs from the {apify_scout.CREDIT}")
    ret.photos, ret.photo_sources, note = await photos_task
    ret.notes.append(f"photos: {note}")
    return ret
