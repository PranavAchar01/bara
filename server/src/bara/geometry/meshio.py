"""Mesh file writers (GLB, binary STL, 3MF) and small readers used to check them.

Meshes are (vertices, triangles) numpy pairs in build space: millimetres, Z up. The GLB
writer converts to glTF convention (metres, Y up) so the viewer's fixed transform
(scale 1000, rotate +90 deg about X, SPEC 3.2) puts the case back in build space.
"""

from __future__ import annotations

import io
import json
import struct
import zipfile
from dataclasses import dataclass
from xml.etree import ElementTree

import numpy as np


@dataclass
class MeshPart:
    name: str
    vertices: np.ndarray  # (n, 3) float, mm, build space
    triangles: np.ndarray  # (m, 3) int
    normals: np.ndarray | None = None  # (n, 3) float, build space
    color_hex: str = "#9E9E9E"
    roughness: float = 0.55


def _srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex_rgba(hex_color: str) -> list[float]:
    h = hex_color.lstrip("#")
    rgb = [int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4)]
    alpha = int(h[6:8], 16) / 255.0 if len(h) == 8 else 1.0
    return [round(_srgb_to_linear(c), 5) for c in rgb] + [alpha]


def _to_gltf(v: np.ndarray, scale: float) -> np.ndarray:
    # build (X, Y, Z) -> glTF (X, Z, -Y); inverse of the viewer's +90 deg X rotation.
    out = np.empty_like(v, dtype=np.float32)
    out[:, 0] = v[:, 0] * scale
    out[:, 1] = v[:, 2] * scale
    out[:, 2] = -v[:, 1] * scale
    return out


def write_glb(parts: list[MeshPart]) -> bytes:
    """One node + mesh + material per part; node names are addressable for recolor."""
    blob = bytearray()
    buffer_views: list[dict] = []
    accessors: list[dict] = []
    meshes: list[dict] = []
    materials: list[dict] = []
    nodes: list[dict] = []

    def add_view(data: bytes, target: int) -> int:
        while len(blob) % 4:
            blob.append(0)
        buffer_views.append(
            {"buffer": 0, "byteOffset": len(blob), "byteLength": len(data), "target": target}
        )
        blob.extend(data)
        return len(buffer_views) - 1

    for part in parts:
        pos = _to_gltf(np.asarray(part.vertices, dtype=np.float64), 0.001)
        idx = np.asarray(part.triangles, dtype=np.uint32).reshape(-1)
        attrs: dict[str, int] = {}
        view = add_view(pos.tobytes(), 34962)
        accessors.append(
            {
                "bufferView": view,
                "componentType": 5126,
                "count": int(pos.shape[0]),
                "type": "VEC3",
                "min": [float(x) for x in pos.min(axis=0)],
                "max": [float(x) for x in pos.max(axis=0)],
            }
        )
        attrs["POSITION"] = len(accessors) - 1
        if part.normals is not None:
            nrm = _to_gltf(np.asarray(part.normals, dtype=np.float64), 1.0)
            lens = np.linalg.norm(nrm, axis=1, keepdims=True)
            nrm = (nrm / np.where(lens > 0, lens, 1)).astype(np.float32)
            view = add_view(nrm.tobytes(), 34962)
            accessors.append(
                {
                    "bufferView": view,
                    "componentType": 5126,
                    "count": int(nrm.shape[0]),
                    "type": "VEC3",
                }
            )
            attrs["NORMAL"] = len(accessors) - 1
        view = add_view(idx.tobytes(), 34963)
        accessors.append(
            {"bufferView": view, "componentType": 5125, "count": int(idx.size), "type": "SCALAR"}
        )
        materials.append(
            {
                "name": f"{part.name}_mat",
                "pbrMetallicRoughness": {
                    "baseColorFactor": hex_rgba(part.color_hex),
                    "metallicFactor": 0.0,
                    "roughnessFactor": part.roughness,
                },
            }
        )
        meshes.append(
            {
                "name": part.name,
                "primitives": [
                    {
                        "attributes": attrs,
                        "indices": len(accessors) - 1,
                        "material": len(materials) - 1,
                    }
                ],
            }
        )
        nodes.append({"name": part.name, "mesh": len(meshes) - 1})

    while len(blob) % 4:
        blob.append(0)
    gltf = {
        "asset": {"version": "2.0", "generator": "bara.geometry"},
        "scene": 0,
        "scenes": [{"nodes": list(range(len(nodes)))}],
        "nodes": nodes,
        "meshes": meshes,
        "materials": materials,
        "accessors": accessors,
        "bufferViews": buffer_views,
        "buffers": [{"byteLength": len(blob)}],
    }
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    total = 12 + 8 + len(js) + 8 + len(blob)
    out = io.BytesIO()
    out.write(struct.pack("<III", 0x46546C67, 2, total))
    out.write(struct.pack("<II", len(js), 0x4E4F534A))
    out.write(js)
    out.write(struct.pack("<II", len(blob), 0x004E4942))
    out.write(bytes(blob))
    return out.getvalue()


def read_glb(data: bytes) -> dict:
    """Parse a GLB header and JSON chunk; raises ValueError on a malformed file."""
    magic, version, total = struct.unpack_from("<III", data, 0)
    if magic != 0x46546C67 or version != 2 or total != len(data):
        raise ValueError("not a glTF 2.0 binary")
    jlen, jtype = struct.unpack_from("<II", data, 12)
    if jtype != 0x4E4F534A:
        raise ValueError("first chunk is not JSON")
    gltf = json.loads(data[20 : 20 + jlen])
    blen, btype = struct.unpack_from("<II", data, 20 + jlen)
    if btype != 0x004E4942 or blen < gltf["buffers"][0]["byteLength"]:
        raise ValueError("bad BIN chunk")
    return gltf


def write_stl(parts: list[MeshPart], name: str = "bara_case") -> bytes:
    tris = []
    for part in parts:
        v = np.asarray(part.vertices, dtype=np.float64)
        tris.append(v[np.asarray(part.triangles, dtype=np.int64)])
    t = np.concatenate(tris) if tris else np.zeros((0, 3, 3))
    n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    lens = np.linalg.norm(n, axis=1, keepdims=True)
    n = n / np.where(lens > 0, lens, 1)
    rec = np.zeros(len(t), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    rec["n"] = n
    rec["v"] = t
    header = name.encode()[:80].ljust(80, b" ")
    return header + struct.pack("<I", len(t)) + rec.tobytes()


def read_stl(data: bytes) -> np.ndarray:
    """Binary STL to (n, 3, 3) triangles; raises ValueError on a size mismatch."""
    (count,) = struct.unpack_from("<I", data, 80)
    if len(data) != 84 + 50 * count:
        raise ValueError("binary STL size mismatch")
    rec = np.frombuffer(
        data, dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")], offset=84
    )
    return rec["v"].astype(np.float64)


_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"


def write_3mf(parts: list[MeshPart]) -> bytes:
    """3MF core package, one object per part, millimetre units, colour as basematerials."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<model unit="millimeter" xml:lang="en-US" xmlns="{_NS}">',
        "<resources>",
        '<basematerials id="1">',
    ]
    for part in parts:
        lines.append(f'<base name="{part.name}" displaycolor="{part.color_hex.upper()[:7]}FF"/>')
    lines.append("</basematerials>")
    for i, part in enumerate(parts):
        oid = i + 2
        lines.append(f'<object id="{oid}" name="{part.name}" type="model" pid="1" pindex="{i}">')
        lines.append("<mesh><vertices>")
        lines.extend(
            f'<vertex x="{x:.4f}" y="{y:.4f}" z="{z:.4f}"/>'
            for x, y, z in np.asarray(part.vertices, dtype=np.float64)
        )
        lines.append("</vertices><triangles>")
        lines.extend(
            f'<triangle v1="{a}" v2="{b}" v3="{c}"/>'
            for a, b, c in np.asarray(part.triangles, dtype=np.int64)
        )
        lines.append("</triangles></mesh></object>")
    lines.append("</resources><build>")
    lines.extend(f'<item objectid="{i + 2}"/>' for i in range(len(parts)))
    lines.append("</build></model>")
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="model" '
        'ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
        'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
        "</Relationships>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("3D/3dmodel.model", "\n".join(lines))
    return buf.getvalue()


def read_3mf(data: bytes) -> list[tuple[np.ndarray, np.ndarray]]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        root = ElementTree.fromstring(zf.read("3D/3dmodel.model"))
    out = []
    for obj in root.iter(f"{{{_NS}}}object"):
        verts = np.array(
            [[float(v.get(k, "0")) for k in ("x", "y", "z")] for v in obj.iter(f"{{{_NS}}}vertex")]
        )
        tris = np.array(
            [
                [int(t.get(k, "0")) for k in ("v1", "v2", "v3")]
                for t in obj.iter(f"{{{_NS}}}triangle")
            ]
        )
        out.append((verts, tris))
    return out
