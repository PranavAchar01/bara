"""Hero-view renderer for the identity judge: GLB meshes to a PNG with numpy only.

The server has no GL context, matplotlib or trimesh, so this is a small z-buffer rasteriser:
read the glTF meshes (nodes, transforms, base colours), put them in build space (mm, z up),
project with a pinhole camera and shade with two lights. It is built to be looked at by a
vision model, not to be pretty.
"""

from __future__ import annotations

import base64
import json
import math
import struct
import subprocess
import zlib
from pathlib import Path
from typing import Any

import numpy as np

Mesh = tuple[np.ndarray, np.ndarray, tuple[float, float, float]]  # verts mm, tris, rgb 0..1

_COMP = {5120: "b", 5121: "B", 5122: "h", 5123: "H", 5125: "I", 5126: "f"}
_NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
MAX_TRIS = 400_000


def _accessor(doc: dict[str, Any], blob: bytes, idx: int) -> np.ndarray:
    acc = doc["accessors"][idx]
    view = doc["bufferViews"][acc["bufferView"]]
    n = _NCOMP[acc["type"]]
    dtype = np.dtype(_COMP[acc["componentType"]]).newbyteorder("<")
    stride = view.get("byteStride")
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    if stride and stride != dtype.itemsize * n:
        item = dtype.itemsize * n
        need = stride * (acc["count"] - 1) + item
        raw = np.frombuffer(blob, dtype=np.uint8, count=need, offset=start)
        raw = np.concatenate([raw, np.zeros(stride - item, dtype=np.uint8)])
        raw = raw.reshape(acc["count"], stride)[:, :item].copy()
        return raw.view(dtype).reshape(acc["count"], n)
    arr = np.frombuffer(blob, dtype=dtype, count=acc["count"] * n, offset=start)
    return arr.reshape(acc["count"], n)


def _positions(doc: dict[str, Any], blob: bytes, idx: int) -> np.ndarray:
    arr = _accessor(doc, blob, idx)
    if doc["accessors"][idx].get("normalized") and arr.dtype.kind in "iu":
        info = np.iinfo(arr.dtype)
        arr = np.maximum(arr / float(info.max), -1.0) if info.min < 0 else arr / float(info.max)
    return arr


def _local(node: dict[str, Any]) -> np.ndarray:
    if "matrix" in node:
        return np.array(node["matrix"], dtype=np.float64).reshape(4, 4).T
    m = np.eye(4)
    if "scale" in node:
        m = np.diag([*node["scale"], 1.0]) @ m
    if "rotation" in node:
        x, y, z, w = node["rotation"]
        r = np.array(
            [
                [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
            ]
        )
        rot = np.eye(4)
        rot[:3, :3] = r
        m = rot @ m
    if "translation" in node:
        t = np.eye(4)
        t[:3, 3] = node["translation"]
        m = t @ m
    return m


def plain_copy(path: Path, cache: Path) -> Path | None:
    """The same GLB with meshopt compression decoded (gltf-transform copy), cached by name."""
    if b"EXT_meshopt_compression" not in path.read_bytes():
        return path
    from bara.geometry.glbopt import GLTF_TRANSFORM

    cache.mkdir(parents=True, exist_ok=True)
    out = cache / f"{path.stem}.plain.glb"
    if out.exists() and out.stat().st_mtime >= path.stat().st_mtime:
        return out
    try:
        done = subprocess.run(  # noqa: S603 - fixed argv
            [*GLTF_TRANSFORM, "copy", str(path), str(out)],
            capture_output=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out if done.returncode == 0 and out.exists() else None


def load_glb(path: Path, unit_scale: float = 1000.0, pose: np.ndarray | None = None) -> list[Mesh]:
    """Meshes of a .glb in build space: mm, x right, y back, z up (glTF is metres, y up).
    pose (a 4x4 in mm) places a board's frame in the build, as the viewer does."""
    data = path.read_bytes()
    if data[:4] != b"glTF":
        return []
    pos, doc, blob = 12, {}, b""
    while pos < len(data):
        length, kind = struct.unpack("<II", data[pos : pos + 8])
        chunk = data[pos + 8 : pos + 8 + length]
        if kind == 0x4E4F534A:
            doc = json.loads(chunk)
        elif kind == 0x004E4942:
            blob = chunk
        pos += 8 + length
    out: list[Mesh] = []
    to_build = np.array([[1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0], [0, 0, 0, 1]], dtype=np.float64)

    def walk(idx: int, parent: np.ndarray) -> None:
        node = doc["nodes"][idx]
        world = parent @ _local(node)
        if "mesh" in node:
            for prim in doc["meshes"][node["mesh"]]["primitives"]:
                if prim.get("mode", 4) != 4 or "POSITION" not in prim["attributes"]:
                    continue
                v = _positions(doc, blob, prim["attributes"]["POSITION"]).astype(np.float64)
                h = np.c_[v, np.ones(len(v))] @ (to_build @ world).T
                if pose is not None:
                    h = h @ pose.T
                if "indices" in prim:
                    tri = _accessor(doc, blob, prim["indices"]).astype(np.int64).reshape(-1, 3)
                else:
                    tri = np.arange(len(v)).reshape(-1, 3)
                rgb = (0.7, 0.7, 0.7)
                if "material" in prim:
                    mat = doc["materials"][prim["material"]]
                    f = mat.get("pbrMetallicRoughness", {}).get("baseColorFactor")
                    if f:
                        rgb = tuple(float(c) for c in f[:3])  # type: ignore[assignment]
                out.append((h[:, :3] * unit_scale, tri, rgb))
        for child in node.get("children", []):
            walk(child, world)

    for root in doc.get("scenes", [{"nodes": []}])[doc.get("scene", 0)].get("nodes", []):
        walk(root, np.eye(4))
    return out


def pose_matrix(position_mm: list[float], rotation_deg: list[float] | None) -> np.ndarray:
    """position_mm and rotation_deg (Euler XYZ, SPEC 3.2) as a 4x4 in mm."""
    from bara.geometry.case import euler_xyz_matrix

    m = np.eye(4)
    m[:3, :3] = euler_xyz_matrix(list(rotation_deg or [0, 0, 0]))
    m[:3, 3] = np.array(position_mm, dtype=np.float64) / 1000.0
    return m


def _png(rgb: np.ndarray) -> bytes:
    h, w, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[y].tobytes() for y in range(h))

    def chunk(tag: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(tag + body) & 0xFFFFFFFF
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", crc)

    head = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", head)
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )


def _cluster(verts: np.ndarray, tris: np.ndarray, cell: float) -> tuple[np.ndarray, np.ndarray]:
    """Merge the vertices in each grid cell and drop the triangles that collapse: fewer
    triangles over the same closed surface (skipping triangles would leave holes)."""
    keys = np.floor(verts / cell).astype(np.int64)
    _, inv, counts = np.unique(keys, axis=0, return_inverse=True, return_counts=True)
    inv = inv.ravel()
    merged = np.zeros((len(counts), 3))
    np.add.at(merged, inv, verts)
    merged /= counts[:, None]
    t = inv[tris]
    keep = (t[:, 0] != t[:, 1]) & (t[:, 1] != t[:, 2]) & (t[:, 0] != t[:, 2])
    t = t[keep]
    first = np.unique(np.sort(t, axis=1), axis=0, return_index=True)[1]
    return merged, t[np.sort(first)]


def _within_budget(meshes: list[Mesh]) -> list[Mesh]:
    """The meshes, clustered on a common grid coarse enough to hold MAX_TRIS triangles."""
    total = sum(len(t) for _, t, _ in meshes)
    if total <= MAX_TRIS:
        return meshes
    pts = np.vstack([v for v, _, _ in meshes])
    cell = float(np.linalg.norm(pts.max(axis=0) - pts.min(axis=0))) / 2000.0
    out = meshes
    while sum(len(t) for _, t, _ in out) > MAX_TRIS:
        out = [(*_cluster(v, t, cell), rgb) for v, t, rgb in meshes]
        cell *= 1.5
    return out


def render(
    meshes: list[Mesh],
    eye: tuple[float, float, float],
    target: tuple[float, float, float],
    size: int = 720,
    fov_deg: float = 35.0,
) -> bytes:
    """A z-buffered, two-light shaded PNG of the meshes seen from eye toward target (z up)."""
    if not meshes:
        return _png(np.full((size, size, 3), 255, dtype=np.uint8))
    eye_v, tgt = np.array(eye, dtype=np.float64), np.array(target, dtype=np.float64)
    fwd = tgt - eye_v
    fwd /= np.linalg.norm(fwd)
    right = np.cross(fwd, [0.0, 0.0, 1.0])
    if np.linalg.norm(right) < 1e-6:
        right = np.array([1.0, 0.0, 0.0])
    right /= np.linalg.norm(right)
    up = np.cross(right, fwd)
    focal = 0.5 * size / np.tan(np.radians(fov_deg) / 2)
    img = np.full((size, size, 3), 244.0)
    zbuf = np.full((size, size), np.inf)
    key = np.array([-0.45, -0.55, 0.7])
    key /= np.linalg.norm(key)
    for verts, tris, rgb in _within_budget(meshes):
        rel = verts - eye_v
        cam = np.c_[rel @ right, rel @ up, rel @ fwd]
        ok = cam[:, 2] > 1.0
        px = size / 2 + focal * cam[:, 0] / np.maximum(cam[:, 2], 1e-6)
        py = size / 2 - focal * cam[:, 1] / np.maximum(cam[:, 2], 1e-6)
        pa, pb, pc = verts[tris[:, 0]], verts[tris[:, 1]], verts[tris[:, 2]]
        nrm = np.cross(pb - pa, pc - pa)
        ln = np.linalg.norm(nrm, axis=1)
        nrm = nrm / np.maximum(ln, 1e-12)[:, None]
        to_eye = eye_v - (pa + pb + pc) / 3
        flip = (nrm * to_eye).sum(axis=1) < 0
        nrm[flip] *= -1
        shade = 0.38 + 0.52 * np.clip(nrm @ key, 0, 1) + 0.1 * np.clip(nrm @ -fwd, 0, 1)
        # dark materials (graphite keys, glass) lifted so their shape reads on a grey ground
        base = (0.22 + 0.78 * np.array(rgb)) * 255.0
        for t in range(len(tris)):
            a, b, c = tris[t]
            if not (ok[a] and ok[b] and ok[c]) or ln[t] < 1e-9:
                continue
            xs, ys = (px[a], px[b], px[c]), (py[a], py[b], py[c])
            x0, x1 = int(max(min(xs), 0)), int(min(max(xs), size - 1))
            y0, y1 = int(max(min(ys), 0)), int(min(max(ys), size - 1))
            if x1 < x0 or y1 < y0:
                continue
            den = (ys[1] - ys[2]) * (xs[0] - xs[2]) + (xs[2] - xs[1]) * (ys[0] - ys[2])
            if abs(den) < 1e-9:
                continue
            gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
            w0 = ((ys[1] - ys[2]) * (gx - xs[2]) + (xs[2] - xs[1]) * (gy - ys[2])) / den
            w1 = ((ys[2] - ys[0]) * (gx - xs[2]) + (xs[0] - xs[2]) * (gy - ys[2])) / den
            w2 = 1 - w0 - w1
            inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
            if not inside.any():
                continue
            z = w0 * cam[a, 2] + w1 * cam[b, 2] + w2 * cam[c, 2]
            win = zbuf[y0 : y1 + 1, x0 : x1 + 1]
            take = inside & (z < win)
            if not take.any():
                continue
            win[take] = z[take]
            img[y0 : y1 + 1, x0 : x1 + 1][take] = np.clip(base * shade[t], 0, 255)
    return _png(img.astype(np.uint8))


def to_b64(png: bytes) -> str:
    return base64.b64encode(png).decode()


def stand_up(meshes: list[Mesh]) -> list[Mesh]:
    """Build space has the main face toward +z; an upright product stands with that face toward
    the viewer (-y) and its top (+y) up, so rotate +90 degrees about x."""
    rot = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]])
    return [(verts @ rot.T, tris, rgb) for verts, tris, rgb in meshes]


def hero_camera(
    meshes: list[Mesh], rest_pose: str = "face_up"
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Eye and target that frame every mesh from the front-top-left, like the viewer's hero.
    An upright product (already stood up) is seen from nearer eye height.

    A face-up product is seen from high enough that its plan keeps its proportions: from a low
    angle the depth foreshortens by sin(elevation), so a portrait slab (deeper than wide) read
    as landscape to the identity judge (130 x 195 mm at 36 degrees projects 130 x 115). The
    elevation is raised until the projected depth keeps the plan's orientation."""
    pts = np.vstack([m[0] for m in meshes]) if meshes else np.zeros((1, 3))
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    centre = (lo + hi) / 2
    radius = float(np.linalg.norm(hi - lo)) / 2 or 50.0
    if rest_pose == "face_up":
        w, d = float(hi[0] - lo[0]), float(hi[1] - lo[1])
        elev = math.radians(58.0)
        if d > w > 0:  # portrait in plan: projected depth at least 1.15x the width
            elev = max(elev, math.asin(min(1.0, 1.15 * w / d)))
        elev = min(elev, math.radians(78.0))  # keep the front edge and thickness visible
        horiz = np.array([-0.35, -0.8]) / np.linalg.norm([-0.35, -0.8])
        direction = np.array([*(horiz * math.cos(elev)), math.sin(elev)])
    else:
        direction = np.array([-0.35, -0.8, 0.3])
    direction /= np.linalg.norm(direction)
    dist = radius / np.sin(np.radians(17.5)) * 1.08
    eye = centre + direction * dist
    return (float(eye[0]), float(eye[1]), float(eye[2])), (
        float(centre[0]),
        float(centre[1]),
        float(centre[2]),
    )
