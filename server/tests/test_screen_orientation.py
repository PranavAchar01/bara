"""A screen lies along the product's long side, whichever way its footprint was drawn."""

from __future__ import annotations

from pathlib import Path

import pytest
from shapely.geometry import box

from bara.board.generic import _extent, _screen_along
from bara.board.layout import Item
from bara.board.libs import FootprintInfo, Pad


def _fp(w: float, h: float) -> FootprintInfo:
    return FootprintInfo(
        lib="t",
        lib_dir=Path("t.pretty"),
        name="panel",
        pads=[Pad("1", "thru_hole", 0, -h / 2 + 2, 1.5, 1.5, ["F.Cu", "B.Cu"])],
        courtyard=(-w / 2, -h / 2, w / 2, h / 2),
        courtyard_back=None,
        models=[],
    )


@pytest.mark.parametrize(
    ("region", "landscape"), [(box(0, 0, 200, 120), True), (box(0, 0, 70, 140), False)]
)
def test_a_portrait_drawn_panel_follows_the_body(region, landscape: bool) -> None:
    for w, h in ((71.5, 107.3), (107.3, 71.5)):
        it = Item(ref="DS1", role="screen", fp=_fp(w, h), x=0, y=0)
        _screen_along(it, region)
        ew, eh = _extent(it)
        assert (ew > eh) == landscape, (w, h, it.rot)


def test_small_or_square_parts_keep_their_turn() -> None:
    region = box(0, 0, 200, 120)
    for role, (w, h) in (("screen", (3.2, 1.6)), ("screen", (30, 30)), ("button", (8, 40))):
        it = Item(ref="X", role=role, fp=_fp(w, h), x=0, y=0)
        _screen_along(it, region)
        assert it.rot == 0.0
