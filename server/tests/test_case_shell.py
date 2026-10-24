"""The sculpted shell: built from a ProductForm alone, one piece per part, parts seated inside,
openings at the anchors, smooth plan."""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np
import pytest
from shapely.geometry import Polygon

from bara.geometry import EncloseReport, enclose_report, shell
from bara.geometry.shell_fixtures import FIXTURES, brief_for

NAMES = ["gamepad", "phone", "puck", "watch", "flashlight"]


@pytest.fixture(scope="module")
def reports(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, EncloseReport]]:
    data = tmp_path_factory.mktemp("shelldata")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("BARA_DATA_DIR", str(data))
        yield {
            n: enclose_report(FIXTURES[n]()["board"], [], brief_for(FIXTURES[n]())) for n in NAMES
        }


@pytest.mark.parametrize("name", NAMES)
def test_every_check_passes(reports: dict[str, EncloseReport], name: str) -> None:
    bad = [(c["rule_id"], c["message"]) for c in reports[name].checks if c["status"] != "pass"]
    assert not bad


@pytest.mark.parametrize("name", NAMES)
def test_watertight_single_pieces(reports: dict[str, EncloseReport], name: str) -> None:
    for piece in (reports[name].tray, reports[name].bezel):
        assert piece.status().name == "NoError"
        assert len(piece.decompose()) == 1
        assert piece.volume() > 0


@pytest.mark.parametrize("name", NAMES)
def test_board_inside_the_case(reports: dict[str, EncloseReport], name: str) -> None:
    ids = {c["rule_id"] for c in reports[name].checks}
    assert {"mech.fit.enclosure", "mech.fit.floating"} <= ids


def test_openings_at_the_anchors(reports: dict[str, EncloseReport]) -> None:
    kinds = {c["feature"] for c in reports["gamepad"].enclosure["cutouts"]}
    assert {"dpad", "shoulder"} <= kinds
    assert any(k in kinds for k in ("stick_well", "stick", "knob_well", "button"))
    assert "screen_window" in {c["feature"] for c in reports["phone"].enclosure["cutouts"]}
    assert "usb_c" in {c["feature"] for c in reports["puck"].enclosure["cutouts"]}


def test_one_port_slot_per_port(reports: dict[str, EncloseReport]) -> None:
    usb = [c for c in reports["puck"].enclosure["cutouts"] if c["feature"] == "usb_c"]
    assert len(usb) == 1


def test_smooth_plan_contains_the_board_and_stays_simple() -> None:
    sq = Polygon([(0, 0), (60, 0), (60, 30), (0, 30)])
    need = sq.buffer(-3.0)
    plan = shell.smooth_plan(sq, 6.0, need)
    assert plan.is_valid and plan.contains(need)
    assert plan.area < sq.area  # corners rounded
    assert np.isfinite(plan.length)


def test_no_device_names_in_the_engine() -> None:
    import inspect
    import re

    src = inspect.getsource(shell)
    assert not re.search(r"xbox|dualshock|iphone|pixel|casio|maglite|airpods", src, re.I)


def test_a_tall_hidden_part_gets_a_pocket_not_a_hole(tmp_path, monkeypatch) -> None:
    """A part above the seat that nobody touches is pocketed from inside; the skin over it stays
    whole (holes punched for hidden parts left lattices and loose bars in the bezel)."""
    import copy

    import manifold3d as mf

    monkeypatch.setenv("BARA_DATA_DIR", str(tmp_path))
    fx = copy.deepcopy(FIXTURES["gamepad"]())
    fx["board"]["placements"].append(
        {
            "ref": "C99",
            "lib_id": "X:C99",
            "role": "capacitor",
            "x_mm": 0.0,
            "y_mm": 0.0,
            "rot_deg": 0,
            "side": "top",
            "height_mm": 4.0,
            "size_mm": [6.0, 6.0],
        }
    )
    rep = enclose_report(fx["board"], [], brief_for(fx))
    f = next(x for x in rep.features if x.ref == "C99")
    top = f.z_range(fx["board"].get("thickness_mm", 1.6))[1]
    column = mf.Manifold.cube((0.4, 0.4, 200.0), center=True).translate((f.x, f.y, top + 100.6))
    assert (rep.bezel ^ column).volume() > 0.16 * 1.0  # at least 1 mm of skin over the part
    assert len(rep.bezel.decompose()) == 1
    assert not [c["message"] for c in rep.checks if c["status"] != "pass"]
