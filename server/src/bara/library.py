"""Persistent build library: every live build's outgoing event stream, kept on the engine.

A build is two small files under <data_dir>/library: <id>.jsonl (one event per line, the same
messages a socket receives) and <id>.meta.json (the index row, written when the build ends).
Deleting a build only hides it: the index row gets a `hidden_at` stamp, the listing leaves it out,
and every file stays, so `restore` brings it back exactly as it was. Nothing here removes data.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BUILD_ID_RE = re.compile(r"^b_[A-Za-z0-9]{1,32}$")
# A product shot is a 1600 x 1200 WebP, around 200 KB; anything far past that is not one.
MAX_SHOT_BYTES = 4 * 1024 * 1024
TERMINAL_STATUS = {"build.done": "done", "build.failed": "failed"}


class Library:
    def __init__(self, root: Path, assets_dir: Path):
        self.root = root
        self.assets_dir = assets_dir
        self._lock = threading.Lock()

    def _paths(self, build_id: str) -> tuple[Path, Path]:
        if not BUILD_ID_RE.fullmatch(build_id):
            raise ValueError("invalid build id")
        return self.root / f"{build_id}.jsonl", self.root / f"{build_id}.meta.json"

    def _hero_url(self, build_id: str) -> str | None:
        for suffix in ("_repaired", ""):
            if (self.assets_dir / "cache" / "hero" / f"{build_id}{suffix}.png").is_file():
                return f"/assets/cache/hero/{build_id}{suffix}.png"
        return None

    def _shot_path(self, build_id: str) -> Path:
        return self.assets_dir / "cache" / "shots" / f"{build_id}.webp"

    def save_shot(self, build_id: str, webp: bytes) -> str:
        """Keep a product shot for a stored build (the browser that built it renders one when it finishes)."""
        if not BUILD_ID_RE.fullmatch(build_id):
            raise ValueError("invalid build id")
        if len(webp) > MAX_SHOT_BYTES or webp[:4] != b"RIFF" or webp[8:12] != b"WEBP":
            raise ValueError("not a WebP image")
        path = self._shot_path(build_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(webp)
        tmp.replace(path)
        return self._shot_url(build_id) or ""

    def _shot_url(self, build_id: str) -> str | None:
        """The product shot scripts/render-shots.mjs writes: the finished device alone, transparent around it."""
        path = self._shot_path(build_id)
        try:
            return f"/assets/cache/shots/{build_id}.webp?v={int(path.stat().st_mtime)}"
        except OSError:
            return None

    def record(self, run: Any, msg: dict[str, Any]) -> None:
        """Append one outgoing event; on build.done or build.failed write the index row."""
        events, meta = self._paths(run.build_id)
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            with events.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(msg, separators=(",", ":")) + "\n")
            status = TERMINAL_STATUS.get(msg.get("type", ""))
            if status:
                row = {
                    "build_id": run.build_id,
                    "prompt": run.prompt,
                    "device": getattr(run, "device", "") or None,
                    "created_at": run.state.get("created_at") or msg.get("ts"),
                    "status": status,
                    "hero_url": self._hero_url(run.build_id),
                }
                tmp = meta.with_suffix(".tmp")
                tmp.write_text(json.dumps(row), encoding="utf-8")
                tmp.replace(meta)

    def list(self, hidden: bool = False) -> list[dict[str, Any]]:
        """The shown builds, newest first; with hidden=True the hidden ones instead."""
        rows: list[dict[str, Any]] = []
        for path in self.root.glob("b_*.meta.json") if self.root.is_dir() else []:
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(row, dict) or bool(row.get("hidden_at")) != hidden:
                continue
            if BUILD_ID_RE.fullmatch(str(row.get("build_id", ""))):
                # shots are rendered after the fact, so look for one each time rather than in the stored row
                rows.append({**row, "shot_url": self._shot_url(row["build_id"])})
        rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
        return rows

    def get(self, build_id: str) -> dict[str, Any] | None:
        events, meta = self._paths(build_id)
        if not meta.is_file() or not events.is_file():
            return None
        try:
            row = json.loads(meta.read_text(encoding="utf-8"))
            lines = events.read_text(encoding="utf-8").splitlines()
            return {**row, "events": [json.loads(ln) for ln in lines if ln.strip()]}
        except (OSError, ValueError):
            return None

    def _set_hidden(self, build_id: str, when: str | None) -> bool:
        _, meta = self._paths(build_id)
        with self._lock:
            try:
                row = json.loads(meta.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return False
            if not isinstance(row, dict):
                return False
            if when:
                row["hidden_at"] = row.get("hidden_at") or when
            else:
                row.pop("hidden_at", None)
            tmp = meta.with_suffix(".tmp")
            tmp.write_text(json.dumps(row), encoding="utf-8")
            tmp.replace(meta)
        return True

    def delete(self, build_id: str) -> bool:
        """Hide a build from the listing. Its events, row and shot all stay; restore undoes it."""
        return self._set_hidden(build_id, datetime.now(UTC).isoformat(timespec="seconds"))

    def restore(self, build_id: str) -> bool:
        """Show a hidden build again."""
        return self._set_hidden(build_id, None)
