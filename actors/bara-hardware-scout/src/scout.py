"""Scouting logic of the Bara Hardware Scout Actor (no Apify import, so the engine can run it
locally and tests can exercise the parsers offline).

Sources, all public and read without a login:
  * GitHub's public repository search and git-tree listing: open-source KiCad projects, with the
    licence GitHub detected (falling back to sniffing the LICENSE file) and the README text.
  * raw.githubusercontent.com for README, LICENSE and BOM files of those repositories.
  * the public jlcsearch part index (https://jlcsearch.tscircuit.com, a mirror of the LCSC /
    JLCPCB catalogue): price breaks and stock for an LCSC part number.

Nothing here reads personal data: repository owners appear only as part of a public repo URL.
Fetched text is data. It is parsed with regular expressions and never executed.
"""

from __future__ import annotations

import asyncio
import csv
import io
import os
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, quote_plus

import httpx

GITHUB_API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
PARTS_API = "https://jlcsearch.tscircuit.com/api/search"
USER_AGENT = "bara-hardware-scout/0.1 (+public-pages-only)"
TIMEOUT_S = 15.0
README_CHARS = 1200
LIBRARY_FOOTPRINTS = 40  # a repo with more footprints than any one device is a parts library
SHELL_EXT = (".stl", ".step", ".stp", ".3mf", ".f3d", ".scad")
STOP = {"a", "an", "the", "with", "and", "for", "of", "my", "open", "source", "kicad", "github"}

LCSC_ID = re.compile(r"\bC(\d{4,9})\b")
GH_REPO = re.compile(r"https?://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)")

# (SPDX id, pattern on the licence text); first match wins, so specific before general
LICENCE_SNIFF: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (spdx, re.compile(pat, re.I | re.S))
    for spdx, pat in (
        ("CERN-OHL-S-2.0", r"cern open hardware licen[cs]e.{0,80}strongly reciprocal"),
        ("CERN-OHL-W-2.0", r"cern open hardware licen[cs]e.{0,80}weakly reciprocal"),
        ("CERN-OHL-P-2.0", r"cern open hardware licen[cs]e.{0,80}permissive"),
        ("TAPR-OHL", r"tapr open hardware license"),
        ("Apache-2.0", r"apache license.{0,40}version 2\.0"),
        ("AGPL-3.0", r"gnu affero general public license"),
        ("LGPL-3.0", r"gnu lesser general public license"),
        ("GPL-3.0", r"gnu general public license.{0,40}version 3"),
        ("GPL-2.0", r"gnu general public license.{0,40}version 2"),
        ("MPL-2.0", r"mozilla public license.{0,40}2\.0"),
        ("CC-BY-SA-4.0", r"attribution-sharealike 4\.0"),
        ("CC-BY-NC-4.0", r"attribution-noncommercial 4\.0"),
        ("CC-BY-4.0", r"creative commons attribution 4\.0"),
        ("CC0-1.0", r"cc0 1\.0|creative commons zero"),
        ("Unlicense", r"this is free and unencumbered software"),
        ("ISC", r"permission to use, copy, modify, and/or distribute this software"),
        ("BSD-3-Clause", r"redistribution and use in source and binary forms.{0,900}neither the name"),
        ("BSD-2-Clause", r"redistribution and use in source and binary forms"),
        ("MIT", r"permission is hereby granted, free of charge"),
    )
)  # fmt: skip


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def words(text: str) -> list[str]:
    """Query words without filler, singular, de-duplicated, in order."""
    out: list[str] = []
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        if w in STOP:
            continue
        w = w[:-1] if len(w) > 3 and w.endswith("s") else w
        if w not in out:
            out.append(w)
    return out


def clean_text(text: str, limit: int = README_CHARS) -> str:
    text = re.sub(r"<[^>]+>|!\[[^\]]*\]\([^)]*\)|```", " ", text or "")
    return re.sub(r"\s+", " ", text).strip()[:limit]


def detect_licence(text: str) -> str:
    """SPDX id of a licence text, or "" when it is not recognised."""
    head = text[:6000]
    for spdx, pat in LICENCE_SNIFF:
        if pat.search(head):
            return spdx
    return ""


def lcsc_ids(text: str, limit: int = 40) -> list[str]:
    """LCSC part numbers (C12345) in a README or BOM, first-seen order."""
    seen: list[str] = []
    for m in LCSC_ID.finditer(text or ""):
        cid = f"C{m.group(1)}"
        if cid not in seen:
            seen.append(cid)
        if len(seen) == limit:
            break
    return seen


def bom_lcsc_ids(csv_text: str) -> list[str]:
    """LCSC numbers from a BOM csv: any column whose header mentions LCSC / JLC / supplier."""
    try:
        rows = list(csv.reader(io.StringIO(csv_text)))
    except csv.Error:
        return []
    if len(rows) < 2:
        return []
    cols = [
        i
        for i, h in enumerate(rows[0])
        if re.search(r"lcsc|jlc|supplier|part ?(number|no)", h, re.I)
    ]
    found: list[str] = []
    for row in rows[1:]:
        for i in cols:
            if i < len(row):
                found += lcsc_ids(row[i])
    return list(dict.fromkeys(found))


def price_breaks(raw: Any) -> list[tuple[int, float]]:
    """"1-99:0.0436,100-299:0.0358,9000-:0.02" (or a bare number) -> [(1, 0.0436), (100, ...)]."""
    if isinstance(raw, int | float):
        return [(1, float(raw))]
    out: list[tuple[int, float]] = []
    for chunk in str(raw or "").split(","):
        m = re.match(r"\s*(\d+)\s*-\s*\d*\s*:\s*([0-9.]+)\s*$", chunk)
        if m:
            out.append((int(m.group(1)), float(m.group(2))))
    return sorted(out)


def unit_price(raw: Any, qty: int = 1) -> float | None:
    """The unit price at `qty` (the break at or below it), None when the listing has none."""
    brk = price_breaks(raw)
    if not brk:
        return None
    price = brk[0][1]
    for start, p in brk:
        if start <= qty:
            price = p
    return price


def tree_summary(paths: list[str]) -> dict[str, Any] | None:
    """KiCad and shell files in a repo tree; None when it has no board (or is a library)."""
    low = [p.lower() for p in paths]
    pcbs = [p for p, lp in zip(paths, low, strict=True) if lp.endswith(".kicad_pcb")]
    if not pcbs or sum(lp.endswith(".kicad_mod") for lp in low) > LIBRARY_FOOTPRINTS:
        return None
    pick = lambda ext: [p for p, lp in zip(paths, low, strict=True) if lp.endswith(ext)]  # noqa: E731
    shells = [
        p
        for p, lp in zip(paths, low, strict=True)
        if lp.endswith(SHELL_EXT) and "3dshapes" not in lp
    ]
    boms = [p for p in pick(".csv") if re.search(r"bom|parts|lcsc|jlc", p, re.I)]
    licences = [
        p for p in paths if re.match(r"(?:licen[cs]e|copying)[^/]*$", p.rsplit("/", 1)[-1], re.I)
    ]
    return {
        "kicad_pcb": sorted(pcbs, key=lambda p: (p.count("/"), p))[0],
        "kicad_pcb_count": len(pcbs),
        "kicad_sch": sorted(pick(".kicad_sch"), key=lambda p: (p.count("/"), p))[:1],
        "enclosure_files": shells[:12],
        "bom_files": boms[:2],
        "licence_files": sorted(licences, key=lambda p: (p.count("/"), p))[:1],
    }


def design_item(repo: dict[str, Any], tree: dict[str, Any], readme: str, licence: str,
                licence_source: str, ids: list[str]) -> dict[str, Any]:  # fmt: skip
    full = str(repo["full_name"])
    branch = repo.get("default_branch") or "HEAD"
    return {
        "type": "design",
        "name": repo.get("name") or full.split("/")[-1],
        "repo": f"https://github.com/{full}",
        "description": clean_text(str(repo.get("description") or ""), 200),
        "stars": int(repo.get("stargazers_count") or 0),
        "licence": licence or "none stated",
        "licence_source": licence_source,
        "kicad_pcb": tree["kicad_pcb"],
        "kicad_pcb_url": f"{RAW}/{full}/{branch}/{quote(tree['kicad_pcb'])}",
        "kicad_sch": tree["kicad_sch"],
        "enclosure_files": tree["enclosure_files"],
        "fit": "close" if tree["enclosure_files"] else "pcb-only",
        "readme": readme,
        "lcsc_ids": ids,
        "source": "github",
        "scraped_at": now_iso(),
    }


def part_item(row: dict[str, Any], qty: int = 1) -> dict[str, Any]:
    cid = f"C{row['lcsc']}"
    mpn = str(row.get("mfr") or "")
    q = quote_plus(mpn)
    return {
        "type": "part",
        "lcsc_id": cid,
        "mpn": mpn,
        "package": str(row.get("package") or ""),
        "description": clean_text(str(row.get("description") or ""), 200),
        "stock": int(row.get("stock") or 0),
        "unit_price_usd": unit_price(row.get("price"), qty),
        "price_breaks": [{"from_qty": a, "usd": b} for a, b in price_breaks(row.get("price"))],
        "basic_part": bool(row.get("is_basic")),
        "product_url": f"https://www.lcsc.com/product-detail/{cid}.html",
        "buy_urls": {
            "lcsc": f"https://www.lcsc.com/product-detail/{cid}.html",
            "digikey": f"https://www.digikey.com/en/products/result?keywords={q}",
            "mouser": f"https://www.mouser.com/c/?q={q}",
        },
        "source": "jlcsearch",
        "scraped_at": now_iso(),
    }


def _headers() -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


async def _get_text(client: httpx.AsyncClient, url: str, limit: int = 200_000) -> str:
    try:
        r = await client.get(url, headers={"User-Agent": USER_AGENT})
    except httpx.HTTPError:
        return ""
    return r.text[:limit] if r.status_code == 200 else ""


async def search_repos(client: httpx.AsyncClient, query: str, max_repos: int) -> list[dict[str, Any]]:
    ws = words(query)
    if not ws:
        return []
    found: dict[str, dict[str, Any]] = {}
    for q in (" ".join([*ws, "kicad"]), " ".join([*ws, "topic:kicad"])):
        try:
            r = await client.get(
                f"{GITHUB_API}/search/repositories",
                params={"q": q, "sort": "stars", "per_page": min(30, max_repos * 2)},
                headers=_headers(),
            )
        except httpx.HTTPError:
            continue
        if r.status_code != 200:
            continue
        for item in r.json().get("items") or []:
            if not item.get("private") and not item.get("fork") and not item.get("archived"):
                found.setdefault(str(item["full_name"]), item)
    return list(found.values())[: max_repos * 2]


async def inspect_repo(client: httpx.AsyncClient, repo: dict[str, Any]) -> dict[str, Any] | None:
    full, branch = str(repo["full_name"]), repo.get("default_branch") or "HEAD"
    try:
        r = await client.get(
            f"{GITHUB_API}/repos/{full}/git/trees/{branch}?recursive=1", headers=_headers()
        )
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    tree = tree_summary([str(t.get("path", "")) for t in r.json().get("tree") or []])
    if tree is None:
        return None
    base = f"{RAW}/{full}/{branch}"
    readme = ""
    for name in ("README.md", "readme.md", "README.rst", "README"):
        readme = await _get_text(client, f"{base}/{name}", 60_000)
        if readme:
            break
    spdx = str((repo.get("license") or {}).get("spdx_id") or "")
    licence, source = (spdx, "github") if spdx and spdx != "NOASSERTION" else ("", "")
    if not licence and tree["licence_files"]:
        text = await _get_text(client, f"{base}/{quote(tree['licence_files'][0])}", 8000)
        licence = detect_licence(text)
        source = "licence file" if licence else ""
    ids = lcsc_ids(readme)
    for bom in tree["bom_files"]:
        ids += bom_lcsc_ids(await _get_text(client, f"{base}/{quote(bom)}"))
    return design_item(repo, tree, clean_text(readme), licence, source, list(dict.fromkeys(ids)))


async def find_designs(client: httpx.AsyncClient, query: str, max_repos: int) -> list[dict[str, Any]]:
    repos = await search_repos(client, query, max_repos)
    got = await asyncio.gather(*(inspect_repo(client, r) for r in repos))
    designs = [d for d in got if d]
    designs.sort(key=lambda d: (d["fit"] != "close", -d["stars"]))
    return designs[:max_repos]


async def quote_part(client: httpx.AsyncClient, cid: str, qty: int = 1) -> dict[str, Any] | None:
    m = LCSC_ID.fullmatch(cid.strip().upper())
    if not m:
        return None
    try:
        r = await client.get(PARTS_API, params={"q": f"C{m.group(1)}", "limit": 1},
                             headers={"User-Agent": USER_AGENT})
        rows = r.json().get("components") or [] if r.status_code == 200 else []
    except (httpx.HTTPError, ValueError):
        return None
    for row in rows:
        if f"C{row.get('lcsc')}" == f"C{m.group(1)}":
            return part_item(row, qty)
    return None


async def quote_parts(client: httpx.AsyncClient, ids: list[str]) -> list[dict[str, Any]]:
    sem = asyncio.Semaphore(5)

    async def one(cid: str) -> dict[str, Any] | None:
        async with sem:
            return await quote_part(client, cid)

    return [p for p in await asyncio.gather(*(one(c) for c in ids)) if p]


async def scout(inp: dict[str, Any], client: httpx.AsyncClient | None = None) -> list[dict[str, Any]]:
    """The Actor's whole job. Input: query (device or function), lcscIds, maxRepos,
    maxPartsFromDesigns. Output: design items then part items (the parts the designs
    use, then any explicitly requested ids), de-duplicated."""
    own = client is None
    counter = {"requests": 0}

    async def count(_request: httpx.Request) -> None:
        counter["requests"] += 1

    client = client or httpx.AsyncClient(
        timeout=TIMEOUT_S, follow_redirects=True, event_hooks={"request": [count]}
    )
    try:
        query = str(inp.get("query") or "").strip()[:120]
        designs = await find_designs(client, query, int(inp.get("maxRepos") or 6)) if query else []
        wanted = [str(c) for c in inp.get("lcscIds") or []]
        for d in designs:
            wanted += d["lcsc_ids"][: int(inp.get("maxPartsFromDesigns") or 20)]
        parts = await quote_parts(client, list(dict.fromkeys(wanted)))
        stats = {"type": "stats", "pages_fetched": counter["requests"], "designs": len(designs),
                 "parts": len(parts), "scraped_at": now_iso()}  # fmt: skip
        return [*designs, *parts, stats]
    finally:
        if own:
            await client.aclose()
