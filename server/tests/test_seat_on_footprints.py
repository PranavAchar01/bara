from bara.live.runner import _seat_on_footprints


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
    assert [m["instance_id"] for m in moved] == ["mcu"]
    pl = parts[0]["placement"]
    assert pl["position_mm"] == [10.0, 23.0, 6.6]
    assert pl["rotation_deg"] == [0.0, 0.0, 180.0]
