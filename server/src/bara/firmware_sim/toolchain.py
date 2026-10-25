"""Compile the generated firmware for real: a cross build for the board's chip with zig cc
(clang + lld, installed as the `ziglang` Python package), and a host build of the same code
for the test harness. Every result carries the exact command and the compiler's log."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from . import elf as elfmod
from .codegen import FwConfig, write_project
from .mcu import Board

COMPILE_TIMEOUT_S = 180
LOW_PRIORITY = ["nice", "-n", "19"] + (["taskpolicy", "-b"] if shutil.which("taskpolicy") else [])


def zig_cc() -> list[str]:
    return [sys.executable, "-m", "ziglang", "cc"]


def zig_version() -> str:
    try:
        r = subprocess.run(
            [sys.executable, "-m", "ziglang", "version"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return r.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "missing"


def _run(cmd: list[str], cwd: Path) -> tuple[int, str, float]:
    t0 = time.monotonic()
    try:
        r = subprocess.run(
            LOW_PRIORITY + cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=COMPILE_TIMEOUT_S,
        )
        return r.returncode, (r.stdout + r.stderr).strip(), time.monotonic() - t0
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {COMPILE_TIMEOUT_S} s", time.monotonic() - t0
    except OSError as e:
        return 127, str(e), time.monotonic() - t0


def _shown(cmd: list[str]) -> str:
    return " ".join("zig" if c == sys.executable else c for c in cmd).replace(
        "zig -m ziglang", "zig"
    )


def build_target(board: Board, src: Path) -> dict[str, Any]:
    if not board.zig_target:
        return {
            "status": "unavailable",
            "message": f"No cross compiler for {board.label} on this server; "
            "the host simulation build runs the same code instead.",
            "log": "",
        }
    hal = {"nrf52840": "hal_nrf52840.c", "rp2040": "hal_rp2040.c"}[board.family]
    cmd = zig_cc() + [
        "-target",
        board.zig_target,
        f"-mcpu={board.zig_cpu}",
        "-Os",
        "-g",
        "-std=c11",
        "-ffreestanding",
        "-fno-builtin",
        "-nostdlib",
        "-fno-stack-protector",
        "-ffunction-sections",
        "-fdata-sections",
        "-Wall",
        "-Wextra",
        "-Wno-unused-parameter",
        "-Wl,--gc-sections",
        "-Wl,-T,link.ld",
        "-Wl,-e,Reset_Handler",
        "-o",
        "firmware.elf",
        "bara_app.c",
        hal,
        "bara_libc.c",
    ]
    code, log, secs = _run(cmd, src)
    out: dict[str, Any] = {
        "status": "ok" if code == 0 else "failed",
        "compiler": f"zig cc {zig_version()} (clang/lld), "
        f"target {board.zig_target} {board.zig_cpu}",
        "command": _shown(cmd),
        "log": log or "(no warnings)",
        "seconds": round(secs, 2),
        "exit_code": code,
    }
    if code != 0:
        out["message"] = "The compiler stopped with errors; the log shows the first one."
        return out
    data = (src / "firmware.elf").read_bytes()
    e = elfmod.parse(data)
    base, image = e.image()
    secs_ = e.sections
    out["size"] = {
        "text": secs_.get(".text", (0, 0))[1],
        "data": secs_.get(".data", (0, 0))[1],
        "bss": secs_.get(".bss", (0, 0))[1],
        "image": len(image),
    }
    out["load_address"] = f"0x{base:08X}"
    out["entry"] = f"0x{e.entry:08X}"
    (src.parent / "firmware.bin").write_bytes(image)
    if board.uf2_family:
        (src.parent / "firmware.uf2").write_bytes(elfmod.uf2(base, image, board.uf2_family))
    shutil.copyfile(src / "firmware.elf", src.parent / "firmware.elf")
    out["sha256"] = hashlib.sha256(image).hexdigest()[:16]
    return out


def build_host(src: Path) -> dict[str, Any]:
    host_cc = [shutil.which("cc")] if shutil.which("cc") else zig_cc()
    cmd = [str(c) for c in host_cc] + [
        "-O1",
        "-std=c11",
        "-DBARA_NO_MAIN",
        "-Wall",
        "-Wno-unused-function",
        "-o",
        "firmware_host",
        "bara_app.c",
        "hal_host.c",
    ]
    code, log, secs = _run(cmd, src)
    out = {
        "status": "ok" if code == 0 else "failed",
        "compiler": "host cc" if host_cc[0] != sys.executable else "zig cc (host)",
        "command": _shown(cmd),
        "log": log or "(no warnings)",
        "seconds": round(secs, 2),
        "exit_code": code,
    }
    if code == 0:
        shutil.copyfile(src / "firmware_host", src.parent / "firmware_host")
        (src.parent / "firmware_host").chmod(0o755)
    return out


def build(io: dict[str, Any], cfg: FwConfig, out_dir: Path) -> dict[str, Any]:
    """Generate, then compile for the chip and for the host. Never says 'not built' vaguely:
    each half is ok, failed (with the log) or unavailable (with the reason)."""
    if out_dir.exists():
        shutil.rmtree(out_dir)
    proj = write_project(io, cfg, out_dir)
    board: Board = proj["board"]
    src: Path = proj["src"]
    target = build_target(board, src)
    host = build_host(src)
    ok_target = target["status"] in ("ok", "unavailable")
    status = "ok" if ok_target and host["status"] == "ok" else "failed"
    if target["status"] == "unavailable" and host["status"] == "ok":
        mode = "host"
    elif target["status"] == "ok":
        mode = "emulated"
    else:
        mode = "none"
    result = {
        "status": status,
        "mode": mode,  # emulated: the chip build runs in the emulator; host: host build only
        "board": {
            "id": board.board_id,
            "label": board.label,
            "family": board.family,
            "emulator": board.emulator,
        },
        "target": target,
        "host": host,
        "config": cfg.to_dict(),
        "files": [f for f in proj["files"] if f.endswith((".c", ".h", ".ld"))],
        "built_at": time.time(),
        "notes": list(board.notes)
        + (
            ["The RP2040 image is a RAM image (no boot2 flash stage); not tested on hardware."]
            if board.family == "rp2040"
            else []
        ),
    }
    (out_dir / "build.json").write_text(json.dumps(result, indent=2))
    return result
