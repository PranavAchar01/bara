"""Synthetic board records in the BOARD agent's shape, for tests and as a stand-in until a
real KiCad board arrives. Sizes are the published footprint/body sizes of the named KiCad
parts; positions are a plain grid. These are test inputs, not part records.
"""

from __future__ import annotations

import math
from typing import Any

import manifold3d as mf
import numpy as np

CHOC_PITCH = (18.0, 17.0)


def _outline_around(
    rects: list[tuple[float, float, float, float, float]],
    margin: float,
    circles: list[tuple[float, float, float]] = (),
) -> list[list[float]]:
    shapes = []
    for x, y, w, d, rot in rects:
        a = math.radians(rot)
        r = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
        pts = np.array([[-w / 2, -d / 2], [w / 2, -d / 2], [w / 2, d / 2], [-w / 2, d / 2]])
        shapes.append(mf.CrossSection([(pts @ r.T + [x, y]).tolist()]))
    for x, y, rad in circles:
        shapes.append(mf.CrossSection.circle(rad, 48).translate((x, y)))
    cs = mf.CrossSection.batch_boolean(shapes, mf.OpType.Add).offset(margin, mf.JoinType.Round)
    polys = cs.offset(-0.01, mf.JoinType.Miter).to_polygons()
    biggest = max(polys, key=lambda p: abs(_area(np.asarray(p))))
    return [[round(float(x), 4), round(float(y), 4)] for x, y in biggest]


def _area(p: np.ndarray) -> float:
    return 0.5 * float(np.sum(p[:, 0] * np.roll(p[:, 1], -1) - np.roll(p[:, 0], -1) * p[:, 1]))


def _circle(x: float, y: float, r: float, n: int = 48) -> list[list[float]]:
    return [
        [x + r * math.cos(2 * math.pi * i / n), y + r * math.sin(2 * math.pi * i / n)]
        for i in range(n)
    ]


def _key(ref: str, x: float, y: float, rot: float = 0.0) -> list[dict[str, Any]]:
    return [
        {
            "ref": ref,
            "lib_id": "PCM_Switch_Keyboard_Kailh:SW_Kailh_Choc_V1",
            "role": "switch",
            "x_mm": x,
            "y_mm": y,
            "rot_deg": rot,
            "side": "top",
            "height_mm": 8.0,
            "size_mm": [15.0, 15.0],
        },
        {
            "ref": f"{ref}_CAP",
            "lib_id": "keycap:klp_choc_1u",
            "role": "keycap",
            "x_mm": x,
            "y_mm": y,
            "rot_deg": rot,
            "side": "top",
            "height_mm": 11.3,
            "size_mm": [17.5, 16.5],
        },
        {
            "ref": f"{ref}_HS",
            "lib_id": "PCM_Switch_Keyboard_Kailh:Kailh_Socket_Choc",
            "role": "other",
            "x_mm": x,
            "y_mm": y - 4.0,
            "rot_deg": rot,
            "side": "bottom",
            "height_mm": 1.8,
            "size_mm": [9.0, 4.6],
        },
    ]


def macropad_board() -> tuple[dict[str, Any], dict[str, Any]]:
    """5x4 Choc macropad with an EC11 encoder, a 0.91 in OLED and a XIAO, white case."""
    px, py = CHOC_PITCH
    places: list[dict[str, Any]] = []
    rects = []
    for r in range(4):
        for c in range(5):
            x, y = c * px, -r * py
            places += _key(f"SW{r * 5 + c + 1}", x, y)
            rects.append((x, y, px, py, 0.0))
    top_y = py * 1.25
    places.append(
        {
            "ref": "ENC1",
            "lib_id": "Rotary_Encoder:RotaryEncoder_Alps_EC11E-Switch_Vertical_H20mm",
            "role": "encoder",
            "x_mm": 0.0,
            "y_mm": top_y,
            "rot_deg": 0,
            "side": "top",
            "height_mm": 20.0,
            "size_mm": [12.0, 13.0],
        }
    )
    places.append(
        {
            "ref": "DISP1",
            "lib_id": "Display:Adafruit_SSD1306_No_Mounting_Holes",
            "role": "screen",
            "x_mm": 1.5 * px,
            "y_mm": top_y,
            "rot_deg": 0,
            "side": "top",
            "height_mm": 4.0,
            "size_mm": [30.0, 11.5],
        }
    )
    places.append(
        {
            "ref": "U1",
            "lib_id": "Module:Seeed_Studio_XIAO_Series",
            "role": "mcu",
            "x_mm": 3.5 * px,
            "y_mm": top_y + 2.0,
            "rot_deg": 0,
            "side": "top",
            "height_mm": 3.5,
            "size_mm": [17.8, 21.0],
        }
    )
    places.append(
        {
            "ref": "J1",
            "lib_id": "Module:Seeed_Studio_XIAO_Series:USB",
            "role": "usb",
            "x_mm": 3.5 * px,
            "y_mm": top_y + 11.0,
            "rot_deg": 0,
            "side": "top",
            "height_mm": 3.3,
            "size_mm": [9.0, 7.5],
        }
    )
    places.append(
        {
            "ref": "BT1",
            "lib_id": "Battery:LiPo_401230",
            "role": "battery",
            "x_mm": 2.5 * px,
            "y_mm": top_y + 3.0,
            "rot_deg": 90,
            "side": "bottom",
            "height_mm": 3.8,
            "size_mm": [19.8, 26.0],
        }
    )
    rects.append((1.75 * px, top_y + 2.0, 4.6 * px, 26.0, 0.0))
    board = {
        "board_id": "pcb_macropad",
        "outline": _outline_around(rects, 1.0),
        "thickness_mm": 1.6,
        "position_mm": [0, 0, 0],
        "placements": places,
        "cables": [],
    }
    brief = {
        "layout": "macropad",
        "colors": {"case": "#F2F2EE", "keycaps": "#FFFFFF"},
        "features": ["knob", "screen"],
    }
    return board, brief


def split_right_board() -> tuple[dict[str, Any], dict[str, Any]]:
    """Right half: 3x5 column-staggered Choc keys, 3 thumb keys, 34 mm trackball, tented."""
    px, py = CHOC_PITCH
    stagger = [0.0, 4.0, 7.0, 4.0, 2.0]
    places: list[dict[str, Any]] = []
    rects = []
    x0 = 80.0
    n = 1
    for c in range(5):
        for r in range(3):
            x, y = x0 + c * px, -r * py + stagger[c]
            places += _key(f"SW{n}", x, y)
            rects.append((x, y, px, py, 0.0))
            n += 1
    for i, (dx, rot) in enumerate(((0.0, 0.0), (px + 1.0, -8.0), (2 * px + 4.0, -16.0))):
        x, y = x0 + dx - 4.0, -3 * py - 4.0 - i * 2.0
        places += _key(f"SW{n}", x, y, rot)
        rects.append((x, y, px, py, rot))
        n += 1
    bx, by, br = x0 - 30.0, -2.4 * py, 17.0
    places.append(
        {
            "ref": "BALL1",
            "lib_id": "trackball:34mm_ball",
            "role": "trackball",
            "x_mm": bx,
            "y_mm": by,
            "rot_deg": 0,
            "side": "top",
            "height_mm": 22.0,
            "size_mm": [2 * br, 2 * br],
        }
    )
    places.append(
        {
            "ref": "U2",
            "lib_id": "Sensor_Motion:PMW3360",
            "role": "sensor",
            "x_mm": bx,
            "y_mm": by,
            "rot_deg": 0,
            "side": "bottom",
            "height_mm": 6.0,
            "size_mm": [16.0, 16.0],
        }
    )
    places.append(
        {
            "ref": "U1",
            "lib_id": "Module:nice_nano",
            "role": "mcu",
            "x_mm": x0 + 5 * px + 2.0,
            "y_mm": stagger[4] + py * 0.9,
            "rot_deg": 0,
            "side": "top",
            "height_mm": 3.5,
            "size_mm": [18.0, 33.0],
        }
    )
    places.append(
        {
            "ref": "BT1",
            "lib_id": "Battery:LiPo_401230",
            "role": "battery",
            "x_mm": x0 + 5 * px + 2.0,
            "y_mm": stagger[4] + py * 0.9 + 1.0,
            "rot_deg": 0,
            "side": "bottom",
            "height_mm": 3.8,
            "size_mm": [19.8, 26.0],
        }
    )
    places.append(
        {
            "ref": "J2",
            "lib_id": "Connector_JST:JST_SH_SM06B-SRSS-TB_1x06-1MP_P1.00mm_Horizontal",
            "role": "other",
            "x_mm": bx + br + 6.0,
            "y_mm": by - 6.0,
            "rot_deg": 90,
            "side": "bottom",
            "height_mm": 2.9,
            "size_mm": [8.0, 4.25],
        }
    )
    rects.append((x0 + 5 * px + 2.0, stagger[4] + py * 0.9, 24.0, 35.0, 0.0))
    board = {
        "board_id": "pcb_right",
        "side": "right",
        "outline": _outline_around(rects, 1.0, [(bx, by, br + 4.0)]),
        "holes": [_circle(bx, by, br + 2.6)],
        "thickness_mm": 1.6,
        "position_mm": [0, 0, 0],
        "placements": places,
        "cables": [{"from_ref": "U2", "to_ref": "J2", "length_mm": 100.0}],
    }
    brief = {
        "layout": "split",
        "split": True,
        "tenting": True,
        "colors": {"case": "#8FA67A", "keycaps": "#F3EBD3"},
        "features": ["trackball", "tenting"],
    }
    return board, brief
