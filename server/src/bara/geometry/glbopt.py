"""GLB compression shared by the part catalog and the board stage.

kicad-cli writes one primitive per pad, track and model face (a keyboard board is about
33k primitives, 29 MB). join merges them per material, which cuts draw calls by two
orders of magnitude, and meshopt (quantised, EXT_meshopt_compression, decoded by the
viewer's MeshoptDecoder) shrinks the file about 10x with no visible loss. Materials stay
as kicad-cli wrote them (no palette), so the viewer can tell mask, silk and copper apart.

dedup is left out on purpose: on a board it takes 20 s of the 25 s a full `optimize` costs
and saves almost nothing after join. Measured on a 29 MB keyboard board: join + meshopt
3.6 s, 2.5 MB, 17 primitives (142 with named footprint nodes kept).

The uncompressed joined file is kept beside the output: trimesh (glb_bounds) cannot read
meshopt buffers, so bounds and node names come from it.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import struct
import subprocess
from pathlib import Path

GLTF_TRANSFORM = shlex.split(
    os.environ.get("BARA_GLTF_TRANSFORM", "npx -y @gltf-transform/cli@4.1.1")
)
# Simplify only meshes this big (bytes after join); compression handles the rest.
SIMPLIFY_ABOVE_BYTES = 4_000_000
# meshoptimizer error is a fraction of the mesh extent: 0.001 of a 20 mm part is 0.02 mm.
SIMPLIFY_ERROR = 0.001
SIMPLIFY_MIN_RATIO = 0.25


def is_valid(path: Path) -> bool:
    """True when the GLB's header and chunk lengths agree with the file and its JSON parses.
    Catches files two writers interleaved into (the viewer cannot load those)."""
    try:
        data = path.read_bytes()
        magic, _, total = struct.unpack_from("<III", data, 0)
        jlen, jtype = struct.unpack_from("<II", data, 12)
        if magic != 0x46546C67 or total != len(data) or jtype != 0x4E4F534A:
            return False
        json.loads(data[20 : 20 + jlen])
        end = 20 + jlen
        if end < len(data):
            blen, btype = struct.unpack_from("<II", data, end)
            if btype != 0x004E4942 or end + 8 + blen > len(data):
                return False
        return True
    except (OSError, ValueError, struct.error):
        return False


# KiCad reference designators (SW3, U1, SW_RST1, LED3A); the viewer uses the same pattern.
REFDES = re.compile(r"^[A-Z][A-Za-z0-9]*([_-][A-Za-z0-9]+)*\d+[A-Za-z]?$")


def name_footprint_meshes(src: Path, dst: Path) -> bool:
    """kicad-cli names a node per footprint (SW3, U1). Under it sit the footprint's 3D model
    meshes, named by OpenCASCADE labels (=>[0:1:1:3]) or, for STEP assemblies, by their own
    part names (main:1, Shell:1). Give every mesh under a footprint the footprint's name and
    drop the other names, so join keeps one node per footprint (the viewer hovers by it) and
    merges the rest. Rewrites the JSON chunk only. False when nothing was renamed."""
    data = src.read_bytes()
    (jlen,) = struct.unpack_from("<I", data, 12)
    doc = json.loads(data[20 : 20 + jlen])
    nodes = doc.get("nodes", [])
    meshes = doc.get("meshes", [])
    renamed = 0

    def walk(i: int, owner: str | None) -> None:
        nonlocal renamed
        node = nodes[i]
        name = node.get("name") or ""
        # The outermost refdes is the footprint; refdes-looking names inside its model
        # (SW_Cherry_MX_PCB_cp_36) are STEP part names and lose their name like any other.
        if owner is None and REFDES.match(name):
            owner = name
        elif owner:
            if "mesh" in node:
                node["name"] = owner
                renamed += 1
            else:
                node.pop("name", None)
        if owner and "mesh" in node:
            # three.js names a multi-primitive mesh's children after the glTF mesh, so the
            # STEP part name must go there too.
            meshes[node["mesh"]].pop("name", None)
        elif name.startswith("=>"):
            node.pop("name", None)
        for c in node.get("children", []):
            walk(c, owner)

    for root in doc["scenes"][doc.get("scene", 0)]["nodes"]:
        walk(root, None)
    if not renamed:
        return False
    js = json.dumps(doc, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    rest = data[20 + jlen :]
    body = struct.pack("<II", len(js), 0x4E4F534A) + js + rest
    dst.write_bytes(struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body)
    return True


def enabled() -> bool:
    return os.environ.get("BARA_GLB_COMPRESS", "1") != "0"


def _gt(args: list[str], timeout: float) -> bool:
    try:
        proc = subprocess.run(
            [*GLTF_TRANSFORM, *args], capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def compress(
    raw: Path,
    out: Path,
    work: Path,
    *,
    keep_named: bool,
    simplify: bool,
    timeout: float = 600,
) -> Path:
    """Write `out` (joined, simplified when `simplify` and very large, meshopt) and return
    the uncompressed joined file in `work`, for bounds and node names. Boards pass
    simplify=False: their detail is never reduced. Falls back to copying `raw` when
    gltf-transform fails or is disabled; then `raw` is returned."""
    out.parent.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    plain = work / f"{out.stem}.plain.glb"
    if not enabled():
        shutil.copyfile(raw, out)
        return raw
    src = raw
    if keep_named:
        named = work / f"{out.stem}.named.glb"
        if name_footprint_meshes(raw, named):
            src = named
    joined = _gt(
        ["join", str(src), str(plain), "--keepNamed", "true" if keep_named else "false"], timeout
    )
    if not joined or not plain.exists():
        shutil.copyfile(raw, out)
        return raw
    size = plain.stat().st_size
    if simplify and size > SIMPLIFY_ABOVE_BYTES:
        ratio = max(SIMPLIFY_MIN_RATIO, SIMPLIFY_ABOVE_BYTES / size)
        tmp = plain.with_suffix(".simple.glb")
        args = [
            "simplify",
            str(plain),
            str(tmp),
            "--ratio",
            f"{ratio:.3f}",
            "--error",
            str(SIMPLIFY_ERROR),
        ]
        if _gt(args, timeout) and tmp.exists():
            tmp.replace(plain)
    tmp = work / f"{out.stem}.meshopt.glb"
    if _gt(["meshopt", str(plain), str(tmp), "--level", "high"], timeout) and tmp.exists():
        tmp.replace(out)
    else:
        shutil.copyfile(plain, out)
    return plain


__all__ = ["compress", "enabled", "is_valid", "name_footprint_meshes"]
