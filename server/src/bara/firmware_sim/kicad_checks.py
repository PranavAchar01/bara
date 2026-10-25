"""KiCad's own evaluation of the build's board, run with kicad-cli: ERC on the schematic, DRC on
the PCB, and the board statistics report. Each result carries counts by severity, every
violation, and the numbers KiCad reports. A build with no board yet says so instead of passing."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from bara.board import kicad as K

KICAD_IDS = ("kicad.erc", "kicad.drc", "kicad.stats")
KICAD_NAMES = {
    "kicad.erc": "Schematic electrical rules (KiCad ERC)",
    "kicad.drc": "Board design rules (KiCad DRC)",
    "kicad.stats": "Board statistics (tracks, vias, layers, routing)",
}
TIMEOUT_S = 120
SEVERITIES = ("error", "warning", "info", "exclusion")


def kicad_cli() -> str | None:
    cli = K.KICAD_CLI
    return cli if shutil.which(cli) or Path(cli).is_file() else None


def board_dirs(state: dict[str, Any], boards_root: Path | None) -> list[tuple[str, Path]]:
    """(board name, folder holding main.kicad_pcb) for every routed board of the build."""
    out: list[tuple[str, Path]] = []
    if boards_root is None:
        return out
    for n, b in enumerate(state.get("boards") or []):
        key = str((b.get("routing") or {}).get("cache_key") or "")
        if not re.fullmatch(r"[0-9a-f]{8,64}", key):
            continue
        folder = boards_root / key
        if (folder / "main.kicad_pcb").is_file():
            out.append((str(b.get("board_id") or f"board {n + 1}"), folder))
    return out


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["nice", "-n", "19", *cmd], capture_output=True, text=True, timeout=TIMEOUT_S, check=False
    )


def _violation_lines(violations: list[dict[str, Any]], prefix: str = "") -> list[str]:
    out = []
    for v in violations:
        items = "; ".join(
            f"{i.get('description', '')} @ ({i['pos']['x']:.2f}, {i['pos']['y']:.2f}) mm"
            if i.get("pos")
            else str(i.get("description", ""))
            for i in v.get("items") or []
        )
        out.append(
            f"{prefix}[{v.get('severity', '?')}] {v.get('description', v.get('type', ''))}"
            f" ({v.get('type', '')})" + (f": {items}" if items else "")
        )
    return out


def _counts(violations: list[dict[str, Any]]) -> dict[str, int]:
    return {s: sum(1 for v in violations if v.get("severity") == s) for s in SEVERITIES}


def _no_board() -> dict[str, Any]:
    return {"status": "unavailable", "summary": "not run: no board yet", "log": ""}


def _no_cli() -> dict[str, Any]:
    return {
        "status": "unavailable",
        "summary": "not run: kicad-cli is not installed on this server",
        "log": "",
    }


def schematic_files(state: dict[str, Any], boards_root: Path | None) -> list[tuple[str, Path]]:
    """(board name, schematic file) for every board whose schematic was drawn."""
    out: list[tuple[str, Path]] = []
    for n, b in enumerate(state.get("boards") or []):
        name = str(b.get("board_id") or f"board {n + 1}")
        sch = Path(str((b.get("schematic") or {}).get("kicad_sch") or ""))
        if not sch.is_file() and boards_root is not None:
            key = str((b.get("routing") or {}).get("cache_key") or "")
            if re.fullmatch(r"[0-9a-f]{8,64}", key):
                sch = boards_root / key / "main.kicad_sch"
        if sch.is_file():
            out.append((name, sch))
    return out


def run_erc(boards: list[tuple[str, Path]]) -> dict[str, Any]:
    if not boards:
        return _no_board()
    cli = kicad_cli()
    if not cli:
        return _no_cli()
    violations: list[dict[str, Any]] = []
    log: list[str] = []
    checked = 0
    for name, sch in boards:
        with tempfile.TemporaryDirectory() as tmp:
            rep = Path(tmp) / "erc.json"
            proc = _run(
                [cli, "sch", "erc", "--format", "json", "--severity-all", "-o", str(rep), str(sch)]
            )
            if not rep.is_file():
                log.append(f"{name}: ERC did not run: {(proc.stderr or proc.stdout)[-300:]}")
                continue
            data = json.loads(rep.read_text())
        checked += 1
        found = [v for s in data.get("sheets") or [] for v in s.get("violations") or []]
        violations += found
        log += _violation_lines(found, f"{name}: " if len(boards) > 1 else "")
    if not checked:
        return {
            "status": "unavailable",
            "summary": "not run: no schematic yet",
            "log": "\n".join(log),
        }
    c = _counts(violations)
    status = "fail" if c["error"] else "warn" if c["warning"] else "pass"
    return {
        "status": status,
        "summary": f"ERC: {c['error']} errors, {c['warning']} warnings"
        f" ({len(violations)} violations in {checked} schematic{'s' if checked > 1 else ''})",
        "numbers": {"errors": c["error"], "warnings": c["warning"], "violations": len(violations)},
        "violations": violations[:300],
        "log": "\n".join(log) or "no violations",
    }


def run_drc(boards: list[tuple[str, Path]]) -> dict[str, Any]:
    if not boards:
        return _no_board()
    cli = kicad_cli()
    if not cli:
        return _no_cli()
    violations: list[dict[str, Any]] = []
    unconnected: list[dict[str, Any]] = []
    log: list[str] = []
    for name, folder in boards:
        with tempfile.TemporaryDirectory() as tmp:
            rep = Path(tmp) / "drc.json"
            proc = _run(
                [cli, "pcb", "drc", "--format", "json", "--severity-all", "--all-track-errors",
                 "--units", "mm", "-o", str(rep), str(folder / "main.kicad_pcb")]
            )  # fmt: skip
            if not rep.is_file():
                log.append(f"{name}: DRC did not run: {(proc.stderr or proc.stdout)[-300:]}")
                continue
            data = json.loads(rep.read_text())
        pre = f"{name}: " if len(boards) > 1 else ""
        violations += data.get("violations") or []
        unconnected += data.get("unconnected_items") or []
        log += _violation_lines(data.get("violations") or [], pre)
        log += _violation_lines(
            [{**u, "severity": "error"} for u in data.get("unconnected_items") or []], pre
        )
    if not log and not violations:
        log = ["no violations"]
    c = _counts(violations)
    errors = c["error"] + len(unconnected)
    status = "fail" if errors else "warn" if c["warning"] else "pass"
    return {
        "status": status,
        "summary": f"DRC: {c['error']} errors, {c['warning']} warnings,"
        f" {len(unconnected)} unconnected",
        "numbers": {
            "errors": c["error"],
            "warnings": c["warning"],
            "unconnected": len(unconnected),
            "violations": len(violations),
        },
        "violations": (violations + unconnected)[:300],
        "log": "\n".join(log),
    }


def _mm(text: Any) -> float | None:
    m = re.match(r"\s*(-?\d+(?:\.\d+)?)", str(text))
    return float(m.group(1)) if m else None


def run_stats(boards: list[tuple[str, Path]], state: dict[str, Any]) -> dict[str, Any]:
    if not boards:
        return _no_board()
    cli = kicad_cli()
    if not cli:
        return _no_cli()
    by_id = {str(b.get("board_id")): b for b in state.get("boards") or []}
    nums: dict[str, float | int | str] = {}
    log: list[str] = []
    track_total = vias = 0.0
    unrouted = nets = 0
    layers = 0
    for name, folder in boards:
        pcb = folder / "main.kicad_pcb"
        rt = K.count_routing(pcb)
        length = sum(rt["track_mm"].values())
        track_total += length
        vias += rt["vias"]
        spec = by_id.get(name) or {}
        layers = max(layers, int(spec.get("layers") or len(rt["track_mm"]) or 0))
        routing = spec.get("routing") or {}
        unrouted += len(routing.get("unrouted_nets") or [])
        nets += len(spec.get("nets") or [])
        stats: dict[str, Any] = {}
        with tempfile.TemporaryDirectory() as tmp:
            rep = Path(tmp) / "stats.json"
            _run(
                [
                    cli,
                    "pcb",
                    "export",
                    "stats",
                    "--format",
                    "json",
                    "--units",
                    "mm",
                    "-o",
                    str(rep),
                    str(pcb),
                ]
            )
            if rep.is_file():
                stats = json.loads(rep.read_text())
        b = stats.get("board") or {}
        pre = f"{name} " if len(boards) > 1 else ""
        log.append(
            f"{pre}track length per layer (mm): "
            + ", ".join(f"{k} {v}" for k, v in rt["track_mm"].items())
        )
        for key, label in (
            ("area", "board area"),
            ("min_track_width", "narrowest track"),
            ("min_track_clearance", "smallest clearance"),
            ("min_drill_diameter", "smallest drill"),
            ("front_component_density", "front component density"),
        ):
            if b.get(key) is not None:
                log.append(f"{pre}{label}: {b[key]}")
        pads, comps = stats.get("pads") or {}, (stats.get("components") or {}).get("total") or {}
        if pads:
            log.append(
                f"{pre}pads: {pads.get('smd', 0)} SMD, {pads.get('through_hole', 0)} through-hole"
            )
        if comps.get("total") is not None:
            nums["components"] = int(nums.get("components", 0)) + int(comps["total"])
        area = _mm(b.get("area"))
        if area:
            nums["board_area_mm2"] = round(float(nums.get("board_area_mm2", 0)) + area, 1)
        mt = _mm(b.get("min_track_width"))
        if mt is not None:
            nums["min_track_width_mm"] = mt
    routed_pct = round(100.0 * (nets - unrouted) / nets, 1) if nets else None
    if routed_pct is None:
        ev = [(by_id.get(n) or {}).get("evaluation") or {} for n, _ in boards]
        pcts = [e["routed_pct"] for e in ev if "routed_pct" in e]
        routed_pct = round(sum(pcts) / len(pcts), 1) if pcts else None
    nums.update(
        {
            "track_length_mm": round(track_total, 1),
            "vias": int(vias),
            "copper_layers": layers,
            "nets": nets,
            "unrouted_nets": unrouted,
        }
    )
    if routed_pct is not None:
        nums["routed_pct"] = routed_pct
    ok = routed_pct is None or routed_pct >= 100.0
    return {
        "status": "pass" if ok else "warn",
        "summary": f"{round(track_total, 1)} mm of track, {int(vias)} vias, {layers} layers"
        + (f", {routed_pct}% routed" if routed_pct is not None else ""),
        "numbers": nums,
        "log": "\n".join(log),
    }


def run(tid: str, state: dict[str, Any], boards_root: Path | None) -> dict[str, Any]:
    boards = board_dirs(state, boards_root)
    if tid == "kicad.erc":
        sheets = schematic_files(state, boards_root)
        if not sheets and boards:
            return {"status": "unavailable", "summary": "not run: no schematic yet", "log": ""}
        return run_erc(sheets)
    if tid == "kicad.drc":
        return run_drc(boards)
    return run_stats(boards, state)
