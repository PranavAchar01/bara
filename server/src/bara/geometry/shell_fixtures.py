"""ProductForm fixtures for the sculpted shell: a silhouette, a thickness profile and anchors,
plus a board whose parts sit where the anchors say. No model call; these are test inputs and
the proof scripts' devices. Form coordinates are y-up; board coordinates are y-down.
"""

from __future__ import annotations

import math
from typing import Any


def rounded_rect(w: float, h: float, r: float, seg: int = 4) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for cx, cy, a0 in (
        (w / 2 - r, h / 2 - r, 0),
        (-w / 2 + r, h / 2 - r, 90),
        (-w / 2 + r, -h / 2 + r, 180),
        (w / 2 - r, -h / 2 + r, 270),
    ):
        for i in range(seg + 1):
            a = math.radians(a0 + 90 * i / seg)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def ellipse(rx: float, ry: float, n: int = 28) -> list[tuple[float, float]]:
    return [
        (rx * math.cos(2 * math.pi * i / n), ry * math.sin(2 * math.pi * i / n)) for i in range(n)
    ]


def anchor(
    name: str,
    purpose: str,
    centre: tuple[float, float],
    *,
    count: int = 1,
    pattern: str = "single",
    pitch: float = 0.0,
    mount: str = "front",
    normal: float = 0.0,
    slot: str | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "purpose": purpose,
        "slot_id": slot or name,
        "mount": mount,
        "pattern": pattern,
        "centre": [float(centre[0]), float(centre[1])],
        "pitch_mm": pitch,
        "count": count,
        "edge_normal_deg": normal,
    }


def part(
    ref: str,
    role: str,
    x: float,
    y: float,
    size: tuple[float, float],
    height: float,
    *,
    side: str = "top",
    touch: bool = False,
    rot: float = 0.0,
) -> dict[str, Any]:
    return {
        "ref": ref,
        "lib_id": f"fixture:{role}",
        "role": role,
        "x_mm": x,
        "y_mm": -y,  # form y-up -> board y-down
        "rot_deg": rot,
        "side": side,
        "height_mm": height,
        "size_mm": [size[0], size[1]],
        "touch": touch,
    }


def _board(parts: list[dict[str, Any]], form: dict[str, Any]) -> dict[str, Any]:
    """The board follows the silhouette inset by the case, exactly as the planner draws it."""
    from bara.board.generic import form_region

    region = form_region({"silhouette": form["silhouette"]}, 1.0)
    outline = [[round(x, 4), round(y, 4)] for x, y in list(region.exterior.coords)[:-1]]
    return {
        "board_id": "pcb_fixture",
        "outline": outline,
        "thickness_mm": 1.6,
        "position_mm": [0, 0, 0],
        "placements": parts,
        "cables": [],
    }


def gamepad() -> dict[str, Any]:
    half = [
        (0.0, 47.0), (30.0, 47.0), (50.0, 44.0), (63.0, 36.0), (71.0, 22.0), (76.0, 2.0),
        (79.0, -22.0), (77.0, -42.0), (68.0, -53.0), (55.0, -54.0), (46.0, -44.0),
        (38.0, -30.0), (26.0, -22.0), (12.0, -20.0), (0.0, -19.0),
    ]  # fmt: skip
    sil = [(x, y) for x, y in half] + [(-x, y) for x, y in reversed(half)][1:-1]
    sil = ccw(sil)
    anchors = [
        anchor("left thumbstick", "thumbstick, left thumb", (-38, 12), slot="stick_l"),
        anchor("right thumbstick", "thumbstick, right thumb", (24, -8), slot="stick_r"),
        anchor("d-pad", "directional pad", (-20, -8), slot="dpad"),
        anchor(
            "face buttons",
            "four action buttons",
            (42, 14),
            count=4,
            pattern="diamond",
            pitch=8.5,
            slot="face",
        ),  # fmt: skip
        anchor(
            "left shoulder", "left shoulder bumper", (-44, 38), mount="edge", normal=90, slot="lb"
        ),  # fmt: skip
        anchor(
            "right shoulder", "right shoulder bumper", (44, 38), mount="edge", normal=90, slot="rb"
        ),  # fmt: skip
        anchor("usb port", "usb-c charging port", (0, 46), mount="edge", normal=90, slot="usb"),
    ]
    parts = [
        part("SL", "other", -38, 12, (17, 17), 12, touch=True),
        part("SR", "other", 24, -8, (17, 17), 12, touch=True),
        part("DP", "other", -20, -8, (14, 14), 5, touch=True),
        part("B1", "switch", 42, 22.5, (7, 7), 3.5, touch=True),
        part("B2", "switch", 50.5, 14, (7, 7), 3.5, touch=True),
        part("B3", "switch", 42, 5.5, (7, 7), 3.5, touch=True),
        part("B4", "switch", 33.5, 14, (7, 7), 3.5, touch=True),
        part("LB", "switch", -44, 33, (10, 5), 4, touch=True),
        part("RB", "switch", 44, 33, (10, 5), 4, touch=True),
        part("U1", "mcu", 0, 14, (24, 16), 3.5),
        part("J1", "usb", 0, 40, (9, 7.5), 3.3),
        part("BT1", "battery", 0, 0, (40, 24), 8, side="bottom"),
    ]
    return {
        "name": "gamepad",
        "form": {
            "device_class": "handheld game controller",
            "silhouette": sil,
            "thickness_mm": 36.0,
            "edge_thickness_mm": 16.0,
            "anchors": anchors,
        },
        "board": parts,
    }


def phone() -> dict[str, Any]:
    sil = rounded_rect(72.0, 150.0, 11.0, 6)
    anchors = [
        anchor("screen", "touch display filling the face", (0, 0), slot="screen"),
        anchor("usb port", "usb-c charging port", (0, -74), mount="edge", normal=270, slot="usb"),
        anchor("power button", "side power button", (36, 22), mount="edge", normal=0, slot="pwr"),
    ]
    parts = [
        part("D1", "screen", 0, 4, (58, 132), 2.0, touch=True),
        part("U1", "mcu", 0, 40, (30, 22), 2.0, side="bottom"),
        part("J1", "usb", 0, -68, (9, 7.5), 3.3),
        part("SW1", "switch", 30.6, 22, (2, 8), 3.0, touch=True),
        part("BT1", "battery", 0, -10, (50, 70), 4.5, side="bottom"),
    ]
    return {
        "name": "phone",
        "form": {
            "device_class": "smartphone",
            "silhouette": sil,
            "thickness_mm": 9.5,
            "edge_thickness_mm": 8.0,
            "anchors": anchors,
        },
        "board": parts,
    }


def puck() -> dict[str, Any]:
    sil = ellipse(42.0, 42.0, 40)
    anchors = [
        anchor(
            "volume ring",
            "three round control buttons",
            (0, 4),
            count=3,
            pattern="ring",
            pitch=19,
            slot="ctl",
        ),  # fmt: skip
        anchor("usb port", "usb-c charging port", (0, -41), mount="edge", normal=270, slot="usb"),
    ]
    parts = [
        part("S1", "switch", 0, 14.0, (9, 9), 3.0, touch=True),
        part("S2", "switch", -12.2, -7.0, (9, 9), 3.0, touch=True),
        part("S3", "switch", 12.2, -7.0, (9, 9), 3.0, touch=True),
        part("U1", "mcu", 0, 3, (14, 10), 2.5),
        part("J1", "usb", 0, -34, (9, 7.5), 3.3),
        part("SP1", "other", 0, 0, (48, 48), 14, side="bottom"),
    ]
    return {
        "name": "speaker",
        "form": {
            "device_class": "portable speaker",
            "silhouette": sil,
            "thickness_mm": 34.0,
            "edge_thickness_mm": 24.0,
            "anchors": anchors,
        },
        "board": parts,
    }


def watch() -> dict[str, Any]:
    body = ellipse(21.0, 21.0, 36)
    lugs = rounded_rect(20.0, 52.0, 4.0, 3)
    from shapely.geometry import Polygon

    sil = list(Polygon(body).union(Polygon(lugs)).exterior.coords)[:-1]
    anchors = [
        anchor("round display", "round amoled display", (0, 0), slot="screen"),
        anchor("side button", "side button", (20, 6), mount="edge", normal=0, slot="btn"),
    ]
    parts = [
        part("D1", "screen", 0, 0, (24, 24), 1.5, touch=True),
        part("U1", "mcu", 0, 5, (14, 10), 1.5, side="bottom"),
        part("SW1", "switch", 14.0, 6, (4, 6), 2.5, touch=True),
        part("BT1", "battery", 0, -8, (24, 12), 3.5, side="bottom"),
    ]
    return {
        "name": "watch",
        "form": {
            "device_class": "smartwatch",
            "silhouette": [(float(x), float(y)) for x, y in sil],
            "thickness_mm": 11.5,
            "edge_thickness_mm": 8.0,
            "anchors": anchors,
        },
        "board": parts,
    }


def flashlight() -> dict[str, Any]:
    profile = [
        (-79.0, 9.0), (-76.0, 13.0), (-60.0, 14.5), (44.0, 14.5), (52.0, 15.0), (58.0, 19.5),
        (74.0, 19.5), (79.0, 16.0),
    ]  # fmt: skip
    sil = [(x, w) for x, w in profile] + [(x, -w) for x, w in reversed(profile)]
    sil = ccw(sil)
    anchors = [
        anchor("power switch", "main push button", (22, 0), slot="pwr"),
        anchor("usb port", "usb-c charging port", (-79, 0), mount="edge", normal=180, slot="usb"),
    ]
    parts = [
        part("SW1", "switch", 22, 0, (12, 12), 3.0, touch=True),
        part("U1", "mcu", -10, 0, (22, 12), 2.5),
        part("J1", "usb", -70, 0, (9, 7.5), 3.3),
        part("BT1", "battery", -20, 0, (65, 18), 18.0, side="bottom"),
    ]
    return {
        "name": "flashlight",
        "form": {
            "device_class": "handheld flashlight",
            "silhouette": sil,
            "thickness_mm": 36.0,
            "edge_thickness_mm": 30.0,
            "anchors": anchors,
        },
        "board": parts,
    }


def ccw(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    a = sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1], strict=True))
    return pts if a > 0 else list(reversed(pts))


_RAW = {f.__name__: f for f in (gamepad, phone, puck, watch, flashlight)}


def build(name: str) -> dict[str, Any]:
    fx = _RAW[name]()
    fx["board"] = _board(fx["board"], fx["form"])
    return fx


FIXTURES = {name: (lambda n=name: build(n)) for name in _RAW}


def brief_for(fx: dict[str, Any]) -> dict[str, Any]:
    form = fx["form"]
    return {
        "layout": form["device_class"],
        "colors": {},
        "features": [],
        "body_thickness_mm": form["thickness_mm"],
        "edge_thickness_mm": form["edge_thickness_mm"],
        "anchors": form["anchors"],
    }
