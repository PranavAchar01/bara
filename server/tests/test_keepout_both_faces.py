"""A footprint keep-out over both copper faces (an antenna clearance) is closed to parts on the
far side too: a display on the front over a back-mounted ESP32's antenna failed DRC."""

from __future__ import annotations

from pathlib import Path

from shapely.geometry import box

from bara.board.generic import _attempt
from bara.board.layout import Item
from bara.board.libs import FootprintInfo, Pad, load_footprint


def _fp(name: str, court: tuple[float, float, float, float], keep=None) -> FootprintInfo:
    return FootprintInfo(
        lib="t",
        lib_dir=Path("t.pretty"),
        name=name,
        pads=[Pad("1", "smd", 0.0, 0.0, 1.0, 1.0, ["F.Cu"])],
        courtyard=court,
        courtyard_back=None,
        models=[],
        keepouts=[keep] if keep else [],
    )


def test_the_esp32_antenna_keepout_is_read_from_the_library() -> None:
    fp = load_footprint("kicad", "RF_Module", "ESP32-WROOM-32E")
    assert fp.keepouts and box(*fp.courtyard).contains(box(-24, -27.75, 24, -6.56))


def test_no_part_on_the_far_face_lands_in_a_keepout() -> None:
    region = box(0, 0, 60, 60)
    antenna = [(-10.0, -15.0), (10.0, -15.0), (10.0, -5.0), (-10.0, -5.0)]
    module = Item(ref="U1", role="mcu", fp=_fp("mod", (-10, -15, 10, 10), antenna), x=0, y=0)
    module.side = "bottom"
    screen = Item(ref="DS1", role="screen", fp=_fp("scr", (-6, -6, 6, 6)), x=0, y=0)
    targets = {id(module): (30.0, 30.0), id(screen): (30.0, 20.0)}
    gaps = {id(module): 1.2, id(screen): 1.2}
    assert _attempt([module, screen], region, targets, gaps) is None
    assert screen.side == "top"
    keep = module.keepout_poly()
    assert keep is not None and keep.area > 0
    assert not screen.footprint_poly().intersects(keep)
