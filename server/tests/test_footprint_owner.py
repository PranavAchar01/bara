"""A board footprint names the build part it seats, so the viewer can hide that part's
standalone mesh (a display drawn twice covered the board)."""

from __future__ import annotations

from bara.board import _footprints


def test_footprint_carries_the_build_part() -> None:
    (fp,) = _footprints(
        [{"ref": "DS1", "instance_id": "board_top_ds1", "for_instance_id": "u_display",
          "x_mm": 0.0, "y_mm": 0.0, "size_mm": [61.0, 82.5]}]
    )  # fmt: skip
    assert fp["instance_id"] == "u_display"
