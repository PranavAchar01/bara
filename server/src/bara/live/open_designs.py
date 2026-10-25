"""Open hardware projects (a KiCad board plus a printable shell) that already build the device,
from the scouted list in docs/shell-sources.json and, for any product, from a live web search
whose GitHub hits are checked for a .kicad_pcb. The reuse stage names the closest ones.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx

SOURCES = Path(__file__).resolve().parents[4] / "docs/shell-sources.json"
FIT_RANK = {"exact": 0, "close": 1, "weak": 2, "pcb-only": 3}
FIT_SCORE = {"exact": 1.0, "close": 0.8, "weak": 0.5, "pcb-only": 0.3}
MIN_OVERLAP = 0.66  # share of the listed device's words the request must contain
STOP = {"a", "an", "the", "with", "and", "for", "of", "my", "style", "large"}


def _words(text: str) -> set[str]:
    out = set()
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        if w in STOP:
            continue
        out.add(w[:-1] if len(w) > 3 and w.endswith("s") else w)
    return out


@lru_cache(maxsize=1)
def _entries() -> list[dict[str, Any]]:
    try:
        return [e for e in json.loads(SOURCES.read_text()) if e.get("candidates")]
    except (OSError, ValueError):
        return []


def closest(request: str, device: str = "") -> tuple[str, list[dict[str, Any]]]:
    """(the listed device that matched, its candidates best fit first); ("", []) when none."""
    asked = _words(request) | _words(device)
    best: tuple[float, int, dict[str, Any]] | None = None
    for entry in _entries():
        listed = _words(entry["device"])
        if not listed:
            continue
        overlap = len(listed & asked) / len(listed)
        # the fuller match wins a tie ("game boy" over "raspberry pi game boy")
        key = (overlap, -len(listed), entry)
        if overlap >= MIN_OVERLAP and (best is None or key[:2] > best[:2]):
            best = key
    if best is None:
        return "", []
    entry = best[2]
    cands = sorted(entry["candidates"], key=lambda c: FIT_RANK.get(c.get("fit", ""), 9))
    return entry["device"], cands


def rows(request: str, device: str = "", limit: int = 3) -> list[dict[str, Any]]:
    """reuse.decided `considered` rows for the scouted open designs matching the request."""
    return to_rows(closest(request, device)[1], limit)


GH_REPO = re.compile(r"https?://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)")
NOT_REPOS = {"topics", "search", "orgs", "sponsors", "features", "marketplace", "collections"}
SHELL_EXT = (".stl", ".step", ".stp", ".3mf", ".f3d", ".scad")
SEARCH_CACHE = Path(__file__).resolve().parents[3] / "data/cache/open_designs"
MAX_REPOS = 10
SEARCH_URL = "https://ydc-index.io/v1/search"
LIBRARY_FOOTPRINTS = 40  # more footprints than any one device's board carries
TIMEOUT_S = 10.0


def _repos(hits: list[dict[str, Any]], product: str) -> list[tuple[str, str]]:
    want = _words(product) - {"open", "source", "kicad", "github"}
    out: list[tuple[str, str]] = []
    for hit in hits:
        m = GH_REPO.match(str(hit.get("url", "")))
        if not m or m.group(1).lower() in NOT_REPOS:
            continue
        repo = (m.group(1), m.group(2).removesuffix(".git"))
        if repo[1].lower().endswith((".pretty", ".3dshapes")):  # KiCad library folders
            continue
        text = " ".join(str(hit.get(k, "")) for k in ("title", "description", "url"))
        text += " " + " ".join(str(x) for x in hit.get("snippets") or [])
        if len(want & _words(text)) < len(want) - len(want) // 3:  # off-topic hit
            continue
        if repo not in out:
            out.append(repo)
    return out


def _gh_headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def _github_repos(client: Any, product: str) -> list[tuple[str, str]]:
    """GitHub's own repo search for the product's words plus "kicad", most starred first."""
    words = sorted(_words(product))
    if not words:
        return []
    try:
        resp = await client.get(
            "https://api.github.com/search/repositories",
            params={"q": " ".join([*words, "kicad"]), "sort": "stars", "per_page": 6},
            headers=_gh_headers(),
        )
        items = resp.json().get("items") or [] if resp.status_code == 200 else []
    except Exception:  # the web search still runs
        return []
    return [tuple(str(i["full_name"]).split("/", 1)) for i in items]  # type: ignore[misc]


async def _inspect(client: Any, owner: str, name: str) -> dict[str, Any] | None:
    """The repo's KiCad board and shell files, from its file tree; None without a board."""
    headers = _gh_headers()
    try:
        meta = await client.get(f"https://api.github.com/repos/{owner}/{name}", headers=headers)
        if meta.status_code != 200:
            return None
        info = meta.json()
        branch = info.get("default_branch") or "main"
        tree = await client.get(
            f"https://api.github.com/repos/{owner}/{name}/git/trees/{branch}?recursive=1",
            headers=headers,
        )
        if tree.status_code != 200:
            return None
        paths = [str(t.get("path", "")) for t in tree.json().get("tree") or []]
    except Exception:  # an unreachable repo is just not a candidate
        return None
    low = [p.lower() for p in paths]
    pcbs = [p for p, lp in zip(paths, low, strict=True) if lp.endswith(".kicad_pcb")]
    footprints = sum(lp.endswith(".kicad_mod") for lp in low)
    if not pcbs or footprints > LIBRARY_FOOTPRINTS:  # a parts library, not a device
        return None
    # part models live in *.3dshapes folders; a shell is a model outside them
    shells = [
        p
        for p, lp in zip(paths, low, strict=True)
        if lp.endswith(SHELL_EXT) and "3dshapes" not in lp
    ]
    licence = ((info.get("license") or {}).get("spdx_id")) or "none stated"
    return {
        "repo": f"https://github.com/{owner}/{name}",
        "licence": licence,
        "fit": "close" if shells else "pcb-only",
        "kicad_pcb": pcbs[0],
        "enclosure_files": shells[:12],
        "stars": int(info.get("stargazers_count") or 0),
    }


async def search(product: str, *, require_you: bool = False) -> tuple[list[dict[str, Any]], str]:
    """Open KiCad projects for any product: GitHub's repo search plus a web search (when
    YOU_API_KEY is set) for its repos, each checked for a .kicad_pcb (and shell files) in its
    tree. (candidates best first, note). Cached by query."""
    key = os.environ.get("YOU_API_KEY")
    if require_you and not key:
        return [], "search failed: no YOU_API_KEY"
    query = f"{product.strip()[:120]} open source KiCad github"
    path = SEARCH_CACHE / f"{hashlib.sha256(query.encode()).hexdigest()[:24]}.json"
    try:
        return json.loads(path.read_text()), "ok (cached)"
    except (OSError, ValueError):
        pass
    queries = (query, f"{product.strip()[:120]} kicad_pcb enclosure github") if key else ()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            pages = await asyncio.gather(
                *(
                    client.get(
                        SEARCH_URL, params={"query": q, "count": 20}, headers={"X-API-Key": key}
                    )
                    for q in queries
                )
            )
            hits = []
            for page in pages:
                page.raise_for_status()
                hits += list((page.json().get("results") or {}).get("web") or [])
            repos = await _github_repos(client, product) + _repos(hits, product)
            repos = list(dict.fromkeys(repos))[:MAX_REPOS]
            found = await asyncio.gather(*(_inspect(client, o, n) for o, n in repos))
    except (httpx.HTTPError, ValueError) as exc:
        return [], f"search failed: {type(exc).__name__}"
    cands = sorted(
        (c for c in found if c),
        key=lambda c: (FIT_RANK.get(c["fit"], 9), -c["stars"]),
    )
    try:
        SEARCH_CACHE.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cands))
    except OSError:
        pass
    return cands, "ok"


def to_rows(cands: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    out = []
    for c in cands[:limit]:
        repo = str(c.get("repo", ""))
        shell = "KiCad + shell" if c.get("fit") in ("exact", "close") else "KiCad board only"
        out.append(
            {
                "design_id": repo,
                "name": f"{repo.rstrip('/').split('/')[-1]} ({c.get('licence', '?')}, "
                f"{c.get('fit', '?')} fit, {shell})"[:80],
                "tier": "compose",
                "score": FIT_SCORE.get(c.get("fit", ""), 0.2),
                "unmet": [],
            }
        )
    return out
