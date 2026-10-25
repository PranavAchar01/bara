"""A mouse's controls sit where a hand finds them: the two clicks side by side at the front with
the wheel between them, the thumb buttons one behind the other on the thumb's wall, the optical
sensor at the centre of the underside, and no two caps share area."""

from __future__ import annotations

import math

from shapely.geometry import Polygon

from bara.live import form as F


def _anchor(name, slot, centre, count=1, mount="front", pattern="single", pitch=0.0, normal=0.0):
    return {
        "name": name,
        "slot_id": slot,
        "purpose": name,
        "mount": mount,
        "pattern": pattern,
        "centre": list(centre),
        "pitch_mm": pitch,
        "cols": 1,
        "count": count,
        "edge_normal_deg": normal,
    }


TOUCHES = [
    F.Touch("clicks", "Click", "input.button", 2, size_mm=(6, 6)),
    F.Touch("enc", "Scroll", "input.rotary_encoder", 1, size_mm=(12, 13.6)),
    F.Touch("wheel", "Wheel", "mech.wheel", 1, size_mm=(7, 20)),
    F.Touch("thumb", "Thumb", "input.button", 2, size_mm=(6, 6)),
    F.Touch("opt", "Sensor", "sense.camera", 1, size_mm=(11, 16)),
    F.Touch("usb", "USB", "power.usb_in", 1, size_mm=(9, 7)),
]


def _mouse(turn: float = 0.0, messy=((-30, 0), (-25, 10), (-20, 10), (-30, -30))) -> F.Form:
    ring = []
    for t in range(24):
        a = t / 24 * 2 * math.pi
        ring.append((40 * math.cos(a) * (0.8 + 0.2 * math.sin(a)), 60 * math.sin(a)))
    rot = math.radians(turn)

    def turned(p):
        return (
            p[0] * math.cos(rot) - p[1] * math.sin(rot),
            p[0] * math.sin(rot) + p[1] * math.cos(rot),
        )

    c, e, w, th = (turned(p) for p in messy)
    anchors = [
        _anchor("Left and right click switches", "clicks", c, 2, pattern="row", pitch=8),
        _anchor("Scroll encoder", "enc", e),
        _anchor("Scroll wheel", "wheel", w),
        _anchor("Thumb back and forward buttons", "thumb", th, 2, pattern="column", pitch=8),
        _anchor("Optical sensor", "opt", turned((20, -40)), mount="back"),
        _anchor("USB-C", "usb", turned((0, -58)), mount="edge", normal=270),
    ]
    return F.Form(
        "computer mouse", [turned(p) for p in ring], 38.0, 18.0, anchors,
        {"width_mm": 80, "height_mm": 120, "thickness_mm": 38}, "",
    )  # fmt: skip


def _by_name(form: F.Form) -> dict[str, dict]:
    return {a["name"]: a for a in form.anchors}


def _arranged(form: F.Form) -> tuple[dict[str, dict], Polygon]:
    F.arrange_pointer(form, TOUCHES)
    F.separate(form, TOUCHES)
    return _by_name(form), Polygon(form.silhouette)


def test_clicks_sit_side_by_side_at_the_front_with_the_wheel_between() -> None:
    form = _mouse()
    anchors, poly = _arranged(form)
    left = anchors["Left and right click switches"]
    right = anchors["Left and right click switches (second)"]
    wheel = anchors["Scroll wheel"]
    assert math.isclose(left["centre"][1], right["centre"][1], abs_tol=0.1)
    assert left["centre"][0] < wheel["centre"][0] < right["centre"][0]
    assert math.isclose(wheel["centre"][1], left["centre"][1], abs_tol=0.1)
    assert left["centre"][1] > poly.centroid.y + 0.15 * (poly.bounds[3] - poly.bounds[1])
    assert wheel["centre"] == anchors["Scroll encoder"]["centre"]  # the encoder under the wheel
    assert F.pointer_overlaps(form, TOUCHES) == []
    assert F.face_overlaps(form, TOUCHES) == []


def test_thumb_buttons_share_one_side_wall_one_behind_the_other() -> None:
    form = _mouse()
    anchors, poly = _arranged(form)
    thumb = anchors["Thumb back and forward buttons"]
    assert thumb["mount"] == "edge" and thumb["pattern"] == "column"
    x, y = thumb["centre"]
    assert x < 0 and abs(thumb["edge_normal_deg"] - 180) < 25  # the left wall, facing out
    assert poly.exterior.distance(F.Point(x, y)) < 2.0
    assert thumb["pitch_mm"] >= 12.0  # one in front of the other, clear of each other
    assert y < anchors["Left and right click switches"]["centre"][1]  # behind the clicks


def test_the_optical_sensor_looks_through_the_middle_of_the_floor() -> None:
    form = _mouse()
    anchors, poly = _arranged(form)
    sensor = anchors["Optical sensor"]
    assert sensor["mount"] == "back"
    assert math.dist(sensor["centre"], (poly.centroid.x, poly.centroid.y)) < 1.0


def test_other_anchors_stay_where_the_model_put_them() -> None:
    form = _mouse()
    anchors, _ = _arranged(form)
    assert anchors["USB-C"]["centre"] == [0, -58] and anchors["USB-C"]["mount"] == "edge"


def test_a_mouse_drawn_sideways_is_arranged_the_same_way() -> None:
    form = _mouse(turn=-90.0)  # front toward +x
    anchors, poly = _arranged(form)
    left = anchors["Left and right click switches"]
    right = anchors["Left and right click switches (second)"]
    wheel = anchors["Scroll wheel"]
    assert math.isclose(left["centre"][0], right["centre"][0], abs_tol=0.1)
    assert math.isclose(wheel["centre"][0], left["centre"][0], abs_tol=0.1)
    assert (
        sorted([left["centre"][1], wheel["centre"][1], right["centre"][1]])[1] == wheel["centre"][1]
    )
    assert left["centre"][0] > poly.centroid.x + 15
    assert F.pointer_overlaps(form, TOUCHES) == []


def test_a_form_that_is_not_a_pointer_is_left_alone() -> None:
    form = _mouse()
    form.device_class = "handheld game console"
    before = [list(a["centre"]) for a in form.anchors]
    F.arrange_pointer(form, TOUCHES)
    assert [a["centre"] for a in form.anchors] == before
