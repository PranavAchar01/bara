"""The hero view of a mesh over the triangle budget still shows a closed surface."""

from __future__ import annotations

import zlib

import numpy as np
import pytest

from bara.live import hero


def _plate(n: int) -> hero.Mesh:
    xs = np.linspace(-50, 50, n + 1)
    gx, gy = np.meshgrid(xs, xs)
    verts = np.c_[gx.ravel(), gy.ravel(), np.zeros(gx.size)]
    i = (np.arange(n)[:, None] * (n + 1) + np.arange(n)[None, :]).ravel()
    tris = np.r_[np.c_[i, i + 1, i + n + 1], np.c_[i + 1, i + n + 2, i + n + 1]]
    return verts, tris.astype(np.int64), (0.6, 0.55, 0.45)


def _pixels(png: bytes, size: int) -> np.ndarray:
    raw = zlib.decompress(png[png.index(b"IDAT") + 4 : png.rindex(b"IEND") - 8])
    rows = np.frombuffer(raw, dtype=np.uint8).reshape(size, 1 + size * 3)
    return rows[:, 1:].reshape(size, size, 3)


def test_an_over_budget_plate_has_no_holes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hero, "MAX_TRIS", 2_000)
    plate = _plate(60)  # 7200 triangles
    size = 120
    img = _pixels(hero.render([plate], (0, 0, 200), (0, 0, 0), size=size), size)
    # the plate fills the middle of the frame: none of it may show the background
    mid = img[40:80, 40:80]
    assert not (mid == 244).all(axis=2).any()
    assert sum(len(t) for _, t, _ in hero._within_budget([plate])) <= 2_000
