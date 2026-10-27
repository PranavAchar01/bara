"""Run KiCad's own checks and exports on one board folder (main.kicad_pcb + main.kicad_sch)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

TIMEOUT_S = 180

# Violation types that only say a symbol or footprint library is not installed where the check
# ran (CI images ship without the parts' own libraries). They are reported, never gated on.
ENVIRONMENT_TYPES = frozenset(
    {"lib_symbol_issues", "lib_symbol_mismatch", "footprint_link_issues",
     "lib_footprint_issues", "lib_footprint_mismatch"}
)  # fmt: skip


def cli() -> str:
    found = os.environ.get("KICAD_CLI") or shutil.which("kicad-cli")
    if not found:
        raise RuntimeError("kicad-cli not found: install KiCad 10 or set KICAD_CLI")
    return found


def version() -> str:
    out = subprocess.run([cli(), "version"], capture_output=True, text=True, timeout=30)
    return out.stdout.strip()


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [cli(), *args], capture_output=True, text=True, timeout=TIMEOUT_S, check=False
    )


def _report(args: list[str], name: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        rep = Path(tmp) / name
        proc = _run([*args[:-1], "-o", str(rep), args[-1]])
        if not rep.is_file():
            raise RuntimeError(f"kicad-cli {' '.join(args[:2])} failed: {proc.stderr[-400:]}")
        return json.loads(rep.read_text())


def _item(v: dict[str, Any]) -> dict[str, Any]:
    items = v.get("items") or []
    pos = next((i["pos"] for i in items if i.get("pos")), None)
    return {
        "severity": v.get("severity", "error"),
        "type": v.get("type", ""),
        "description": v.get("description", ""),
        "items": [str(i.get("description", "")) for i in items],
        "at_mm": [round(pos["x"], 2), round(pos["y"], 2)] if pos else None,
        "environment": v.get("type") in ENVIRONMENT_TYPES,
    }


def _tally(found: list[dict[str, Any]]) -> dict[str, int]:
    design = [v for v in found if not v["environment"]]
    c = Counter(v["severity"] for v in design)
    return {
        "errors": c.get("error", 0),
        "warnings": c.get("warning", 0),
        "environment": len(found) - len(design),
    }


def drc(board: Path) -> dict[str, Any]:
    data = _report(
        ["pcb", "drc", "--format", "json", "--severity-all", "--units", "mm",
         str(board / "main.kicad_pcb")],
        "drc.json",
    )  # fmt: skip
    found = [_item(v) for v in data.get("violations") or []]
    unconnected = [{**_item(v), "severity": "error"} for v in data.get("unconnected_items") or []]
    out = {"violations": found + unconnected, **_tally(found + unconnected)}
    out["unconnected"] = len(unconnected)
    return out


def erc(board: Path) -> dict[str, Any]:
    data = _report(
        ["sch", "erc", "--format", "json", "--severity-all", str(board / "main.kicad_sch")],
        "erc.json",
    )
    found = [_item(v) for s in data.get("sheets") or [] for v in s.get("violations") or []]
    return {"violations": found, **_tally(found)}


def stats(board: Path) -> dict[str, Any]:
    data = _report(
        ["pcb", "export", "stats", "--format", "json", "--units", "mm",
         str(board / "main.kicad_pcb")],
        "stats.json",
    )  # fmt: skip
    b = data.get("board") or {}
    comps = (data.get("components") or {}).get("total") or {}
    pads = data.get("pads") or {}
    return {
        "area": b.get("area"),
        "width": b.get("width"),
        "height": b.get("height"),
        "min_track_width": b.get("min_track_width"),
        "min_drill_diameter": b.get("min_drill_diameter"),
        "components": comps.get("total"),
        "pads_smd": pads.get("smd"),
        "pads_tht": pads.get("through_hole"),
    }


def fab(board: Path, out_zip: Path) -> list[str]:
    """Gerbers, drill files, pick-and-place and a BOM for one board, zipped for the fab house."""
    pcb, sch = str(board / "main.kicad_pcb"), str(board / "main.kicad_sch")
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        steps = [
            ["pcb", "export", "gerbers", "-o", f"{t}/", pcb],
            ["pcb", "export", "drill", "-o", f"{t}/", pcb],
            ["pcb", "export", "pos", "--format", "csv", "--units", "mm", "-o", f"{t}/pos.csv", pcb],
            ["sch", "export", "bom", "-o", f"{t}/bom.csv", sch],
        ]
        for args in steps:
            proc = _run(args)
            if proc.returncode != 0:
                raise RuntimeError(f"kicad-cli {' '.join(args[:3])} failed: {proc.stderr[-400:]}")
        files = sorted(p for p in t.iterdir() if p.is_file())
        out_zip.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
            for p in files:
                z.write(p, p.name)
        return [p.name for p in files]
