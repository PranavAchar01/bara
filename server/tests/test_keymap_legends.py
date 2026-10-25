"""Keycap legends follow a real keyboard: QWERTY rows on a one-piece board, split at T|Y."""

from __future__ import annotations

from bara.live.firmware import _keymap_rows
from bara.live.layout import PRESETS, Half, KeyboardPlan, _half_keys, preset_keys


def _codes(row: str) -> list[str]:
    return [b.removeprefix("&kp ") for b in row.split("  ")]


def _by_row(half: Half, codes: list[str], r: int) -> list[str]:
    keys = [
        (k["pos"][1], c)
        for k, c in zip(half.keys, codes, strict=True)
        if k["pos"][0] == r and not k.get("thumb")
    ]
    return [c for _, c in sorted(keys)]


def test_ansi_60_reads_as_qwerty() -> None:
    keys = preset_keys("ansi_60")
    half = Half(side="none", rows=len(PRESETS["ansi_60"]), cols=14, thumbs=0, keys=keys)
    codes = _codes(
        _keymap_rows(KeyboardPlan(style="unibody", halves=[half], key_count=len(keys)))[0]
    )
    assert _by_row(half, codes, 1)[:11] == "TAB Q W E R T Y U I O P".split()
    assert _by_row(half, codes, 2)[:10] == "CAPS A S D F G H J K L".split()
    assert "SPACE" in _by_row(half, codes, 4)
    assert len(set(codes)) == len(codes)


def test_split_halves_meet_at_t_and_y() -> None:
    halves = [
        Half(
            side=s,
            rows=3,
            cols=5,
            thumbs=3,
            keys=_half_keys(18, 3, 5, 3, True, mirror=s == "right"),
        )
        for s in ("left", "right")
    ]
    left, right = (
        _codes(r) for r in _keymap_rows(KeyboardPlan(style="split", halves=halves, key_count=36))
    )
    assert _by_row(halves[0], left, 0) == "Q W E R T".split()
    # the right half's column 0 is its outer edge, so reading by column runs P back to Y
    assert _by_row(halves[1], right, 0) == "P O I U Y".split()
    assert _by_row(halves[0], left, 1) == "A S D F G".split()
