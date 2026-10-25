"""Persistent build library: every live build's outgoing event stream, kept on the engine.

A build is two small files under <data_dir>/library: <id>.jsonl (one event per line, the same
messages a socket receives) and <id>.meta.json (the index row, written when the build ends).
Deleting a build removes those two files only; shared caches (boards, enclosures, hero
renders) stay because other builds may reuse them.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

BUILD_ID_RE = re.compile(r"^b_[A-Za-z0-9]{1,32}$")
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

    def _shot_url(self, build_id: str) -> str | None:
        """The product shot scripts/render-shots.mjs writes: the finished device alone, transparent around it."""
        path = self.assets_dir / "cache" / "shots" / f"{build_id}.webp"
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

    def list(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in self.root.glob("b_*.meta.json") if self.root.is_dir() else []:
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(row, dict) and BUILD_ID_RE.fullmatch(str(row.get("build_id", ""))):
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

    def delete(self, build_id: str) -> bool:
        events, meta = self._paths(build_id)
        with self._lock:
            found = meta.is_file() or events.is_file()
            meta.unlink(missing_ok=True)
            events.unlink(missing_ok=True)
        return found
