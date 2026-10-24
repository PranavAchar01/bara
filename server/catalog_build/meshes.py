"""KiCad 3D models -> one GLB per part, through kicad-cli.

Each part is written as a one-footprint .kicad_pcb (footprint at the origin, only the
selected model entries kept, model paths resolved to absolute files) and exported
with `kicad-cli pcb export glb --no-board-body`, so KiCad itself applies each model's
offset, rotation and scale exactly as it does on a real board. The GLB is then welded
and simplified with gltf-transform. Output: metres, Y up (glTF), which the viewer maps
to SPEC 3.2 build space with scale 1000 and +90 deg about X.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import struct
import subprocess
from pathlib import Path
from typing import Any

from .kicad_lib import Footprint, Model
from .sexpr import Node, Quoted, children, dump

KICAD_CLI = os.environ.get("KICAD_CLI", "/opt/homebrew/bin/kicad-cli")
GLTF_TRANSFORM = ["npx", "-y", "@gltf-transform/cli@4.1.1"]

PCB_HEADER = """(kicad_pcb
\t(version 20241229)
\t(generator "bara_catalog")
\t(generator_version "10.0")
\t(general (thickness 1.6) (legacy_teardrops no))
\t(paper "A4")
\t(layers
\t\t(0 "F.Cu" signal) (2 "B.Cu" signal)
\t\t(9 "F.Adhes" user "F.Adhesive") (11 "B.Adhes" user "B.Adhesive")
\t\t(13 "F.Paste" user) (15 "B.Paste" user)
\t\t(5 "F.SilkS" user "F.Silkscreen") (7 "B.SilkS" user "B.Silkscreen")
\t\t(1 "F.Mask" user) (3 "B.Mask" user)
\t\t(17 "Dwgs.User" user "User.Drawings") (19 "Cmts.User" user "User.Comments")
\t\t(21 "Eco1.User" user "User.Eco1") (23 "Eco2.User" user "User.Eco2")
\t\t(25 "Edge.Cuts" user) (27 "Margin" user)
\t\t(31 "F.CrtYd" user "F.Courtyard") (29 "B.CrtYd" user "B.Courtyard")
\t\t(35 "F.Fab" user) (33 "B.Fab" user)
\t)
\t(setup (pad_to_mask_clearance 0))
\t(net 0 "")
"""

BOARD_THICKNESS_MM = 1.6  # matches (general (thickness 1.6)) in PCB_HEADER
SIMPLIFY_ABOVE_BYTES = 250_000

DROP_HEADS = {"version", "generator", "generator_version", "embedded_fonts", "embedded_files"}
# Graphics are irrelevant to the 3D export and legacy (KiCad 5) arcs fail to parse inside a
# current-format board, so they are dropped from the temporary board.
DROP_GRAPHICS = {
    "fp_line",
    "fp_arc",
    "fp_circle",
    "fp_poly",
    "fp_rect",
    "fp_text",
    "fp_curve",
    "fp_text_box",
    "zone",
    "group",
    "dimension",
    "image",
    "property",
}


def model_node(path: Path, m: Model | None = None) -> Node:
    off = m.offset if m else (0.0, 0.0, 0.0)
    # kicad-cli puts the board bottom at z = 0 and the top at z = thickness; shift so
    # z = 0 is the PCB seating plane (top face), as SPEC 3.2 part frames expect.
    off = (off[0], off[1], off[2] - BOARD_THICKNESS_MM)
    rot = m.rotate if m else (0.0, 0.0, 0.0)
    sc = m.scale if m else (1.0, 1.0, 1.0)
    return [
        "model",
        Quoted(str(path)),
        ["offset", ["xyz", *[repr(float(v)) for v in off]]],
        ["scale", ["xyz", *[repr(float(v)) for v in sc]]],
        ["rotate", ["xyz", *[repr(float(v)) for v in rot]]],
    ]


def board_text(fp: Footprint | None, models: list[tuple[Path, Model | None]]) -> str:
    """One footprint at (0, 0) carrying only the given (resolved) models."""
    if fp is None:
        body: Node = ["footprint", Quoted("bara:model_only"), ["layer", Quoted("F.Cu")]]
    else:
        body = [copy.deepcopy(x) if isinstance(x, list) else x for x in fp.node]
        body = [
            x
            for x in body
            if not (
                isinstance(x, list) and x and x[0] in DROP_HEADS | DROP_GRAPHICS | {"model", "at"}
            )
        ]
        body[1] = Quoted(f"bara:{fp.name}")
    insert_at = 2
    for i, item in enumerate(body):
        if isinstance(item, list) and item and item[0] == "layer":
            insert_at = i + 1
    body.insert(insert_at, ["at", "0", "0"])
    body += [model_node(path, m) for path, m in models]
    return PCB_HEADER + "\t" + dump(body) + "\n)\n"


def _run(cmd: list[str], timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["nice", "-n", "19", "taskpolicy", "-b", *cmd],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def export_glb(
    work: Path,
    stem: str,
    fp: Footprint | None,
    models: list[tuple[Path, Model | None]],
    out: Path,
) -> dict[str, Any]:
    """Export and simplify. Returns {"ok", "raw_bytes", "bytes", "log"}."""
    work.mkdir(parents=True, exist_ok=True)
    pcb = work / f"{stem}.kicad_pcb"
    pcb.write_text(board_text(fp, models))
    raw = work / f"{stem}.raw.glb"
    res = _run(
        [
            KICAD_CLI,
            "pcb",
            "export",
            "glb",
            "--force",
            "--no-board-body",
            "--user-origin",
            "0x0mm",
            "-o",
            str(raw),
            str(pcb),
        ],
        timeout=600,
    )
    if res.returncode != 0 or not raw.exists() or raw.stat().st_size < 200:
        return {"ok": False, "log": (res.stdout + res.stderr)[-800:]}
    out.parent.mkdir(parents=True, exist_ok=True)
    shrink(raw, out, work)
    return {"ok": True, "raw_bytes": raw.stat().st_size, "bytes": out.stat().st_size, "log": ""}


def shrink(raw: Path, out: Path, work: Path) -> bool:
    """Copy small GLBs as is; simplify larger ones (no Draco/meshopt, so any glTF loader
    reads them). Falls back to the raw file if gltf-transform fails."""
    out.parent.mkdir(parents=True, exist_ok=True)
    size = raw.stat().st_size
    if size <= SIMPLIFY_ABOVE_BYTES:
        shutil.copyfile(raw, out)
        return True
    ratio = 0.5 if size < 1_000_000 else 0.3 if size < 4_000_000 else 0.15
    tmp = work / f"{out.stem}.opt.glb"
    r = _run(
        [
            *GLTF_TRANSFORM,
            "optimize",
            str(raw),
            str(tmp),
            "--compress",
            "false",
            "--texture-compress",
            "false",
            "--instance",
            "false",
            "--simplify-ratio",
            str(ratio),
            "--simplify-error",
            "0.002",
        ],
        timeout=600,
    )
    if r.returncode == 0 and tmp.exists() and 0 < tmp.stat().st_size < size:
        shutil.copyfile(tmp, out)
        return True
    shutil.copyfile(raw, out)
    return False


def glb_bounds(path: Path) -> dict[str, list[float]] | None:
    """Exact bounds of all mesh vertices after node transforms, in SPEC part frame (mm)."""
    import numpy as np  # local import: only the build needs numpy
    import trimesh

    scene = trimesh.load(str(path), force="scene")
    if not scene.geometry:
        return None
    lo, hi = scene.bounds  # glTF metres, Y up
    # Viewer mapping: scale 1000, rotate +90 deg about X: (x, y, z) -> (x, -z, y).
    corners = (
        np.array(
            [[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
        )
        * 1000.0
    )
    mapped = np.stack([corners[:, 0], -corners[:, 2], corners[:, 1]], axis=1)
    return {
        "min": [round(float(v), 3) for v in mapped.min(axis=0)],
        "max": [round(float(v), 3) for v in mapped.max(axis=0)],
    }


def translate_glb(src: Path, dst: Path, t: tuple[float, float, float]) -> None:
    """Lossless re-centre: wrap the scene roots in one node with a glTF translation (m)."""
    data = src.read_bytes()
    (jlen,) = struct.unpack_from("<I", data, 12)
    doc = json.loads(data[20 : 20 + jlen])
    rest = data[20 + jlen :]
    scene = doc["scenes"][doc.get("scene", 0)]
    doc.setdefault("nodes", []).append(
        {"name": "bara_recentre", "translation": list(t), "children": scene["nodes"]}
    )
    scene["nodes"] = [len(doc["nodes"]) - 1]
    js = json.dumps(doc, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    body = struct.pack("<II", len(js), 0x4E4F534A) + js + rest
    dst.write_bytes(struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body)


def glb_node_names(path: Path) -> list[str]:
    data = path.read_bytes()
    if len(data) < 20 or data[:4] != b"glTF":
        return []
    (length,) = struct.unpack_from("<I", data, 12)
    doc = json.loads(data[20 : 20 + length])
    return [n["name"] for n in doc.get("nodes", []) if n.get("name")][:64]


__all__ = ["board_text", "export_glb", "glb_bounds", "glb_node_names", "children"]
