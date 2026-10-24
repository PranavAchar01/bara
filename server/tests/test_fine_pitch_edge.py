"""A fine-pitch part keeps a routing channel to the board edge, as it does to its neighbours."""

from __future__ import annotations

from pathlib import Path

from shapely.geometry import box

from bara.board.generic import EDGE_COPPER_MM, ESCAPE_MM, _attempt
from bara.board.layout import Item
from bara.board.libs import FootprintInfo, Pad


def _fp(name: str, pads: list[tuple[float, float]], w: float, h: float) -> FootprintInfo:
    return FootprintInfo(
        lib="t",
        lib_dir=Path("t.pretty"),
        name=name,
        pads=[Pad(str(i + 1), "smd", x, y, w, h, ["F.Cu"]) for i, (x, y) in enumerate(pads)],
        courtyard=(-1.6, -1.4, 1.6, 1.4),
        courtyard_back=None,
        models=[],
    )


def _edge_gap(it: Item, region) -> float:
    return region.exterior.distance(it.footprint_poly())


def test_a_fine_pitch_chip_leaves_its_pins_room_to_escape_at_the_edge() -> None:
    region = box(0, 0, 20, 20)
    lga = _fp(
        "lga14",
        [(-0.5 + 0.5 * i, 1.01) for i in range(3)]
        + [(-0.5 + 0.5 * i, -1.01) for i in range(3)]
        + [(-1.26, -0.75 + 0.5 * i) for i in range(4)]
        + [(1.26, -0.75 + 0.5 * i) for i in range(4)],
        0.28,
        0.28,
    )
    r0805 = _fp("r0805", [(-0.95, 0), (0.95, 0)], 1.0, 1.45)
    chip = Item(ref="U1", role="imu", fp=lga, x=0, y=0)
    res = Item(ref="R1", role="passive", fp=r0805, x=0, y=0)
    for it, want in ((chip, EDGE_COPPER_MM + ESCAPE_MM), (res, EDGE_COPPER_MM)):
        assert _attempt([it], region, {id(it): (0.0, 10.0)}, {id(it): 1.2}) is None
        assert _edge_gap(it, region) >= want - 0.05, (it.ref, _edge_gap(it, region))
    # the coarse part still uses the rim: only the fine-pitch one is held back
    assert _edge_gap(res, region) < EDGE_COPPER_MM + ESCAPE_MM - 0.1
