"""Builds that stand on one board as one combined device: a macropad and the desktop display it
drives, a keyboard and its mouse. Each device is its own build in the library; a scene ties them
together under one plain title ("Macropad with desktop display") that the library, the tab and the
build header show, so the simulator runs them as the one device they are.

Scenes are kept in <library>/scenes.json, beside the builds. A build belongs to at most one scene:
putting builds together that already sit in scenes merges those scenes. Nothing here touches a
build's own files.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from bara.library import BUILD_ID_RE

TITLE_SYSTEM = """You name one combined device made of several separate devices that work together
on one desk (for example a macropad and the small display it drives).

Write a short plain title, three to six words, in sentence case: the main device first, then
"with" and the other device(s), e.g. "Macropad with desktop display", "Keyboard with mouse",
"Game console with controller". Plain nouns only: no brand or product names, no counts or sizes,
no marketing words, no punctuation at the end, no dashes."""

TITLE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"title": {"type": "string"}},
    "required": ["title"],
    "additionalProperties": False,
}

# words that describe a device without naming it: "small", "4-key", "USB", "for streaming"
_FILLER = re.compile(
    r"\b(?:an?|the|small|tiny|mini|little|compact|simple|cool|desk|usb(?:-c)?|"
    r"wireless|wired|bluetooth|battery-powered|portable|status|panel|"
    r"\d+[- ]?(?:key|button|inch|in)s?|\d+%|low-profile|"
    r"mechanical(?=\s+\w)|computer(?=\s+\w))\b",
    re.I,
)
_CUT = re.compile(r"\s*[,;:(]\s*|\s+(?:with|that|for|which|to|using|plus|in|on)\s+", re.I)
_BRANDS = re.compile(r"\b(?:stream\s*deck|game\s*boy|gameboy|playstation|xbox|nintendo)\b", re.I)


def device_noun(name: str) -> str:
    """The device a name is about, in a few plain words: "4-key USB macropad for streaming
    controls" reads "macropad", "small desktop status display panel" reads "desktop display"."""
    s = _BRANDS.sub("macropad", (name or "").strip())
    s = re.split(_CUT, s, maxsplit=1)[0]
    s = _FILLER.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip(" -")
    words = s.split()
    return " ".join(words[-3:]).lower() if words else (name or "device").strip().lower()


def joined_title(names: list[str]) -> str:
    """The deterministic title: the first device, "with", the rest joined by "and"."""
    nouns: list[str] = []
    for n in names:
        noun = device_noun(n)
        if noun and noun not in nouns:
            nouns.append(noun)
    if not nouns:
        return "Combined device"
    head, rest = nouns[0], nouns[1:]
    tail = ""
    if rest:
        tail = " with " + (rest[0] if len(rest) == 1 else ", ".join(rest[:-1]) + " and " + rest[-1])
    t = head + tail
    return t[0].upper() + t[1:]


def _clean_title(raw: str) -> str:
    t = re.sub(r"[‒-―]", " ", str(raw or "")).strip().strip(".!\"'")
    t = re.sub(r"\s+", " ", t)
    if not t or len(t) > 60 or len(t.split()) > 8:
        return ""
    return t[0].upper() + t[1:]


async def combined_title(names: list[str]) -> tuple[str, str]:
    """(title, by): the joined title when it reads well (five words or fewer), else the model's
    short title for the devices together, with the joined one when no model answers."""
    fallback = joined_title(names)
    if len(names) < 2 or len(fallback.split()) <= 5:
        return fallback, "rules"
    from bara.live.ask import ask_json  # the model call; imported late so tests run without it

    listing = "\n".join(f"- {n.strip()[:160]}" for n in names[:6])
    data, _note = await ask_json(
        TITLE_SYSTEM,
        f"Devices on the board, the main one first:\n{listing}",
        TITLE_SCHEMA,
        name="scene_title",
        fast=True,
        timeout_s=15.0,
        max_tokens=100,
        effort="low",
    )
    title = _clean_title((data or {}).get("title", ""))
    return (title, "model") if title else (fallback, "rules")


def scene_id(builds: list[str]) -> str:
    return "s_" + hashlib.sha1(",".join(sorted(builds)).encode()).hexdigest()[:12]


# a companion prompt names what it pairs with ("... that connects to a 4-button stream deck, sized
# to sit beside it"); the intent route writes them this way
_COMPANION = re.compile(
    r"\b(?:pairs?\s+(?:over\s+\S+\s+)?with|connects?\s+to|"
    r"(?:sized\s+)?to\s+sit\s+beside|alongside)\b",
    re.I,
)


def detect_pairs(rows: list[dict[str, Any]], window_s: float = 1800.0) -> list[list[str]]:
    """Companion builds already in the library: a build whose prompt says it pairs with another
    device, with the visible build made just before it (within `window_s`). Used to backfill."""

    def ts(r: dict[str, Any]) -> float:
        try:
            return datetime.fromisoformat(
                str(r.get("created_at")).replace("Z", "+00:00")
            ).timestamp()
        except ValueError:
            return 0.0

    shown = sorted(
        (r for r in rows if not r.get("hidden_at") and r.get("origin") != "open_source"), key=ts
    )
    out: list[list[str]] = []
    for i, r in enumerate(shown):
        if i == 0 or not _COMPANION.search(str(r.get("prompt") or "")):
            continue
        prev = shown[i - 1]
        if 0 <= ts(r) - ts(prev) <= window_s:
            out.append([prev["build_id"], r["build_id"]])
    return out


class Scenes:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()

    def _read(self) -> list[dict[str, Any]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return (
            [s for s in raw if isinstance(s, dict) and isinstance(s.get("builds"), list)]
            if isinstance(raw, list)
            else []
        )

    def _write(self, scenes: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(scenes, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def all(self) -> list[dict[str, Any]]:
        return self._read()

    def of(self, build_id: str) -> dict[str, Any] | None:
        return next((s for s in self._read() if build_id in s["builds"]), None)

    def put(
        self, builds: list[str], title: str, by: str, names: list[str] | None = None
    ) -> dict[str, Any]:
        """Stand these builds on one board (the first is the main device). Scenes that already
        hold any of them are merged into this one, their builds kept after these."""
        ids = [b for b in dict.fromkeys(builds) if BUILD_ID_RE.fullmatch(b)]
        if len(ids) < 2:
            raise ValueError("a scene needs two builds or more")
        with self._lock:
            scenes = self._read()
            keep: list[dict[str, Any]] = []
            for s in scenes:
                if set(s["builds"]) & set(ids):
                    ids += [b for b in s["builds"] if b not in ids]
                else:
                    keep.append(s)
            scene = {
                "scene_id": scene_id(ids),
                "builds": ids,
                "title": title,
                "by": by,
                "names": (names or [])[: len(ids)],
                "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            }
            self._write([*keep, scene])
        return scene

    def annotate(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Library rows with the scene each one stands in, when it stands in one."""
        by_build = {b: s for s in self._read() for b in s["builds"]}
        out = []
        for r in rows:
            s = by_build.get(str(r.get("build_id")))
            out.append(
                {
                    **r,
                    "scene": {
                        "scene_id": s["scene_id"],
                        "title": s["title"],
                        "builds": s["builds"],
                    },
                }
                if s
                else r
            )
        return out


def scene_routes(api: Any, svc: Any) -> None:
    """GET /v1/scenes lists the scenes; POST /v1/scenes {builds, names?} stands builds on one
    board and names the combined device. The library listing carries each row's scene."""
    store = Scenes(svc.engine.library.root / "scenes.json")

    def err(message: str, status: int = 400) -> JSONResponse:
        return JSONResponse({"error": {"code": "E_BAD_MESSAGE", "message": message}}, status)

    @api.get("/v1/scenes")
    def scenes_list() -> JSONResponse:
        return JSONResponse({"scenes": store.all()})

    @api.post("/v1/scenes")
    async def scenes_put(request: Request) -> JSONResponse:
        try:
            data = await request.json()
        except ValueError:
            return err("Body is not JSON.")
        builds = data.get("builds") if isinstance(data, dict) else None
        if not isinstance(builds, list) or not all(isinstance(b, str) for b in builds):
            return err("Send builds: the build ids on one board, the main device first.")
        ids = [b for b in dict.fromkeys(builds) if BUILD_ID_RE.fullmatch(b)]
        if len(ids) < 2:
            return err("A combined device needs two builds or more.")
        same = store.of(ids[0])
        if same and set(ids) <= set(same["builds"]):
            return JSONResponse({"scene": same})  # already on one board: keep the title it has
        given = data.get("names") if isinstance(data.get("names"), list) else []
        names: list[str] = []
        for i, b in enumerate(ids):
            # the library's short device name wins over the page's tab label
            row = svc.engine.library.get(b) or {}
            n = str(row.get("device") or "")
            if not n.strip():
                n = given[i] if i < len(given) and isinstance(given[i], str) else ""
            if not n.strip():
                n = str(row.get("prompt") or "device")
            names.append(n.strip()[:160])
        title, by = await combined_title(names)
        return JSONResponse({"scene": store.put(ids, title, by, names)})


async def backfill(library_root: Path) -> list[dict[str, Any]]:
    """Find the companion builds already in the library and stand each pair on one board."""
    from bara.library import Library

    lib = Library(library_root, library_root)
    rows = lib.list()
    names = {r["build_id"]: str(r.get("device") or r.get("prompt") or "") for r in rows}
    store = Scenes(library_root / "scenes.json")
    made = []
    for pair in detect_pairs(rows):
        if store.of(pair[0]) and store.of(pair[1]):
            continue
        title, by = await combined_title([names[b] for b in pair])
        made.append(store.put(pair, title, by, [names[b] for b in pair]))
    return made


if __name__ == "__main__":  # python -m bara.scenes  (backfills the configured library)
    import asyncio
    import sys

    from bara.config import load_settings

    settings = load_settings()
    root = settings.library_override or settings.data_dir / "library"
    for s in asyncio.run(backfill(root)):
        sys.stdout.write(f"{s['scene_id']} {s['title']} ({s['by']}) {s['builds']}\n")
