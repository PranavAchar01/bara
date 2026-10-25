"""KiCad's own checks and statistics on a generated board, read into the build's checks.

Three kicad-cli runs per board, each writing JSON:
  `pcb drc --schematic-parity`  design rules plus schematic parity (via kicad.run_drc, the
                                same DRC the routing loop runs)
  `sch erc`                     electrical rules on the schematic
  `pcb export stats`            KiCad's board statistics (size, copper, pads, components)

Every violation keeps KiCad's rule (its `type`), severity, message and the references of the
footprints or symbols it names. When kicad-cli is missing the report says "KiCad not installed"
and the build goes on; a tool that fails is reported, never raised.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from . import kicad as K

REPORT_VERSION = "kicad-checks-v1"
MAX_VIOLATIONS = 200  # per board: counts stay complete, the list is capped for the build state
APP_CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
SEVERITIES = ("error", "warning", "info", "exclusion")


def find_kicad_cli() -> str | None:
    """kicad-cli from BARA_KICAD_CLI, the macOS app bundle, PATH or Homebrew; None if absent."""
    for cand in (
        os.environ.get("BARA_KICAD_CLI"),
        APP_CLI,
        shutil.which("kicad-cli"),
        "/opt/homebrew/bin/kicad-cli",
    ):
        if cand and Path(cand).is_file() and os.access(cand, os.X_OK):
            return cand
    return None


# ---------------------------------------------------------------- parsing

# "PTH pad 1 [GND] of DS1", "Footprint U1", "Symbol R3 Pin 2 [Passive]", "Symbol #PWR001 ..."
_REF = re.compile(r"(?:\bof|^Footprint|^Symbol)\s+(#?[A-Za-z_]+[0-9]+[A-Za-z]?)\b")


def item_refs(items: list[dict]) -> list[str]:
    """The footprint or symbol references a violation's items name, in order, once each."""
    out: list[str] = []
    for it in items or []:
        m = _REF.search(str(it.get("description", "")))
        if m and m.group(1) not in out:
            out.append(m.group(1))
    return out


def _violation(tool: str, v: dict, severity: str | None = None, note: str | None = None) -> dict:
    items = v.get("items") or []
    out = {
        "tool": tool,
        "rule": str(v.get("type") or "unknown"),
        "severity": severity or str(v.get("severity") or "error"),
        "message": str(v.get("description") or v.get("type") or ""),
        "refs": item_refs(items),
        "items": [str(it.get("description", "")) for it in items][:4],
    }
    pos = items[0].get("pos") if items else None
    if isinstance(pos, dict) and "x" in pos and "y" in pos:
        out["pos_mm"] = [float(pos["x"]), float(pos["y"])]
    if note:
        out["note"] = note
    return out


def _counts(violations: list[dict]) -> dict[str, int]:
    out = {s: 0 for s in ("error", "warning", "info")}
    for v in violations:
        out[v["severity"]] = out.get(v["severity"], 0) + 1
    return out


def _by_rule(violations: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in violations:
        key = f"{v['severity']}:{v['rule']}"
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))


def _section(violations: list[dict]) -> dict:
    counts = _counts(violations)
    return {
        "counts": counts,
        "by_rule": _by_rule(violations),
        "passed": counts.get("error", 0) == 0,
    }


def parse_drc(data: dict) -> dict:
    """A `kicad-cli pcb drc --format json` report -> DRC and schematic-parity sections.

    The same two readings the routing loop uses apply here so both reports agree: a clearance
    short by less than the router's grid is dropped, and a clearance between two pads of one
    footprint (the vendor land pattern) is a warning."""
    drc: list[dict] = []
    for v in data.get("violations") or []:
        if K._within_router_grid(v):
            continue
        if v.get("severity") == "error" and K._inside_one_footprint(v):
            drc.append(_violation("drc", v, "warning", "pads inside one library footprint"))
        else:
            drc.append(_violation("drc", v))
    unconnected = [
        _violation("drc", {**u, "type": u.get("type") or "unconnected_items"})
        for u in data.get("unconnected_items") or []
    ]
    parity = [_violation("parity", v) for v in data.get("schematic_parity") or []]
    out = {
        "drc": {**_section(drc + unconnected), "unconnected": len(unconnected)},
        "violations": drc + unconnected + parity,
        "kicad_version": data.get("kicad_version"),
    }
    if "schematic_parity" in data:
        out["parity"] = _section(parity)
    return out


def parse_erc(data: dict) -> dict:
    """A `kicad-cli sch erc --format json` report -> the ERC section (all sheets)."""
    viol = [
        _violation("erc", v) for s in data.get("sheets") or [] for v in s.get("violations") or []
    ]
    return {"erc": _section(viol), "violations": viol, "kicad_version": data.get("kicad_version")}


_NUM = re.compile(r"-?[0-9]+(?:\.[0-9]+)?")


def _num(v: Any) -> float | None:
    if isinstance(v, int | float):
        return float(v)
    m = _NUM.search(str(v or ""))
    return float(m.group(0)) if m else None


def parse_stats(data: dict) -> dict:
    """`kicad-cli pcb export stats --format json` -> flat board numbers in mm."""
    board = data.get("board") or {}
    comps = (data.get("components") or {}).get("total") or {}
    pads = data.get("pads") or {}
    vias = data.get("vias") or {}
    area = _num(board.get("area"))
    copper = [_num(board.get("front_copper_area")), _num(board.get("back_copper_area"))]
    fill = None
    if area and all(c is not None for c in copper):
        fill = round(100.0 * sum(c for c in copper if c is not None) / (2 * area), 1)
    return {
        "width_mm": _num(board.get("width")),
        "height_mm": _num(board.get("height")),
        "area_mm2": area,
        "thickness_mm": _num(board.get("board_thickness")),
        "copper_fill_pct": fill,
        "min_track_width_mm": _num(board.get("min_track_width")),
        "min_clearance_mm": _num(board.get("min_track_clearance")),
        "min_drill_mm": _num(board.get("min_drill_diameter")),
        "components": int(comps.get("total") or 0),
        "pads": int(sum(int(v or 0) for v in pads.values() if isinstance(v, int | float))),
        "vias": int(sum(int(v or 0) for v in vias.values() if isinstance(v, int | float))),
    }


_LAYERS = re.compile(r"\(layers\b(.*?)\n\t\)", re.S)
_CU = re.compile(r"\(\d+\s+\"([^\"]+\.Cu)\"\s+(?:signal|power|mixed|jumper)")


def copper_layers(pcb_text: str) -> int:
    m = _LAYERS.search(pcb_text)
    return len(set(_CU.findall(m.group(1) if m else pcb_text))) or 2


# ---------------------------------------------------------------- running


def _digest(*paths: Path | None) -> str:
    h = hashlib.sha256(REPORT_VERSION.encode())
    for p in paths:
        if p is not None and p.exists():
            h.update(p.read_bytes())
    return h.hexdigest()[:24]


def _json_run(cmd: list[str], out: Path, timeout: float, cwd: Path) -> tuple[dict, float]:
    out.unlink(missing_ok=True)
    t = time.monotonic()
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd, check=False
    )
    secs = round(time.monotonic() - t, 2)
    if not out.exists():
        raise RuntimeError(f"{' '.join(cmd[1:3])} wrote no report: {proc.stderr[-400:]}")
    return json.loads(out.read_text()), secs


def run_checks(
    pcb: Path,
    sch: Path | None = None,
    *,
    out_dir: Path | None = None,
    cli: str | None = None,
    timeout: float = 120,
    use_cache: bool = True,
) -> dict:
    """KiCad DRC (with schematic parity when `sch` exists), ERC and board statistics.

    Reports land in `out_dir` (default: beside the board); the board and schematic are only
    read. A report for the same input bytes is reused. Never raises: a missing kicad-cli is
    status "not_installed", a tool failure is status "failed" with what is known so far."""
    t0 = time.monotonic()
    cli = cli or find_kicad_cli()
    if cli is None:
        return {"status": "not_installed", "message": "KiCad not installed"}
    sch = sch if sch is not None and sch.exists() else None
    out_dir = out_dir or pcb.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = out_dir / "kicad_checks.json"
    digest = _digest(pcb, sch)
    if use_cache and cache.exists():
        try:
            cached = json.loads(cache.read_text())
            if cached.get("digest") == digest and cached.get("status") == "ok":
                return {**cached, "cached": True}
        except ValueError:
            pass
    report: dict[str, Any] = {"status": "ok", "digest": digest, "timings": {}, "violations": []}
    try:
        # A parity check reads the schematic named like the board (main.kicad_sch beside
        # main.kicad_pcb), which is how the pipeline writes it.
        parity = sch is not None and sch.parent == pcb.parent and sch.stem == pcb.stem
        # the same DRC run the routing loop uses, now with schematic parity and kept whole
        t = time.monotonic()
        res = K.run_drc(
            pcb, timeout, schematic_parity=parity, report=out_dir / "kicad_drc.json", cli=cli
        )
        secs = round(time.monotonic() - t, 2)
        drc = parse_drc(json.loads(Path(res["report"]).read_text()))
        report.update({k: v for k, v in drc.items() if k != "violations"})
        report["violations"] += drc["violations"]
        report["timings"]["drc_s"] = secs
        if sch is not None:
            data, secs = _json_run(
                [cli, "sch", "erc", "--format", "json", "--severity-all", "--units", "mm",
                 "-o", str(out_dir / "kicad_erc.json"), str(sch)],
                out_dir / "kicad_erc.json", timeout, sch.parent,
            )  # fmt: skip
            erc = parse_erc(data)
            report["erc"] = erc["erc"]
            report["violations"] += erc["violations"]
            report["timings"]["erc_s"] = secs
        data, secs = _json_run(
            [cli, "pcb", "export", "stats", "--format", "json", "--units", "mm",
             "-o", str(out_dir / "kicad_stats.json"), str(pcb)],
            out_dir / "kicad_stats.json", timeout, pcb.parent,
        )  # fmt: skip
        stats = parse_stats(data)
        text = pcb.read_text()
        routing = K.count_routing(pcb)
        track = routing.get("track_mm") or {}
        stats.update(
            {
                "copper_layers": copper_layers(text),
                "track_mm": track,
                "track_total_mm": round(sum(track.values()), 1),
                "segments": routing.get("segments"),
                "unrouted": int(report.get("drc", {}).get("unconnected", 0)),
            }
        )
        report["stats"] = stats
        report["timings"]["stats_s"] = secs
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        report["status"] = "failed"
        report["message"] = f"KiCad check failed: {exc}"[:400]
    report["total_violations"] = len(report["violations"])
    report["violations"] = sorted(
        report["violations"], key=lambda v: SEVERITIES.index(v["severity"])
        if v["severity"] in SEVERITIES else len(SEVERITIES),
    )[:MAX_VIOLATIONS]  # fmt: skip
    report["timings"]["total_s"] = round(time.monotonic() - t0, 2)
    report["cli"] = cli
    if report["status"] == "ok":
        tmp = cache.with_suffix(".tmp")
        tmp.write_text(json.dumps(report, indent=1))
        tmp.replace(cache)
    return report


def attach_instances(
    report: dict,
    footprints: list[dict],
    slots: dict[str, str] | None = None,
    role_slot: dict[str, str] | None = None,
) -> dict:
    """Each violation gains the build instance ids of the refs it names. A board footprint
    maps ref -> instance id; one the board left unmapped falls back to the build part in the
    slot its role names (role_slot, else a slot named after the role). Parts with no build
    row, such as decoupling caps, map to nothing."""
    slots, role_slot = slots or {}, role_slot or {}
    by_ref = {
        fp["ref"]: fp.get("instance_id")
        or slots.get(role_slot.get(fp.get("role") or "", fp.get("role") or ""))
        for fp in footprints
        if fp.get("ref")
    }
    out = dict(report)
    out["violations"] = [
        {**v, "instance_ids": sorted({by_ref[r] for r in v["refs"] if by_ref.get(r)})}
        for v in report.get("violations") or []
    ]
    return out


_LABEL = {"drc": "KiCad DRC", "erc": "KiCad ERC", "parity": "KiCad schematic parity"}


def check_results(bid: str, report: dict) -> list[dict]:
    """The report as build checks: one per tool, failing on any error, with its counts."""
    subjects: list[dict] = [{"board_id": bid}]
    status = report.get("status")
    if status != "ok":
        return [
            {
                "check_key": f"board.kicad:{bid}",
                "rule_id": "board.kicad",
                "status": "unknown",
                "severity": "info",
                "message": str(report.get("message") or "KiCad checks did not run"),
                "subjects": subjects,
                "measured": None,
                "limit": None,
                "unit": None,
                "stage": "board",
            }
        ]
    out = []
    for tool in ("drc", "erc", "parity"):
        sec = report.get(tool)
        if not sec:
            continue
        c = sec["counts"]
        errs = [v for v in report["violations"] if v["tool"] == tool and v["severity"] == "error"]
        insts = sorted({i for v in errs for i in v.get("instance_ids", [])})
        # errors first, then the most frequent rules
        ranked = sorted(sec["by_rule"].items(), key=lambda kv: (kv[0][:6] != "error:", -kv[1]))
        top = ", ".join(f"{k.partition(':')[2].replace('_', ' ')} x{n}" for k, n in ranked[:3])
        out.append(
            {
                "check_key": f"board.kicad.{tool}:{bid}",
                "rule_id": f"board.kicad.{tool}",
                "status": "pass" if sec["passed"] else "fail",
                "severity": "error" if c.get("error") else "warning",
                "message": (
                    f"{_LABEL[tool]}: {c.get('error', 0)} errors, {c.get('warning', 0)} warnings"
                    + (f" ({top})" if top else "")
                ),
                "subjects": subjects + [{"instance_id": i} for i in insts],
                "measured": c.get("error", 0),
                "limit": 0,
                "unit": "count",
                "stage": "board",
            }
        )
    return out
