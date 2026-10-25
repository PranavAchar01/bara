"""The Apify scout: the front door of retrieval.

Every build starts by running the `bara-hardware-scout` Actor (actors/bara-hardware-scout) for
the requested device: public open-source KiCad projects (licence detected, README, board and
case files, LCSC part numbers) and live price and stock for the parts they use. With APIFY_TOKEN
in the environment the Actor runs on the Apify platform through the Apify API client; without
it the same Actor code runs locally in-process, so the engine works before any account exists.
The results feed the retrieval evidence, the reference-design match and the shopping list, and
per-build numbers (designs found, parts priced, pages crawled) are appended to stats.jsonl.

The token is read from the environment only; it is never logged or written anywhere.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[4]
ACTOR_SRC = ROOT / "actors/bara-hardware-scout/src/scout.py"
CACHE = Path(__file__).resolve().parents[3] / "data/cache/apify_scout"
STATS = CACHE / "stats.jsonl"
CREDIT = "Apify scout"
BUDGET_S = 60.0
CLOUD_TIMEOUT_S = 90
TTL_S = 7 * 86400
LCSC = re.compile(r"C\d{4,9}")


def enabled() -> bool:
    return os.environ.get("BARA_APIFY", "on").lower() not in ("off", "0", "false")


def _actor_id() -> str:
    return os.environ.get("APIFY_ACTOR_ID", "bara-hardware-scout")


def _scout_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("bara_hardware_scout_logic", ACTOR_SRC)
    if spec is None or spec.loader is None:
        raise ImportError(f"scout not found at {ACTOR_SRC}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@dataclass
class ScoutResult:
    query: str
    designs: list[dict[str, Any]] = field(default_factory=list)
    parts: list[dict[str, Any]] = field(default_factory=list)
    mode: str = "off"  # "apify cloud" | "local" | "cached" | "off" | "failed"
    pages_fetched: int = 0
    ms: int = 0
    notes: list[str] = field(default_factory=list)

    def numbers(self) -> dict[str, Any]:
        return {
            "designs_found": len(self.designs),
            "parts_priced": len(self.parts),
            "pages_crawled": self.pages_fetched,
            "mode": self.mode,
        }

    def top_sources(self, n: int = 3) -> list[str]:
        return [
            f"{d['repo'].removeprefix('https://github.com/')} ({d.get('licence', '?')})"
            for d in self.designs[:n]
        ]

    def summary(self) -> str:
        """One line for the build log."""
        if not self.designs and not self.parts:
            return f"{CREDIT} ({self.mode}) found nothing for this device."
        tops = "; ".join(self.top_sources()) or "none"
        return (
            f"{CREDIT} ({self.mode}): {len(self.designs)} open designs, {len(self.parts)} "
            f"parts priced, {self.pages_fetched} public pages crawled. Top: {tops}."
        )

    def json(self) -> dict[str, Any]:
        return {
            **self.numbers(),
            "query": self.query,
            "top": [
                {"repo": d["repo"], "licence": d.get("licence"), "fit": d.get("fit")}
                for d in self.designs[:5]
            ],
        }


def split_items(items: list[dict[str, Any]]) -> tuple[list[dict], list[dict], int]:
    """Dataset items -> (designs, parts, pages fetched). Anything malformed is dropped."""
    designs = [i for i in items if i.get("type") == "design" and i.get("repo")]
    parts = [i for i in items if i.get("type") == "part" and LCSC.fullmatch(str(i.get("lcsc_id")))]
    pages = sum(int(i.get("pages_fetched") or 0) for i in items if i.get("type") == "stats")
    return designs, parts, pages


def _key(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:24]


def _read_cache(path: Path) -> Any | None:
    try:
        data = json.loads(path.read_text())
        return data if time.time() - float(data.get("at", 0)) < TTL_S else None
    except (OSError, ValueError, TypeError):
        return None


def _write_cache(path: Path, data: dict[str, Any]) -> None:
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({**data, "at": time.time()}))
    except OSError:
        log.warning("apify scout cache not written: %s", path.name)


async def _run_cloud(token: str, inp: dict[str, Any]) -> list[dict[str, Any]]:
    from apify_client import ApifyClientAsync

    client = ApifyClientAsync(token)
    run = await client.actor(_actor_id()).call(run_input=inp, timeout=CLOUD_TIMEOUT_S)
    if run is None:
        raise RuntimeError("Actor run returned nothing")
    page = await client.dataset(run.default_dataset_id).list_items()
    return list(page.items)


async def _run_local(inp: dict[str, Any]) -> list[dict[str, Any]]:
    return await _scout_module().scout(inp)


async def execute(inp: dict[str, Any]) -> tuple[list[dict[str, Any]], str, list[str]]:
    """Run the Actor: on Apify when APIFY_TOKEN is set (local fallback on failure), else local."""
    token = os.environ.get("APIFY_TOKEN")
    notes: list[str] = []
    if token:
        try:
            return await asyncio.wait_for(_run_cloud(token, inp), BUDGET_S), "apify cloud", notes
        except Exception as exc:  # network, auth, quota: the local run still gives an answer
            notes.append(f"apify cloud failed ({type(exc).__name__}); ran locally")
    return await asyncio.wait_for(_run_local(inp), BUDGET_S), "local", notes


async def run(product: str, *, max_repos: int = 6) -> ScoutResult:
    """Scout open-source designs and priced parts for `product`. Never raises."""
    product = product.strip()[:120]
    res = ScoutResult(product)
    if not enabled() or not product:
        return res
    inp = {"query": product, "maxRepos": max_repos}
    path = CACHE / f"run_{_key(inp)}.json"
    started = time.monotonic()
    cached = _read_cache(path)
    try:
        if cached is not None:
            items, mode, notes = cached["items"], "cached", ["cached result"]
        else:
            items, mode, notes = await execute(inp)
            if items:
                _write_cache(path, {"items": items})
    except Exception as exc:
        res.mode, res.notes = "failed", [f"scout failed: {type(exc).__name__}"]
        return res
    res.designs, res.parts, res.pages_fetched = split_items(items)
    res.mode, res.notes = mode, notes
    res.ms = int((time.monotonic() - started) * 1000)
    for p in res.parts:
        _write_cache(CACHE / f"part_{p['lcsc_id']}.json", {"part": p})
    return res


def merge_designs(scouted: list[dict[str, Any]], others: list[dict[str, Any]]) -> list[dict]:
    """Scouted designs first, then the rest, one row per repo."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for d in [*scouted, *others]:
        repo = str(d.get("repo", "")).lower().rstrip("/")
        if repo and repo not in seen:
            seen.add(repo)
            out.append(d)
    return out


async def quote(ids: list[str]) -> dict[str, dict[str, Any]]:
    """Price and stock for LCSC ids: cached ones as they are, the rest through the Actor."""
    got = cached_quotes(ids)
    missing = [i for i in dict.fromkeys(ids) if i.upper() not in got and LCSC.fullmatch(i.upper())]
    if missing and enabled():
        try:
            items, _, _ = await execute({"lcscIds": missing[:60], "maxRepos": 1})
        except Exception as exc:
            log.warning("apify part quote failed: %s", type(exc).__name__)
            items = []
        for p in split_items(items)[1]:
            _write_cache(CACHE / f"part_{p['lcsc_id']}.json", {"part": p})
            got[p["lcsc_id"]] = p
    return got


def cached_quotes(ids: list[str]) -> dict[str, dict[str, Any]]:
    """Part quotes already fetched (no network): {LCSC id: part item}."""
    if not enabled():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for cid in ids:
        data = (
            _read_cache(CACHE / f"part_{cid.upper()}.json") if LCSC.fullmatch(cid.upper()) else None
        )
        if data and data.get("part"):
            out[cid.upper()] = data["part"]
    return out


def record(build_id: str, res: ScoutResult, bom_parts_quoted: int = 0) -> None:
    """Append one build's honest numbers to stats.jsonl."""
    row = {"build_id": build_id, "ts": int(time.time()), **res.numbers(),
           "bom_parts_quoted": bom_parts_quoted, "ms": res.ms}  # fmt: skip
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        with STATS.open("a") as fh:
            fh.write(json.dumps(row) + "\n")
    except OSError:
        log.warning("apify stats not written")


def totals() -> dict[str, Any]:
    """Sums over every recorded build, for citing."""
    out = {"builds": 0, "designs_found": 0, "parts_priced": 0, "pages_crawled": 0,
           "bom_parts_quoted": 0}  # fmt: skip
    try:
        lines = STATS.read_text().splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        out["builds"] += 1
        for k in ("designs_found", "parts_priced", "pages_crawled", "bom_parts_quoted"):
            out[k] += int(row.get(k) or 0)
    return out
