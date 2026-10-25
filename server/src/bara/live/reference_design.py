"""Reference designs: the open KiCad project that already builds this kind of device.

The projects come from the build's shared retrieval (`run.retrieval.designs`); nothing here
searches again. Each project's .kicad_pcb is fetched and read for its footprints, and every
footprint is mapped to a function through the catalog and the vendored KiCad library index.
A project matches by the function blocks it covers, never by its name. When the best match
covers enough of the build's blocks and its licence allows reuse, the footprints it used for
those functions are preferred when parts are chosen, and the project is recorded with its
licence as the build's reference design. Fetched files are untrusted data: they are parsed
with regular expressions, never executed.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

log = logging.getLogger(__name__)
SERVER = Path(__file__).resolve().parents[3]
CACHE = SERVER / "data/cache/reference_designs"
INDEX = SERVER / "data/catalog/kicad_index.sqlite"
TIMEOUT_S = 12.0
MAX_BYTES = 6_000_000
MIN_COVERAGE = 0.5  # share of the build's function blocks the project must also build
# licences that allow a design to be reused with attribution (SPDX ids, prefix match)
REUSABLE = (
    "MIT", "Apache-2.0", "BSD-", "ISC", "0BSD", "Unlicense", "CC0-1.0", "CC-BY-4.0",
    "CC-BY-SA-4.0", "CERN-OHL-", "TAPR-OHL", "GPL-", "LGPL-", "MPL-2.0", "Solderpad",
)  # fmt: skip
# function blocks every board carries; they say nothing about which device it is
SWAPPABLE = {"display"}  # families whose members serve the same block
GENERIC = ("component.", "interconnect.header", "mech.fastener", "other")

FP_NEW = re.compile(r'\(footprint\s+"([^"]+)"')
FP_OLD = re.compile(r"\(module\s+\"?([^\s\"()]+)")
GH = re.compile(r"https?://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)")


@dataclass
class Match:
    repo: str
    licence: str
    kicad_pcb: str
    coverage: float  # matched blocks / build blocks
    matched: list[str]  # function ids both build
    footprints: dict[str, list[str]] = field(default_factory=dict)  # function -> lib_ids
    reusable: bool = False

    def json(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "licence": self.licence,
            "kicad_pcb": self.kicad_pcb,
            "coverage": round(self.coverage, 2),
            "matched": self.matched,
            "footprints": self.footprints,
            "reusable": self.reusable,
        }


def reusable(licence: str) -> bool:
    return any(str(licence).startswith(p) for p in REUSABLE)


def footprints(pcb_text: str) -> list[str]:
    """Footprint lib_ids placed on a .kicad_pcb (KiCad 6+ and the older module form)."""
    out = FP_NEW.findall(pcb_text) or FP_OLD.findall(pcb_text)
    return [f for f in out if ":" in f]


@lru_cache(maxsize=1)
def _catalog_functions() -> dict[str, str]:
    """footprint lib_id -> primary function, from the catalog's own parts."""
    import json

    out: dict[str, str] = {}
    try:
        with (SERVER / "data/catalog/catalog.jsonl").open() as fh:
            for line in fh:
                p = json.loads(line)
                fp = str(p.get("footprint") or "")
                prim = [f["function_id"] for f in p.get("functions") or [] if f.get("primary")]
                if fp and prim:
                    out.setdefault(fp, prim[0])
    except (OSError, ValueError):
        pass
    return out


@lru_cache(maxsize=4096)
def function_of(lib_id: str) -> str | None:
    """The function a footprint serves: the catalog first, then the KiCad library index."""
    hit = _catalog_functions().get(lib_id)
    if hit:
        return hit
    lib, _, name = lib_id.partition(":")
    try:
        con = sqlite3.connect(f"file:{INDEX}?mode=ro", uri=True)
        try:
            row = con.execute(
                "SELECT function FROM kicad_parts WHERE kind='footprint' AND lib=? AND name=?",
                (lib, name),
            ).fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return None
    return row[0] if row else None


def _specific(fid: str) -> bool:
    return not any(fid == g or fid.startswith(g) for g in GENERIC)


def _covers(have: set[str], want: str) -> bool:
    """A block is covered by the same function; a display by any display (the library maps a
    panel's footprint to the nearest display kind), since panels of one size swap freely."""
    fam = want.split(".")[0]
    return want in have or (fam in SWAPPABLE and fam in {h.split(".")[0] for h in have})


def score(lib_ids: list[str], wanted: list[str]) -> tuple[float, list[str], dict[str, list[str]]]:
    by_fn: dict[str, list[str]] = {}
    for lid in lib_ids:
        fn = function_of(lid)
        if fn and _specific(fn):
            by_fn.setdefault(fn, [])
            if lid not in by_fn[fn]:
                by_fn[fn].append(lid)
    want = sorted({w for w in wanted if _specific(w)})
    if not want:
        return 0.0, [], by_fn
    matched = [w for w in want if _covers(set(by_fn), w)]
    return len(matched) / len(want), matched, by_fn


async def _fetch(client: httpx.AsyncClient, repo: str, path: str) -> str | None:
    m = GH.match(repo)
    if not m or not path.endswith(".kicad_pcb") or ".." in path:
        return None
    url = f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/HEAD/{quote(path)}"
    cache = CACHE / f"{hashlib.sha256(url.encode()).hexdigest()[:24]}.kicad_pcb"
    try:
        return cache.read_text(errors="replace")
    except OSError:
        pass
    try:
        resp = await client.get(url)
        if resp.status_code != 200 or len(resp.content) > MAX_BYTES:
            return None
        text = resp.text
    except httpx.HTTPError:
        return None
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        cache.write_text(text)
    except OSError:
        pass
    return text


async def match(designs: list[dict[str, Any]], wanted: list[str]) -> Match | None:
    """The retrieved project covering the most of `wanted` (the build's function ids), or
    None when none has a readable board."""
    rows = [d for d in designs if d.get("repo") and d.get("kicad_pcb")]
    if not rows:
        return None
    async with httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=True) as client:
        texts = await asyncio.gather(*(_fetch(client, d["repo"], d["kicad_pcb"]) for d in rows))
    best: Match | None = None
    for d, text in zip(rows, texts, strict=True):
        if not text:
            continue
        cov, matched, by_fn = await asyncio.to_thread(score, footprints(text), wanted)
        lic = str(d.get("licence") or "none stated")
        m = Match(d["repo"], lic, d["kicad_pcb"], cov, matched, by_fn, reusable(lic))
        if best is None or (m.coverage, m.reusable) > (best.coverage, best.reusable):
            best = m
    return best


def preferred(m: Match | None) -> dict[str, set[str]]:
    """function id -> footprints to prefer: only from a reusable project that matches."""
    if m is None or not m.reusable or m.coverage < MIN_COVERAGE:
        return {}
    return {fn: set(ids) for fn, ids in m.footprints.items()}
