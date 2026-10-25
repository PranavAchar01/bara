"""KiCad + Freerouting tool runs: build .kicad_pcb, DSN/SES routing, DRC, GLB export."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from shapely.geometry import Polygon
from shapely.ops import unary_union

from bara.geometry.glbopt import compress

from .layout import EDGE_BAND, BoardPlan, Item
from .libs import KICAD_PYTHON, LIBRARIES, SOURCES, resolve_model

KICAD_CLI = (
    os.environ.get("BARA_KICAD_CLI") or shutil.which("kicad-cli") or "/opt/homebrew/bin/kicad-cli"
)
FREEROUTING_JAR = Path(
    os.environ.get("BARA_FREEROUTING_JAR", SOURCES / "tools/freerouting-2.5.0.jar")
)
FREEROUTING_VERSION = "2.5.0"
JAVA = os.environ.get("BARA_JAVA") or (
    "/opt/homebrew/opt/openjdk/bin/java"
    if Path("/opt/homebrew/opt/openjdk/bin/java").exists()
    else "java"
)
SCRIPT = Path(__file__).with_name("kicad_script.py")
NICE = ["nice", "-n", "19"]
# macOS background QoS (taskpolicy -b) slows Freerouting about 5x (measured 17 s vs 3 s per
# pass) and the GLB export as much (96 s vs 19 s on a keyboard board), so nothing on the
# build's critical path uses it; tool runs stay at nice 19.

RULES = {
    "clearance_mm": 0.15,
    "track_mm": 0.2,
    "via_mm": 0.5,
    "via_drill_mm": 0.3,
    # Freerouting's fanout narrows a trace to 0.15 mm where it squeezes past a hotswap pad
    # even with automatic neckdown off; 0.15 mm is still above common 2-layer fab minimums.
    "min_track_mm": 0.15,
    "edge_clearance_mm": 0.3,
}
# Freerouting's score oscillates on some dense boards and it stops with 1-3 connections
# open; a different cost setting changes its search order. Tried in order until DRC shows
# no unconnected items (measured 2026-10-23: via_costs=100 closed all three MX failures).
ROUTE_STRATEGIES: list[tuple[str, list[str]]] = [
    ("default", []),
    ("via_costs_100", ["--router.scoring.via_costs=100"]),
    ("ripup_50", ["--router.scoring.start_ripup_costs=50"]),
    ("ripup_200", ["--router.scoring.start_ripup_costs=200"]),
]
# DRC errors that come from copper being too close, not from the parts: one more pass with
# wider rules (clearance, track, edge) before the board is reported with them.
WIDENABLE = ("clearance", "copper_edge_clearance", "solder_mask_bridge", "annular_width")
WIDE_RULES = {
    **RULES,
    "clearance_mm": 0.2,
    "track_mm": 0.25,
    "min_track_mm": 0.2,
    "via_mm": 0.6,
    "via_drill_mm": 0.35,
    "edge_clearance_mm": 0.45,
}
# Board items are shifted by this much in KiCad. Large enough that the build-space origin,
# passed to `export glb --user-origin`, is always positive (kicad-cli rejects negatives).
KICAD_OFFSET = (400.0, 400.0)


class ToolError(RuntimeError):
    pass


def _run(cmd: list[str], timeout: float, cwd: Path | None = None) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd, check=False
    )
    return proc


def kicad_version() -> str:
    out = _run([KICAD_CLI, "version"], 30)
    return out.stdout.strip()


# ---------------------------------------------------------------- plan -> KiCad JSON


def _models_for(it: Item) -> list[dict]:
    if it.fp is None:
        return []
    out: list[dict] = []
    if it.model_override:
        lib, fname = it.model_override["file"].split("/", 1)
        for root in LIBRARIES[lib]["models"]:
            cand = Path(root) / fname
            if cand.exists():
                out.append(
                    {
                        "path": str(cand),
                        "offset": it.model_override.get("offset", [0, 0, 0]),
                        "rotate": it.model_override.get("rotate", [0, 0, 0]),
                    }
                )
        return out
    xforms = it.fp.extra.get("model_xforms", {})
    for ref in list(it.fp.models) + list(it.extra_models):
        path = resolve_model(ref, it.fp.lib)
        if path is not None:
            # keep the footprint author's model offset/rotation/scale (KiCad applies them)
            out.append({"path": str(path), **xforms.get(ref, {})})
    if not out:
        out = _sibling_model(it.fp.lib, it.fp.name)
    return out


def _sibling_model(lib: str, name: str) -> list[dict]:
    """A stock footprint the library ships without a 3D model is drawn with the model of
    its closest sibling of the same body size, so the routed board shows the part."""
    from bara.kicad_generated import KicadIndex

    index = KicadIndex.open()
    lender = index.model_footprint(f"{lib}:{name}") if index is not None else None
    if lender is None:
        return []
    models = index.kicad(lender)["models"]
    return [{"path": m["path"]} for m in models if Path(m["path"]).exists()]


def _poly_coords(poly: Polygon, ox: float, oy: float) -> list[list[float]]:
    pts = list(poly.exterior.coords)[:-1]
    return [[round(x + ox, 4), round(y + oy, 4)] for x, y in pts]


def plan_json(plan: BoardPlan, board_path: Path, dsn_path: Path) -> dict:
    ox, oy = KICAD_OFFSET
    nets: set[str] = set()
    fps = []
    for it in plan.items:
        if not it.on_pcb or it.fp is None:
            continue
        nets.update(v for v in it.pads.values() if v)
        fps.append(
            {
                "lib_dir": str(it.fp.lib_dir),
                "name": it.fp.name,
                "lib_id": it.fp.lib_id,
                "ref": it.ref,
                "value": it.label or it.fp.name,
                "x": round(it.x + ox, 4),
                "y": round(it.y + oy, 4),
                "rot": round(it.rot, 4),
                "side": it.side,
                "edge_cuts": it.fp.cutout is not None,
                "pads": it.pads,
                "models": _models_for(it),
            }
        )
    board_poly = plan.outline
    for cx, cy, r in plan.hole_circles:
        from shapely.geometry import Point

        board_poly = board_poly.difference(Point(cx, cy).buffer(r, 128))
    for it in plan.items:
        cut = it.cutout_poly() if it.on_pcb else None
        if cut is not None:
            board_poly = board_poly.difference(cut)
    band = board_poly.difference(board_poly.buffer(-EDGE_BAND, join_style="mitre"))
    band_polys = list(band.geoms) if hasattr(band, "geoms") else [band]
    rule_areas = []
    for i, bp in enumerate(band_polys):
        if bp.is_empty or bp.area < 0.01:
            continue
        rule_areas.append(
            {
                "name": f"edge_band_{i}",
                "outer": _poly_coords(bp, ox, oy),
                "holes": [
                    [[round(x + ox, 4), round(y + oy, 4)] for x, y in list(h.coords)[:-1]]
                    for h in bp.interiors
                ],
                "layers": ["F.Cu", "B.Cu"],
            }
        )
    return {
        "board_path": str(board_path),
        "dsn_path": str(dsn_path),
        "rules": RULES,
        "nets": sorted(nets),
        "outline": _poly_coords(plan.outline, ox, oy),
        "holes": [{"circle": [cx + ox, cy + oy, r]} for cx, cy, r in plan.hole_circles],
        "rule_areas": rule_areas,
        "footprints": fps,
    }


def board_region(plan: BoardPlan) -> Polygon:
    return unary_union([plan.outline])


# ---------------------------------------------------------------- steps


def build_pcb(plan_path: Path, timeout: float = 120) -> None:
    cmd = [str(KICAD_PYTHON), str(SCRIPT), "build", str(plan_path)]
    proc = _run(cmd, timeout, cwd=plan_path.parent)
    if proc.returncode != 0 and "create wxApp" in proc.stderr:
        # pcbnew's wx traits assert fires now and then under parallel builds; a rerun clears it
        proc = _run(cmd, timeout, cwd=plan_path.parent)
    if proc.returncode != 0:
        raise ToolError(f"kicad build failed: {proc.stderr[-2000:]}")


def freeroute(
    dsn: Path,
    ses: Path,
    timeout_s: float,
    passes: int = 100,
    optimizer: bool = False,
    extra: list[str] | None = None,
) -> dict:
    """Run Freerouting headless. Returns {seconds, returncode, log_tail}."""
    cmd = NICE + [
        JAVA,
        "-Djava.awt.headless=true",
        "-jar",
        str(FREEROUTING_JAR),
        "-de",
        str(dsn),
        "-do",
        str(ses),
        f"--router.autorouter.max_passes={passes}",
        "--gui.enabled=false",
        "--router.automatic_neckdown=false",
        f"--router.optimizer.enabled={'true' if optimizer else 'false'}",
        *(extra or []),
    ]
    t0 = time.monotonic()
    try:
        proc = _run(cmd, timeout_s, cwd=dsn.parent)
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"freerouting timed out after {timeout_s:.0f} s") from exc
    secs = time.monotonic() - t0
    text = proc.stdout + proc.stderr
    (dsn.parent / "freerouting.log").write_text(text)
    if not ses.exists():
        raise ToolError(f"freerouting wrote no session: {text[-1500:]}")
    best = re.search(r"Auto-routing stage completed.*?\((\d+) unrouted", text)
    passes_run = len(re.findall(r"Auto-routing pass #\d+", text))
    return {
        "seconds": round(secs, 2),
        "returncode": proc.returncode,
        "unrouted": int(best.group(1)) if best else None,
        "passes": passes_run,
    }


def import_ses(board: Path, ses: Path, timeout: float = 120) -> None:
    proc = _run(
        [str(KICAD_PYTHON), str(SCRIPT), "import", str(board), str(ses)], timeout, cwd=board.parent
    )
    if proc.returncode != 0:
        raise ToolError(f"SES import failed: {proc.stderr[-2000:]}")


def run_drc(board: Path, timeout: float = 180) -> dict:
    report = board.with_suffix(".drc.json")
    proc = _run(
        [
            KICAD_CLI,
            "pcb",
            "drc",
            "--format",
            "json",
            "--severity-all",
            "--units",
            "mm",
            "-o",
            str(report),
            str(board),
        ],
        timeout,
        cwd=board.parent,
    )
    if not report.exists():
        raise ToolError(f"kicad-cli drc failed: {proc.stderr[-1500:]}")
    data = json.loads(report.read_text())
    viol = data.get("violations", [])
    errors = [v for v in viol if v.get("severity") == "error"]
    warnings = [v for v in viol if v.get("severity") == "warning"]
    unconnected = data.get("unconnected_items", [])
    open_nets = sorted(
        {
            m.group(1)
            for u in unconnected
            for it in u.get("items", [])
            if (m := re.search(r"\[([^\]]+)\]", it.get("description", "")))
        }
    )
    by_type: dict[str, int] = {}
    titles: dict[str, str] = {}
    for v in viol:
        key = f"{v.get('severity')}:{v.get('type')}"
        by_type[key] = by_type.get(key, 0) + 1
        titles.setdefault(key, str(v.get("description") or v.get("type")))
    return {
        "errors": len(errors),
        "warnings": len(warnings),
        "unconnected": len(unconnected),
        "unconnected_nets": open_nets,
        "by_type": by_type,
        "titles": titles,
        "report": str(report),
    }


def export_glb(
    board: Path, out: Path, origin_kicad: tuple[float, float], timeout: float = 300
) -> None:
    if min(origin_kicad) < 0:
        raise ToolError(f"GLB origin {origin_kicad} is negative; raise KICAD_OFFSET")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".raw.glb")
    cmd = NICE + [
        KICAD_CLI,
        "pcb",
        "export",
        "glb",
        "-f",
        "-o",
        str(tmp),
        "--subst-models",
        "--include-tracks",
        "--include-pads",
        "--include-zones",
        "--include-silkscreen",
        "--include-soldermask",
        "--user-origin",
        f"{origin_kicad[0]:.4f}x{origin_kicad[1]:.4f}mm",
        str(board),
    ]
    # kicad-cli writes a scratch "$tempfile$.bin.tmp" into its cwd; a per-board cwd keeps
    # concurrent builds from clobbering each other's file.
    proc = _run(cmd, timeout, cwd=board.parent)
    if not tmp.exists():
        raise ToolError(f"glb export failed: {(proc.stdout + proc.stderr)[-1500:]}")
    # Named footprint nodes stay separate so the viewer can pick and highlight them.
    work = out.parent / f".work-{out.stem}"  # per board: concurrent builds never share it
    compress(tmp, out, work, keep_named=True, simplify=False)
    tmp.unlink(missing_ok=True)
    shutil.rmtree(work, ignore_errors=True)


SEGMENT = re.compile(
    r"\(segment\s+\(start ([-\d.]+) ([-\d.]+)\)\s+\(end ([-\d.]+) ([-\d.]+)\)"
    r"\s+\(width [-\d.]+\)\s+\(layer \"([^\"]+)\"\)"
)


def count_routing(board: Path) -> dict:
    text = board.read_text()
    length: dict[str, float] = {}
    for x0, y0, x1, y1, layer in SEGMENT.findall(text):
        d = ((float(x1) - float(x0)) ** 2 + (float(y1) - float(y0)) ** 2) ** 0.5
        length[layer] = length.get(layer, 0.0) + d
    return {
        "segments": len(re.findall(r"^\s*\(segment\b", text, re.M)),
        "vias": len(re.findall(r"^\s*\(via\b", text, re.M)),
        "track_mm": {k: round(v, 1) for k, v in sorted(length.items())},
    }
