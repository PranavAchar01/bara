"""One simulator per build: the I/O plan, the compiled firmware, the running session, the test
results and the chat with the build agent."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .codegen import FwConfig
from .emulator import ChipSession, HostSession, make_chip
from .io import plan_io
from .tests import catalog, run_test
from .toolchain import build as compile_firmware


@dataclass
class SimBuild:
    build_id: str
    state: dict[str, Any]
    out_dir: Path
    assets_url: str
    boards_root: Path | None = None
    io: dict[str, Any] = field(default_factory=dict)
    cfg: FwConfig = field(default_factory=FwConfig)
    fw: dict[str, Any] = field(default_factory=dict)
    session: HostSession | ChipSession | None = None
    results: dict[str, dict[str, Any]] = field(default_factory=dict)
    chat: list[dict[str, Any]] = field(default_factory=list)
    labels: dict[str, Any] | None = None
    label_notes: list[str] = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock)
    touched: float = field(default_factory=time.time)
    # the combined device this build stands in, from the page: {title, testing, devices, flows}
    scene: dict[str, Any] | None = None

    # ---- lifecycle ----
    def plan(self, client: dict[str, str] | None = None, codes: dict[str, str] | None = None):
        from .agent import apply_labels

        self.io = plan_io(self.state, client, codes)
        if self.labels:
            apply_labels(self.io, self.labels)
        return self.io

    def compile(self) -> dict[str, Any]:
        with self.lock:
            self.close()
            self.fw = compile_firmware(self.io, self.cfg, self.out_dir)
            self.results = {}
            self.start()
            return self.fw

    def start(self) -> None:
        with self.lock:
            self.close()
            if self.fw.get("mode") == "emulated":
                self.session = make_chip(self.io, self.cfg, self.out_dir / "firmware.elf")
            elif self.fw.get("host", {}).get("status") == "ok":
                self.session = HostSession(self.io, self.cfg, self.out_dir / "firmware_host")
            else:
                self.session = None
            if self.session:
                self.session.run_ms(30)

    def close(self) -> None:
        if isinstance(self.session, HostSession):
            self.session.close()
        self.session = None

    # ---- views ----
    def downloads(self) -> dict[str, str]:
        out = {}
        for name in ("firmware.uf2", "firmware.elf", "firmware.bin"):
            if (self.out_dir / name).is_file():
                out[name] = f"{self.assets_url}/{name}"
        return out

    def view(self) -> dict[str, Any]:
        snap = self.session.snapshot() if self.session else None
        return {
            "build_id": self.build_id,
            "prompt": self.state.get("prompt"),
            "io": self.io,
            "firmware": {**self.fw, "downloads": self.downloads()},
            "config": self.cfg.to_dict(),
            "tests": [
                {**t, **(self.results.get(t["id"]) or {"status": "not_run"})}
                for t in catalog(self.io, self.fw)
            ]
            if self.fw
            else [],
            "chat": self.chat[-40:],
            "labels_note": "; ".join(self.label_notes),
            "snapshot": snap,
            "scene": self.scene,
        }

    def run_tests(self, ids: list[str] | None = None) -> list[dict[str, Any]]:
        with self.lock:
            items = catalog(self.io, self.fw)
            wanted = [t["id"] for t in items if ids is None or t["id"] in ids]
            out = []
            for tid in wanted:
                try:
                    r = run_test(
                        tid, self.io, self.cfg, self.fw, self.out_dir, self.state, self.boards_root
                    )
                except Exception as e:  # a crashing test is a failed test, with the reason
                    r = {"id": tid, "status": "fail", "summary": f"test crashed: {e}", "log": ""}
                self.results[tid] = r
                out.append(r)
            return out

    def source(self, name: str) -> str | None:
        path = (self.out_dir / "src" / name).resolve()
        if path.parent != (self.out_dir / "src").resolve() or not path.is_file():
            return None
        if path.suffix not in (".c", ".h", ".ld"):
            return None
        return path.read_text(errors="replace")


class SimStore:
    def __init__(self, assets_dir: Path, limit: int = 12, boards_root: Path | None = None) -> None:
        self.boards_root = boards_root
        self.root = assets_dir / "cache" / "firmware_sim"  # gitignored, served at /assets
        self.items: dict[str, SimBuild] = {}
        self.limit = limit
        self.lock = threading.Lock()

    def get(self, build_id: str) -> SimBuild | None:
        sb = self.items.get(build_id)
        if sb:
            sb.touched = time.time()
        return sb

    def create(self, build_id: str, state: dict[str, Any]) -> SimBuild:
        with self.lock:
            old = self.items.pop(build_id, None)
            if old:
                old.close()
            while len(self.items) >= self.limit:
                oldest = min(self.items.values(), key=lambda s: s.touched)
                oldest.close()
                self.items.pop(oldest.build_id, None)
            sb = SimBuild(
                build_id=build_id,
                state=state,
                out_dir=self.root / build_id,
                assets_url=f"/assets/cache/firmware_sim/{build_id}",
                boards_root=self.boards_root,
            )
            self.items[build_id] = sb
            return sb
