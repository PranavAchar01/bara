"""Catalog build: check sources, export meshes, write the mesh manifest.

    cd server
    uv run --with trimesh --with numpy python -m catalog_build.build check
    uv run --with trimesh --with numpy python -m catalog_build.build meshes [--only ID ...]
    uv run --with trimesh --with numpy python -m catalog_build.build parts

Heavy (kicad-cli exports): run under ~/helloworld/.heavy-lock.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bara.geometry.glbopt import compress

from .kicad_lib import Footprint, Model, read_footprint
from .manifest import ENTRIES, Entry, ModelSpec
from .meshes import (
    KICAD_CLI,
    _run,
    export_glb,
    glb_bounds,
    glb_node_names,
    translate_glb,
)
from .resolve import (
    Resolved,
    footprint_lib_id,
    resolve_footprint,
    resolve_model,
    resolve_symbol,
)
from .sources import SOURCES

SERVER = Path(__file__).resolve().parent.parent
ASSETS = SERVER / "data/assets/parts"
CATALOG = SERVER / "data/catalog"
MESH_MANIFEST = CATALOG / "meshes.json"
WORK = Path("/tmp/bara-catalog-work")
ALIGN_TOL_MM = 0.05


def say(*parts: object, sep: str = " ") -> None:
    sys.stdout.write(sep.join(str(x) for x in parts) + "\n")
    sys.stdout.flush()


def glb_stem(part_id: str) -> str:
    """File stem from the id suffix; prefixed with the id prefix when two suffixes clash."""
    suffix = part_id.split(":", 1)[1]
    clash = sum(1 for e in ENTRIES if e.part_id.split(":", 1)[1] == suffix) > 1
    stem = f"{part_id.split(':', 1)[0]}_{suffix}" if clash else suffix
    return re.sub(r"[^A-Za-z0-9._-]+", "_", stem)


@dataclass
class Plan:
    entry: Entry
    footprint: Resolved | None = None
    fp: Footprint | None = None
    models: list[tuple[Resolved, Model | None, ModelSpec | None]] = field(default_factory=list)
    missing_models: list[str] = field(default_factory=list)
    board: Resolved | None = None
    problems: list[str] = field(default_factory=list)


def plan_entry(e: Entry) -> Plan:
    p = Plan(e)
    if e.whole_board:
        key, _, rel = e.whole_board.partition(":")
        src = SOURCES[key]
        path = src.root / rel
        if path.is_file():
            p.board = Resolved(path, src, rel)
        else:
            p.problems.append(f"board missing: {path}")
        return p
    if e.footprint:
        try:
            p.footprint = resolve_footprint(e.footprint)
            p.fp = read_footprint(p.footprint.path)
        except FileNotFoundError as exc:
            p.problems.append(str(exc))
    if e.symbol:
        try:
            res, name = resolve_symbol(e.symbol)
            from .kicad_lib import read_symbol

            read_symbol(res.path, name)
        except (FileNotFoundError, KeyError) as exc:
            p.problems.append(f"symbol: {exc}")
    if e.mesh_from:
        return p
    if e.models:
        for spec in e.models:
            src = SOURCES[spec.source]
            path = src.root / spec.path
            if path.is_file():
                p.models.append((Resolved(path, src, spec.path), None, spec))
            else:
                p.problems.append(f"model missing: {path}")
        return p
    if p.fp is not None:
        for m in p.fp.models:
            if m.hidden:
                continue
            if e.model_filter and not any(k in m.path for k in e.model_filter):
                continue
            res = resolve_model(m.path, p.fp.path)
            if res is None:
                p.missing_models.append(m.path)
            else:
                p.models.append((res, m, None))
    return p


def cmd_check() -> int:
    bad = 0
    ids = [e.part_id for e in ENTRIES]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        say("duplicate ids:", sorted(dupes))
        bad += 1
    meshless = []
    for e in ENTRIES:
        p = plan_entry(e)
        if p.problems:
            bad += 1
            say(f"PROBLEM {e.part_id}: {'; '.join(p.problems)}")
        elif not (p.models or p.board or e.mesh_from):
            meshless.append(f"{e.part_id} (missing: {', '.join(p.missing_models) or 'none'})")
    say(f"{len(ENTRIES)} entries, {bad} with problems")
    say("no mesh source:", *meshless, sep="\n  ")
    return 1 if bad else 0


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _export(
    stem: str, fp: Footprint | None, models: list[tuple[Path, Model | None]], out: Path
) -> dict[str, Any]:
    return export_glb(WORK / stem, stem, fp, models, out)


def _outline(fp: Footprint | None) -> dict[str, list[float]] | None:
    """Courtyard, else the pad extents (SPEC frame), used to seat model-only parts."""
    if fp is None:
        return None
    if fp.courtyard:
        return fp.courtyard
    pads = [pd.as_record() for pd in fp.pads if pd.size]
    if not pads:
        return None
    xs = [pd["xy_mm"][0] + s * pd["size_mm"][0] / 2 for pd in pads for s in (-1, 1)]
    ys = [pd["xy_mm"][1] + s * pd["size_mm"][1] / 2 for pd in pads for s in (-1, 1)]
    return {"min": [min(xs), min(ys)], "max": [max(xs), max(ys)]}


def _aligned_models(
    stem: str, fp: Footprint | None, items: list[tuple[Resolved, Model | None, ModelSpec | None]]
) -> tuple[list[tuple[Path, Model | None]], list[str]]:
    """Seat model-only parts: computed offsets so the bbox sits on the courtyard centre, z>=0."""
    out: list[tuple[Path, Model | None]] = []
    notes: list[str] = []
    for i, (res, m, spec) in enumerate(items):
        if spec is None or spec.align is None:
            out.append((res.path, m))
            continue
        rot = spec.rotate
        tc = (0.0, 0.0)
        outline = _outline(fp)
        if outline:
            c = outline
            tc = ((c["min"][0] + c["max"][0]) / 2, (c["min"][1] + c["max"][1]) / 2)
        base = Model(path=str(res.path), rotate=rot)
        probe = WORK / stem / f"align{i}.glb"
        r = export_glb(WORK / stem, f"align{i}", None, [(res.path, base)], probe)
        b = glb_bounds(probe.with_suffix(".raw.glb")) if r["ok"] else None
        if b is None:
            notes.append(f"align failed for {res.path.name}")
            out.append((res.path, base))
            continue
        # Auto 90 deg about Z when the footprint is taller than wide and the model is not.
        if outline:
            fw = outline["max"][0] - outline["min"][0]
            fh = outline["max"][1] - outline["min"][1]
            mw, mh = b["max"][0] - b["min"][0], b["max"][1] - b["min"][1]
            if (fw - fh) * (mw - mh) < 0 and abs(mw - mh) > 1.0:
                rot = (rot[0], rot[1], rot[2] + 90.0)
                base = Model(path=str(res.path), rotate=rot)
                r = export_glb(WORK / stem, f"align{i}", None, [(res.path, base)], probe)
                b = glb_bounds(probe.with_suffix(".raw.glb"))
                assert b is not None
                notes.append("rotated 90 deg about Z to match the footprint outline")
        dx = tc[0] - (b["min"][0] + b["max"][0]) / 2
        dy = tc[1] - (b["min"][1] + b["max"][1]) / 2
        dz = spec.z_base - b["min"][2]
        for sign in (1.0, -1.0):
            mm = Model(path=str(res.path), rotate=rot, offset=(dx, sign * dy, dz))
            r = export_glb(WORK / stem, f"align{i}", None, [(res.path, mm)], probe)
            b2 = glb_bounds(probe.with_suffix(".raw.glb"))
            assert b2 is not None
            cy = (b2["min"][1] + b2["max"][1]) / 2
            cx = (b2["min"][0] + b2["max"][0]) / 2
            if abs(cy - tc[1]) < ALIGN_TOL_MM and abs(cx - tc[0]) < ALIGN_TOL_MM:
                break
        notes.append(
            f"aligned by bbox: rotate {list(rot)} deg, offset "
            f"{[round(v, 3) for v in mm.offset]} mm (computed from model bounds)"
        )
        out.append((res.path, mm))
    return out, notes


BOARD_FLAGS = [
    "--board-only",
    "--include-pads",
    "--include-tracks",
    "--include-silkscreen",
    "--include-soldermask",
]


def _board_glb(board: Path, dst: Path) -> bool:
    r = _run(
        [KICAD_CLI, "pcb", "export", "glb", "--force", *BOARD_FLAGS, "-o", str(dst), str(board)],
        timeout=900,
    )
    return r.returncode == 0 and dst.exists()


CROP_HEADS = {
    "footprint",
    "segment",
    "arc",
    "via",
    "zone",
    "gr_line",
    "gr_arc",
    "gr_circle",
    "gr_rect",
    "gr_poly",
    "gr_curve",
    "gr_text",
    "gr_text_box",
    "dimension",
    "image",
    "group",
    "target",
}
_XY_HEADS = {"at", "start", "end", "center", "mid", "xy"}


def _xs(node: list[Any]) -> list[float]:
    out: list[float] = []
    for item in node[1:]:
        if isinstance(item, list) and item:
            if item[0] in _XY_HEADS and len(item) >= 3:
                try:
                    out.append(float(item[1]))
                except ValueError:
                    pass
            elif item[0] not in ("footprint", "pad", "model", "property"):
                out.extend(_xs(item))
    return out


def _crop_board(board: Path, dst: Path, half: str, mid_x: float) -> None:
    """Board file with only the items lying wholly on one side of mid_x."""
    from .sexpr import dump, parse

    root = parse(board.read_text(encoding="utf-8", errors="replace"))
    kept: list[Any] = [root[0]]
    for item in root[1:]:
        if isinstance(item, list) and item and item[0] in CROP_HEADS:
            xs = [
                float(item_at[1])
                for item_at in item[1:]
                if isinstance(item_at, list) and item_at and item_at[0] == "at"
            ]
            xs = xs or _xs(item)
            # Keep an item only when it lies wholly on the chosen side; drawings that
            # span both halves (titles, fab lines) are dropped.
            if xs and (max(xs) > mid_x if half == "left" else min(xs) < mid_x):
                continue
        kept.append(item)
    dst.write_text(dump(kept) + "\n")


def _edge_mid_x(board: Path) -> float:
    from .sexpr import parse

    root = parse(board.read_text(encoding="utf-8", errors="replace"))
    xs: list[float] = []
    for item in root[1:]:
        if isinstance(item, list) and item and str(item[0]).startswith("gr_"):
            layer = next((x for x in item[1:] if isinstance(x, list) and x[:1] == ["layer"]), None)
            if layer is not None and str(layer[1]) == "Edge.Cuts":
                xs.extend(_xs(item))
    return (min(xs) + max(xs)) / 2


def _export_board(stem: str, board: Path, out: Path, half: str | None) -> dict[str, Any]:
    """Whole upstream board, board-only (components are separate parts), centred in XY."""
    work = WORK / stem
    work.mkdir(parents=True, exist_ok=True)
    note = "whole board (kicad-cli, board only), re-centred on its bounds"
    if half:
        cropped = work / f"{stem}.kicad_pcb"
        _crop_board(board, cropped, half, _edge_mid_x(board))
        board = cropped
        note = (
            f"{half} half of the upstream two-up board file: KiCad items past the Edge.Cuts "
            "midline removed, then re-centred on its bounds"
        )
    raw = work / f"{stem}.page.glb"
    if not _board_glb(board, raw):
        return {"ok": False, "log": "board export failed"}
    b = glb_bounds(raw)
    assert b is not None
    dx = -(b["min"][0] + b["max"][0]) / 2
    dy = -(b["min"][1] + b["max"][1]) / 2
    centred = work / f"{stem}.raw.glb"
    translate_glb(raw, centred, (dx / 1000.0, 0.0, -dy / 1000.0))
    size = centred.stat().st_size
    plain = compress(centred, out, work, keep_named=False, simplify=False)
    return {
        "ok": True,
        "raw_bytes": size,
        "bytes": out.stat().st_size,
        "plain": plain,
        "note": note,
    }


def _licence_union(lics: list[dict[str, Any]]) -> dict[str, Any]:
    uniq: list[dict[str, Any]] = []
    for lic in lics:
        if lic not in uniq:
            uniq.append(lic)
    if len(uniq) == 1:
        return uniq[0]
    order = {"no": 0, "unknown": 1, "yes": 2}
    worst = min((u["commercial_ok"] for u in uniq), key=lambda v: order[v])
    return {
        "spdx": " AND ".join(dict.fromkeys(u["spdx"] for u in uniq)),
        "name": "; ".join(dict.fromkeys(u["name"] for u in uniq)),
        "url": uniq[0]["url"],
        "commercial_ok": worst,
        "copyleft": "yes"
        if any(u["copyleft"] == "yes" for u in uniq)
        else ("unknown" if any(u["copyleft"] == "unknown" for u in uniq) else "no"),
        "attribution_required": "yes"
        if any(u["attribution_required"] == "yes" for u in uniq)
        else ("unknown" if any(u["attribution_required"] == "unknown" for u in uniq) else "no"),
        "notes": "Combined: footprint and 3D model come from different sources.",
        "parts": uniq,
    }


def mesh_record(
    p: Plan, result: dict[str, Any] | None, out: Path | None, notes: list[str]
) -> dict[str, Any]:
    e = p.entry
    rec: dict[str, Any] = {"part_id": e.part_id, "display_name": e.name, "kind": e.kind}
    files: list[dict[str, Any]] = []
    lics: list[dict[str, Any]] = []
    if p.footprint:
        rec["footprint"] = {
            "lib_id": footprint_lib_id(e.footprint or "", p.footprint),
            "file": str(p.footprint.path),
            "source_url": p.footprint.url,
            "source": p.footprint.source.key,
            "commit": p.footprint.source.commit,
        }
        lics.append(p.footprint.licence.as_record())
    if p.board:
        files.append(
            {
                "role": "board",
                "file": str(p.board.path),
                "source_url": p.board.url,
                "source": p.board.source.key,
                "commit": p.board.source.commit,
                "licence": p.board.licence.as_record(),
            }
        )
        lics.append(p.board.licence.as_record())
    for res, m, spec in p.models:
        item: dict[str, Any] = {
            "role": "model",
            "file": str(res.path),
            "source_url": res.url,
            "source": res.source.key,
            "commit": res.source.commit,
            "licence": res.licence.as_record(),
        }
        if m is not None:
            item["kicad_model"] = m.as_record()
        if spec is not None:
            item["placement"] = "aligned_by_bbox" if spec.align else "as_is"
        files.append(item)
        lics.append(res.licence.as_record())
    rec["sources"] = files
    if p.missing_models:
        rec["unresolved_models"] = p.missing_models
    if result and result.get("ok") and out is not None:
        rec.update(
            {
                "status": "ok",
                "glb": str(out.relative_to(SERVER.parent)),
                "url": f"/assets/parts/{out.name}",
                "bytes": out.stat().st_size,
                "raw_bytes": result.get("raw_bytes"),
                "sha256": sha256(out),
                # Bounds and names from the uncompressed file: trimesh cannot read meshopt.
                "bbox_mm": glb_bounds(result.get("plain") or out),
                "nodes": glb_node_names(result.get("plain") or out),
            }
        )
        if result.get("note"):
            notes = [*notes, result["note"]]
    else:
        rec.update({"status": "missing", "glb": None, "url": None, "bbox_mm": None})
        if result and not result.get("ok"):
            notes = [*notes, f"export failed: {result.get('log', '')[-300:]}"]
    if e.mesh_note:
        notes = [*notes, e.mesh_note]
    if e.bbox_note and rec["status"] == "missing":
        notes = [*notes, e.bbox_note]
    rec["notes"] = notes
    rec["licence"] = _licence_union(lics) if lics else None
    return rec


def build_one(p: Plan) -> dict[str, Any]:
    e = p.entry
    stem = glb_stem(e.part_id)
    out = ASSETS / f"{stem}.glb"
    if p.problems:
        return mesh_record(p, {"ok": False, "log": "; ".join(p.problems)}, None, [])
    if p.board:
        return mesh_record(p, _export_board(stem, p.board.path, out, e.board_half), out, [])
    if not p.models:
        return mesh_record(p, None, None, [])
    models, notes = _aligned_models(stem, p.fp, p.models)
    return mesh_record(p, _export(stem, p.fp, models, out), out, notes)


def cmd_meshes(only: list[str]) -> int:
    ASSETS.mkdir(parents=True, exist_ok=True)
    CATALOG.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    old: dict[str, dict[str, Any]] = {}
    if MESH_MANIFEST.exists():
        old = {r["part_id"]: r for r in json.loads(MESH_MANIFEST.read_text())["parts"]}
    recs: dict[str, dict[str, Any]] = {}
    for e in ENTRIES:
        if e.mesh_from:
            continue
        if only and e.part_id not in only:
            if e.part_id in old:
                recs[e.part_id] = old[e.part_id]
            continue
        rec = build_one(plan_entry(e))
        recs[e.part_id] = rec
        say(
            f"{rec['status']:8} {e.part_id:36} {rec.get('bytes') or 0:>9}  {rec.get('bbox_mm')}",
        )
    for e in ENTRIES:
        if not e.mesh_from:
            continue
        if e.mesh_from not in recs:
            continue
        base = recs[e.mesh_from]
        p = plan_entry(e)
        rec = mesh_record(p, None, None, [])
        rec.update(
            {k: base[k] for k in ("glb", "url", "bytes", "sha256", "bbox_mm", "nodes") if k in base}
        )
        rec["sources"] = base["sources"]
        rec["status"] = "proxy" if base["status"] == "ok" else "missing"
        rec["mesh_proxy_of"] = e.mesh_from
        rec["licence"] = base["licence"]
        recs[e.part_id] = rec
    parts = [recs[e.part_id] for e in ENTRIES if e.part_id in recs]
    doc = {
        "about": (
            "Bara part meshes. Every GLB is converted with kicad-cli from an upstream KiCad "
            "footprint 3D model or an open-source STEP file; see SOURCES.md. glTF is metres, "
            "Y up; bbox_mm is in the SPEC 3.2 part frame (mm, Z up, z=0 at the PCB top for "
            "components, board bottom for whole boards)."
        ),
        "kicad_cli": KICAD_CLI,
        "count": len(parts),
        "with_mesh": sum(1 for r in parts if r["status"] in ("ok", "proxy")),
        "total_glb_bytes": sum(r.get("bytes") or 0 for r in parts if r["status"] == "ok"),
        "parts": parts,
    }
    MESH_MANIFEST.write_text(json.dumps(doc, indent=1) + "\n")
    say(
        f"wrote {MESH_MANIFEST}: {doc['with_mesh']}/{doc['count']} with mesh, "
        f"{doc['total_glb_bytes']} bytes"
    )
    return 0


SPEC_DIR = SERVER.parent / "spec"


def _designs(schemas: Any, part_ids: set[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """The fixture Corne design plus the hand-authored overlay designs, each validated."""
    found: list[dict[str, Any]] = []
    fx = json.loads((SPEC_DIR / "fixtures/rest/design.json").read_text())
    found.append(fx["response"]["body"]["design"])
    overlay = CATALOG / "designs_overlay.json"
    if overlay.is_file():
        found += json.loads(overlay.read_text()).get("designs", [])
    keep: list[dict[str, Any]] = []
    notes: list[str] = []
    for d in found:
        errs = schemas.errors("design.schema.json", d)
        missing = sorted({p["part_id"] for p in d.get("parts", [])} - part_ids)
        if errs:
            notes.append(f"design {d.get('design_id')}: dropped, {errs[0]}")
            continue
        if missing:
            notes.append(f"design {d['design_id']}: parts not in catalog {missing}")
        keep.append(d)
    return keep, notes


def cmd_parts() -> int:
    """Mesh manifest + manifest entries -> catalog.jsonl, kicad.jsonl, catalog.sqlite."""
    from collections import Counter

    from bara.catalog_db import write_catalog
    from bara.schemas import SchemaSet

    from .parts import build_part

    meshes = {r["part_id"]: r for r in json.loads(MESH_MANIFEST.read_text())["parts"]}
    schemas = SchemaSet(SPEC_DIR / "schemas")
    built: list[tuple[dict[str, Any], dict[str, Any]]] = []
    bad = 0
    for e in ENTRIES:
        part, kicad = build_part(e, meshes.get(e.part_id))
        errs = schemas.errors("part.schema.json", part, strict=True)
        if errs:
            bad += 1
            say(f"INVALID {e.part_id}: {errs[:3]}")
        built.append((part, kicad))
    if bad:
        say(f"{bad} invalid parts; catalog not written")
        return 1
    designs, notes = _designs(schemas, {p["part_id"] for p, _ in built})
    for n in notes:
        say(n)
    built.sort(key=lambda pk: pk[0]["part_id"])
    with (CATALOG / "catalog.jsonl").open("w") as fh:
        for part, _ in built:
            fh.write(json.dumps(part, sort_keys=True) + "\n")
    with (CATALOG / "kicad.jsonl").open("w") as fh:
        for _, kicad in built:
            fh.write(json.dumps(kicad, sort_keys=True) + "\n")
    fn = Counter(
        next(f["function_id"] for f in p["functions"] if f.get("primary")) for p, _ in built
    )
    meta = {
        "spec_version": json.loads((SPEC_DIR / "schemas/part.schema.json").read_text())[
            "x-spec-version"
        ],
        "part_count": len(built),
        "with_mesh": sum(1 for p, _ in built if p["facets"]["has_mesh"]),
        "design_count": len(designs),
        "primary_function_counts": dict(sorted(fn.items())),
    }
    write_catalog(CATALOG / "catalog.sqlite", built, designs, meta)
    unknown = sum(1 for p, _ in built for i in p["interfaces"] if i["type"] == "unknown")
    say(f"wrote {CATALOG / 'catalog.sqlite'}: {len(built)} parts, {meta['with_mesh']} with mesh,")
    say(f"  {len(designs)} designs, {unknown} interfaces typed unknown")
    for k, v in sorted(fn.items()):
        say(f"  {v:4d}  {k}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="catalog_build.build")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    m = sub.add_parser("meshes")
    m.add_argument("--only", nargs="*", default=[])
    sub.add_parser("parts")
    args = ap.parse_args(argv)
    if args.cmd == "check":
        return cmd_check()
    if args.cmd == "parts":
        return cmd_parts()
    return cmd_meshes(args.only)


if __name__ == "__main__":
    sys.exit(main())
