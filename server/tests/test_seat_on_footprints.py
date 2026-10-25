import math

from bara.live.runner import _euler_xyz, _seat_on_footprints


def test_part_moves_onto_its_routed_footprint():
    board = {
        "position_mm": [10.0, 20.0, 5.0],
        "rotation_deg": [0.0, 0.0, 90.0],
        "thickness_mm": 1.6,
        "footprints": [
            {"ref": "U1", "instance_id": "mcu", "center_mm": [3.0, 0.0], "rot_deg": 90.0},
            {"ref": "D1", "instance_id": None, "center_mm": [1.0, 1.0]},
        ],
    }
    parts = [
        {"instance_id": "mcu", "quantity": 1, "placement": {"position_mm": [0, 0, 40]}},
        {"instance_id": "caps", "quantity": 4, "placement": {"position_mm": [0, 0, 0]}},
    ]
    moved = _seat_on_footprints(board, parts)
    assert moved[0]["instance_id"] == "mcu"
    pl = parts[0]["placement"]
    assert pl["position_mm"] == [10.0, 23.0, 6.6]
    assert pl["rotation_deg"] == [0.0, 0.0, 180.0]


def _board() -> dict:
    return {
        "side": "none",
        "position_mm": [30.0, -12.0, 5.0],
        "rotation_deg": [0.0, 0.0, 90.0],
        "thickness_mm": 1.6,
        "outline_mm": [[-20.0, -10.0], [20.0, -10.0], [20.0, 10.0], [-20.0, 10.0]],
        "footprints": [
            {"ref": "D1", "instance_id": "diode", "center_mm": [-10.0, 4.0]},
            {"ref": "D2", "instance_id": "diode", "center_mm": [10.0, 4.0]},
            {"ref": "U1", "instance_id": "mcu", "center_mm": [0.0, -3.0], "rot_deg": 0.0},
        ],
    }


def _world_bbox(board: dict) -> tuple[float, float, float, float]:
    rb = _euler_xyz(board["rotation_deg"])
    pts = [
        [board["position_mm"][i] + rb[i][0] * x + rb[i][1] * y for i in range(2)]
        for x, y in board["outline_mm"]
    ]
    return (
        min(p[0] for p in pts),
        min(p[1] for p in pts),
        max(p[0] for p in pts),
        max(p[1] for p in pts),
    )


def test_no_part_is_left_stranded_after_seating():
    """Compose leaves unplaced parts at exactly [0,0,0]; after the board is routed every
    part of the board sits inside its outline and none is at the origin by accident."""
    board = _board()
    origin = {"mode": "single", "position_mm": [0.0, 0.0, 0.0], "rotation_deg": [0, 0, 0]}
    parts = [
        {"instance_id": "mcu", "quantity": 1, "side": "none", "placement": dict(origin)},
        {"instance_id": "diode", "quantity": 1, "side": "none", "placement": dict(origin)},
        {"instance_id": "diodes2", "quantity": 4, "side": "none", "placement": dict(origin)},
        {"instance_id": "battery", "quantity": 1, "side": "none", "placement": dict(origin)},
        {"instance_id": "regulator", "quantity": 1, "side": "none", "placement": dict(origin)},
    ]
    moved = _seat_on_footprints(board, parts)
    assert {m["instance_id"] for m in moved} == {p["instance_id"] for p in parts}
    x0, y0, x1, y1 = _world_bbox(board)
    for part in parts:
        x, y, _ = part["placement"]["position_mm"]
        assert x0 <= x <= x1 and y0 <= y <= y1, (part["instance_id"], x, y)
        assert math.hypot(x, y) > 1.0, part["instance_id"]
    # the diode line has two footprints: it sits on their centroid, turned with the board
    diode = parts[1]["placement"]
    assert diode["position_mm"] == [30.0 - 4.0, -12.0, 6.6]
    assert diode["rotation_deg"] == [0.0, 0.0, 90.0]


def test_a_part_shared_by_two_boards_is_seated_once():
    left, right = _board(), {**_board(), "position_mm": [-60.0, 0.0, 5.0]}
    part = {
        "instance_id": "diode",
        "quantity": 1,
        "side": "none",
        "placement": {"mode": "single", "position_mm": [0.0, 0.0, 0.0]},
    }
    seen: set[str] = set()
    assert len(_seat_on_footprints(left, [part], seen)) == 1
    first = list(part["placement"]["position_mm"])
    assert _seat_on_footprints(right, [part], seen) == []
    assert part["placement"]["position_mm"] == first


def test_a_planned_part_keeps_its_pose_and_layout_parts_are_left_alone():
    board = _board()
    planned = {"instance_id": "bat", "quantity": 1, "placement": {"position_mm": [5.0, 6.0, 7.0]}}
    keys = {
        "instance_id": "sw",
        "quantity": 9,
        "placement": {"mode": "layout", "layout_id": "lay_main", "position_mm": [0, 0, 0]},
    }
    assert _seat_on_footprints(board, [planned, keys]) == []
    assert planned["placement"]["position_mm"] == [5.0, 6.0, 7.0]
