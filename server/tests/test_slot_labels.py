"""Slot headings in the Layers list name the part, not the block's whole explanation."""

import pytest

from bara.live.completeness import short_label


@pytest.mark.parametrize(
    ("label", "heading"),
    [
        ("PAW3212 optical mouse sensor with lens, ", "PAW3212 optical mouse sensor"),
        ("Main left/right click tactile switch 6x6", "Main left/right click tactile switch"),
        ("USB-C receptacle (power and USB 2.0 data", "USB-C receptacle"),
        ("3.3 V low-dropout, low-quiescent-current", "3.3 V low-dropout"),
        ("Battery power on/off slide switch (SPDT,", "Battery power on/off slide switch"),
        ("Controller", "Controller"),
    ],
)
def test_long_block_labels_become_short_headings(label, heading):
    assert short_label(label) == heading
