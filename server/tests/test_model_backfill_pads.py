"""A fetched model seats on a catalog footprint when the land patterns agree, even when the
two libraries draw the courtyard differently."""

from __future__ import annotations

from pathlib import Path

from catalog_build.kicad_lib import read_footprint
from catalog_build.model_backfill import same_pads


def _mod(tmp: Path, name: str, pads: list[tuple[str, float, float]], yard: float) -> Path:
    body = "".join(
        f'(pad "{n}" smd rect (at {x} {y}) (size 0.7 0.7) (layers "F.Cu"))\n' for n, x, y in pads
    )
    lines = "".join(
        f'(fp_line (start {a} {b}) (end {c} {d}) (layer "F.CrtYd"))\n'
        for a, b, c, d in [
            (-yard, -yard, yard, -yard),
            (yard, -yard, yard, yard),
            (yard, yard, -yard, yard),
            (-yard, yard, -yard, -yard),
        ]
    )
    path = tmp / f"{name}.kicad_mod"
    path.write_text(f'(footprint "{name}"\n{lines}{body})\n')
    return path


QUAD = [("1", -0.92, -0.55), ("2", -0.92, 0.55), ("3", 0.92, 0.55), ("4", 0.92, -0.55)]


def test_the_same_land_pattern_matches_whatever_the_courtyard(tmp_path: Path) -> None:
    kicad = read_footprint(_mod(tmp_path, "a", QUAD, 1.5))
    easyeda = read_footprint(_mod(tmp_path, "b", [(n, x + 0.005, y) for n, x, y in QUAD], 1.0))
    assert same_pads(kicad, easyeda)


def test_moved_or_renumbered_pads_do_not_match(tmp_path: Path) -> None:
    kicad = read_footprint(_mod(tmp_path, "a", QUAD, 1.5))
    wider = read_footprint(_mod(tmp_path, "b", [(n, x * 1.5, y) for n, x, y in QUAD], 1.5))
    fewer = read_footprint(_mod(tmp_path, "c", QUAD[:3], 1.5))
    assert not same_pads(kicad, wider) and not same_pads(kicad, fewer)
