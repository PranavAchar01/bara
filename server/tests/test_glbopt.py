"""GLB compression and the validity check that guards the board cache."""

from __future__ import annotations

import shutil
import struct
from pathlib import Path

import numpy as np
import pytest

from bara.geometry import glbopt
from bara.geometry.meshio import MeshPart, read_glb, write_glb


def _cube_glb() -> bytes:
    v = np.array([[x, y, z] for x in (0, 10) for y in (0, 10) for z in (0, 10)], dtype=np.float64)
    t = np.array(
        [
            [0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1],
            [2, 3, 7], [2, 7, 6], [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3],
        ]
    )  # fmt: skip
    return write_glb([MeshPart("a", v, t), MeshPart("b", v + 20, t, color_hex="#336699")])


def test_valid_glb_passes(tmp_path: Path) -> None:
    p = tmp_path / "ok.glb"
    p.write_bytes(_cube_glb())
    assert glbopt.is_valid(p)


def test_interleaved_glb_fails(tmp_path: Path) -> None:
    # Two writers into one file: the JSON runs past its declared length and the binary
    # chunk is cut short, while the header still describes the first writer's file.
    data = bytearray(_cube_glb())
    (jlen,) = struct.unpack_from("<I", data, 12)
    bad = data[: 20 + jlen - 8] + b',"x":1}' + b" " + data[20 + jlen :]
    p = tmp_path / "bad.glb"
    p.write_bytes(bytes(bad))
    assert not glbopt.is_valid(p)
    trunc = tmp_path / "trunc.glb"
    trunc.write_bytes(bytes(data[:-16]))
    assert not glbopt.is_valid(trunc)


def test_compress_disabled_copies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BARA_GLB_COMPRESS", "0")
    raw = tmp_path / "raw.glb"
    raw.write_bytes(_cube_glb())
    out = tmp_path / "out" / "part.glb"
    plain = glbopt.compress(raw, out, tmp_path / "work", keep_named=False, simplify=True)
    assert plain == raw
    assert out.read_bytes() == raw.read_bytes()


def test_compress_falls_back_when_tool_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(glbopt, "GLTF_TRANSFORM", ["false"])
    raw = tmp_path / "raw.glb"
    raw.write_bytes(_cube_glb())
    out = tmp_path / "part.glb"
    assert glbopt.compress(raw, out, tmp_path / "work", keep_named=True, simplify=False) == raw
    assert glbopt.is_valid(out)


@pytest.mark.skipif(shutil.which("npx") is None, reason="needs npx for gltf-transform")
def test_compress_joins_and_meshopts(tmp_path: Path) -> None:
    raw = tmp_path / "raw.glb"
    raw.write_bytes(_cube_glb())
    out = tmp_path / "part.glb"
    plain = glbopt.compress(raw, out, tmp_path / "work", keep_named=False, simplify=False)
    if plain == raw:
        pytest.skip("gltf-transform unavailable (offline)")
    assert glbopt.is_valid(out) and glbopt.is_valid(plain)
    doc = read_glb(out.read_bytes())
    assert "EXT_meshopt_compression" in doc.get("extensionsUsed", [])
    # Two materials stay two materials: no palette merge.
    assert len(doc["materials"]) == 2
