"""A part with no model of its own is drawn from its KiCad footprint's 3D model, never a box."""

from __future__ import annotations

import pytest

from bara.kicad_generated import GLB_URL, KicadIndex
from bara.live.compose import _model_from_footprint

FP = "Connector_PinHeader_2.54mm:PinHeader_1x16_P2.54mm_Vertical"


@pytest.fixture
def lender() -> str:
    index = KicadIndex.open()
    found = index.model_footprint(FP) if index is not None else None
    if found is None:
        pytest.skip("the KiCad index or its footprint is missing")
    return found


def test_a_part_with_no_model_gets_its_footprint_model(lender: str) -> None:
    assets: list[dict] = [{"kind": "pdf", "role": "datasheet", "url": "https://x/ds.pdf"}]
    _model_from_footprint({"footprint": FP}, assets)
    glb = [a for a in assets if a.get("kind") == "glb"]
    assert len(glb) == 1 and glb[0]["role"] == "model"
    assert glb[0]["url"].startswith(GLB_URL + "/") and glb[0]["status"] == "pending"


def test_a_missing_model_is_replaced_and_a_remote_one_kept(lender: str) -> None:
    missing = [
        {"kind": "glb", "role": "model", "url": "/assets/parts/nope.glb", "status": "missing"}
    ]
    _model_from_footprint({"footprint": FP}, missing)
    assert missing[0]["url"].startswith(GLB_URL + "/") and len(missing) == 1
    remote = [{"kind": "glb", "role": "model", "url": "https://cdn/x.glb", "status": "ready"}]
    _model_from_footprint({"footprint": FP}, remote)
    assert remote[0]["url"] == "https://cdn/x.glb"
