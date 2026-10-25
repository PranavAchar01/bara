"""Form features change the body itself: a thin appendage reaching past the rim (a stake, a
lug with a hole), a wedge whose underside deepens toward its thick end, lid grooves, a pocket,
a pad and a clear lens on the face. Each is checked on a built case, and the form rejects
features it could not build."""

from __future__ import annotations

from typing import Any

import manifold3d as mf
import pytest

from bara.geometry import enclose_report
from bara.geometry.shell_fixtures import FIXTURES, brief_for
from bara.live import form as F


def _feat(kind: str, **kw: Any) -> dict[str, Any]:
    base = {"kind": kind, "purpose": kind, "outline": [], "centre": [0.0, 0.0], "width_mm": 0.0,
            "height_mm": 0.0, "cols": 1, "rows": 1, "thickness_mm": 0.0, "hole_mm": 0.0,
            "axis_deg": 0.0}  # fmt: skip
    return {**base, **kw}


LUG = _feat(
    "appendage",
    outline=[[-8.0, 38.0], [8.0, 38.0], [8.0, 60.0], [-8.0, 60.0]],
    centre=[0.0, 53.0],
    thickness_mm=4.0,
    hole_mm=5.0,
)
SURFACE = [
    _feat("panel_grid", centre=[0.0, -22.0], width_mm=36.0, height_mm=12.0, cols=3),
    _feat("lens", centre=[-24.0, 16.0], width_mm=10.0, height_mm=10.0, thickness_mm=3.0),
    _feat("recess", centre=[24.0, 16.0], width_mm=10.0, height_mm=8.0),
]


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    fx = FIXTURES["puck"]()
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("BARA_DATA_DIR", str(tmp_path_factory.mktemp("ff")))
        plain = enclose_report(fx["board"], [], brief_for(fx))
        brief = {**brief_for(fx), "shape_features": [LUG, *SURFACE]}
        shaped = enclose_report(fx["board"], [], brief)
        wedge = _feat("wedge", thickness_mm=20.0, axis_deg=90.0)
        wedged = enclose_report(fx["board"], [], {**brief_for(fx), "shape_features": [wedge]})
    return {"plain": plain, "shaped": shaped, "wedged": wedged}


def test_the_shaped_case_still_passes_every_check(built: dict[str, Any]) -> None:
    for name in ("shaped", "wedged"):
        rep = built[name]
        bad = [(c["rule_id"], c["message"]) for c in rep.checks if c["status"] != "pass"]
        assert not bad, name
        for piece in (rep.tray, rep.bezel):
            assert len(piece.decompose()) == 1


def test_an_appendage_reaches_past_the_rim_thin_and_with_its_hole(built: dict[str, Any]) -> None:
    plain, shaped = built["plain"], built["shaped"]
    p, s = (r.tray + r.bezel for r in (plain, shaped))
    (_, py0, _, _, py1, _), (_, sy0, _, _, sy1, _) = p.bounding_box(), s.bounding_box()
    assert (sy1 - sy0) - (py1 - py0) > 15.0  # the lug adds ~20 mm to the 84 mm body
    y_tip = sy0 if sy0 < py0 - 5 else sy1  # the board frame may mirror y
    probe = mf.Manifold.cube((10.0, 6.0, 200.0), True).translate((0.0, y_tip * 0.97, 0.0))
    _, _, lo, _, _, hi = (s ^ probe).bounding_box()
    assert hi - lo < 6.0  # a 4 mm plate, not the 34 mm body
    hole_y = -53.0 if y_tip < 0 else 53.0
    pin = mf.Manifold.cylinder(200.0, 1.5, 1.5, 24).translate((0.0, hole_y, -100.0))
    assert (s ^ pin).volume() < 1e-3


def test_surface_features_land_on_the_face(built: dict[str, Any]) -> None:
    shaped = built["shaped"]
    kinds = {c["feature"] for c in shaped.enclosure["cutouts"]}
    assert {"panel_grid", "lens", "recess"} <= kinds
    assert shaped.bezel.volume() < built["plain"].bezel.volume()  # grooves and a pocket cut


def test_a_wedge_deepens_one_end_and_keeps_the_face(built: dict[str, Any]) -> None:
    plain, wedged = built["plain"], built["wedged"]

    def depth_at(rep: Any, y: float) -> float:
        col = mf.Manifold.cube((4.0, 4.0, 200.0), True).translate((0.0, y, 0.0))
        _, _, lo, _, _, hi = ((rep.tray + rep.bezel) ^ col).bounding_box()
        return hi - lo

    a, b = depth_at(wedged, 30.0), depth_at(wedged, -30.0)
    # the parts set how thin the thin end can get; the thick end takes the form's full depth
    assert abs(a - b) > 3.0
    top = (wedged.tray + wedged.bezel).bounding_box()[5]
    assert top == pytest.approx((plain.tray + plain.bezel).bounding_box()[5], abs=1.5)


def test_the_form_rejects_features_it_cannot_build() -> None:
    sil = [(-30.0, -20.0), (30.0, -20.0), (30.0, 20.0), (-30.0, 20.0)]
    form = F.Form("box", sil, 12.0, 10.0, [], {}, "", features=[])
    form.features = [
        _feat("appendage", outline=[[60, 0], [70, 0], [70, 10]], thickness_mm=3.0),  # floating
        _feat("appendage", outline=[[-5, -5], [5, -5], [5, 5], [-5, 5]], thickness_mm=3.0),
        _feat("wedge", thickness_mm=15.0),
        _feat("lens", centre=[80.0, 0.0], width_mm=8.0, height_mm=8.0, thickness_mm=2.0),
    ]
    probs = F.feature_problems(form)
    assert any("touch the silhouette" in p for p in probs)
    assert any("outside the silhouette" in p for p in probs)
    assert any("thin edge" in p for p in probs)
    assert any("main face" in p for p in probs)
    form.features = [
        _feat("appendage", outline=[[-5, 20], [5, 20], [5, 40], [-5, 40]], thickness_mm=3.0),
        _feat("wedge", thickness_mm=6.0, axis_deg=90.0),
        _feat("panel_grid", centre=[0.0, 0.0], width_mm=40.0, height_mm=20.0, cols=4, rows=2),
    ]
    assert F.feature_problems(form) == []


def test_features_follow_the_form_when_it_is_scaled_and_centred() -> None:
    sil = [(0.0, 0.0), (60.0, 0.0), (60.0, 40.0), (0.0, 40.0)]
    form = F.Form("box", sil, 12.0, 10.0, [], {}, "")
    form.features = [_feat("recess", centre=[30.0, 20.0], width_mm=10.0, height_mm=6.0)]
    F.centre_on_origin(form)
    assert form.features[0]["centre"] == [0.0, 0.0]
    F.move_features(form, 2.0)
    assert form.features[0]["width_mm"] == 20.0


def test_the_schema_asks_for_features() -> None:
    sch = F.schema(["a"])
    assert "features" in sch["required"]
    kinds = sch["properties"]["features"]["items"]["properties"]["kind"]["enum"]
    assert kinds == F.FEATURE_KINDS
