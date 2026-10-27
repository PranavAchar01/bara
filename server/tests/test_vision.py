"""The fit check: OpenCV measurement on synthetic photos, and the choices the agent makes."""

from __future__ import annotations

import base64

import cv2
import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bara.vision import agent
from bara.vision.measure import measure
from bara.vision.routes import build_vision_router
from bara.vision.synth import make_scene


@pytest.fixture(autouse=True)
def _local(monkeypatch):
    monkeypatch.delenv("BARA_VISION_URL", raising=False)


@pytest.mark.parametrize(
    "seed,w,d,kind",
    [
        (1, 120, 70, "rectangle"),
        (2, 80, 80, "round"),
        (3, 150, 60, "rectangle"),
        (4, 60, 40, "oval"),
    ],
)
def test_measures_known_sizes_within_2mm(seed, w, d, kind):
    scene = make_scene(np.random.default_rng(seed), w, d, "round" if kind != "rectangle" else kind)
    r = measure(scene.jpg)
    assert r["status"] == "ok", r["tried"]
    assert abs(r["object"]["width_mm"] - w) <= 2.0
    assert abs(r["object"]["depth_mm"] - d) <= 2.0
    assert r["object"]["kind"] == kind


def test_photo_without_marker_asks_for_a_retake():
    img = np.full((600, 800, 3), 180, np.uint8)
    cv2.rectangle(img, (300, 200), (500, 350), (40, 40, 40), -1)
    ok, jpg = cv2.imencode(".jpg", img)
    assert ok
    out = agent.decide(jpg.tobytes())
    assert out["measurement"]["status"] == "no_marker"
    assert [s.get("args", {}).get("enhance") for s in out["steps"] if s.get("tool")] == [
        False,
        True,
    ]
    assert out["action"]["kind"] == "retake"


def test_no_build_proposes_a_sized_build():
    scene = make_scene(np.random.default_rng(5), 140, 90)
    out = agent.decide(scene.jpg, device="a macro pad with four keys", clearance_mm=2)
    assert out["action"]["kind"] == "build"
    assert out["action"]["needs_approval"] is True
    assert out["action"]["prompt"].startswith("a macro pad with four keys.")
    assert "mm" in out["action"]["prompt"]


def test_open_build_that_is_too_big_gets_a_shrink_proposal():
    scene = make_scene(np.random.default_rng(6), 100, 60)
    enc = {"enclosure_id": "enc_1", "outer_size_mm": [130.0, 70.0, 20.0]}
    out = agent.decide(scene.jpg, enclosure=enc)
    assert out["fit"]["footprint_fits"] is False
    assert out["action"]["kind"] == "prompt"


def test_open_build_that_fits_is_reported_and_height_is_checked():
    scene = make_scene(np.random.default_rng(7), 160, 110)
    enc = {"enclosure_id": "enc_1", "outer_size_mm": [90.0, 140.0, 30.0]}
    out = agent.decide(scene.jpg, enclosure=enc)
    assert out["fit"]["footprint_fits"] is True
    assert out["action"]["kind"] == "none"
    out = agent.decide(scene.jpg, enclosure=enc, height_limit_mm=20)
    assert out["action"]["kind"] == "edit"
    assert out["action"]["ops"][0]["params"] == {"height_mm": 20}


def test_route_round_trip():
    app = FastAPI()
    app.include_router(build_vision_router())
    client = TestClient(app)
    scene = make_scene(np.random.default_rng(8), 120, 80)
    res = client.post(
        "/v1/vision/fit",
        json={"image_b64": base64.b64encode(scene.jpg).decode(), "device": "a remote"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["measurement"]["opencv"].startswith("5.")
    assert data["annotated_jpg_b64"]
    png = client.get("/v1/vision/marker.png")
    assert png.status_code == 200 and png.content[:4] == b"\x89PNG"
