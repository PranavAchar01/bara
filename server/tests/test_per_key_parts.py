"""A split keyboard lists a matrix diode and a hot-swap socket for every key on each half."""

from pathlib import Path

import pytest

from bara.catalog import load_catalog
from bara.live.catalog_source import open_part_source
from bara.live.compose import Composer, _per_key
from bara.live.layout import plan_keyboard

ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS = ["input.key", "mech.keycap", "component.diode", "interconnect.connector", "compute.mcu"]


@pytest.fixture(scope="module")
def composer() -> Composer:
    catalog_dir = ROOT / "data" / "catalog"
    source = open_part_source(load_catalog(ROOT.parent / "spec", catalog_dir), catalog_dir)
    brief = {
        "layout_style": "split",
        "device": "keyboard",
        "switch_family": "choc",
        "wireless": "none",
        "functions": FUNCTIONS,
        "features": [],
    }
    spec = {"functions": [{"function_id": f, "required": True, "count": 1} for f in FUNCTIONS]}
    return Composer(source, spec, brief, plan_keyboard(brief), None)


def keys_by_side(composer: Composer) -> dict[str, int]:
    return {h.side: len(h.keys) for h in composer.plan.halves}


def test_one_diode_per_key_on_each_half(composer: Composer) -> None:
    diode = next(s for s in composer.slots if s.function_id == "component.diode")
    assert {i.side: i.quantity for i in diode.instances} == keys_by_side(composer)
    assert all(i.layout_id is None for i in diode.instances)


def test_a_hotswap_socket_per_key_costs_no_controller_pins(composer: Composer) -> None:
    conn = next(s for s in composer.slots if s.function_id == "interconnect.connector")
    before = composer.pin_need_for("left")
    conn.chosen = composer.source.get_part("hs:kailh_choc_socket")
    conn.instances = _per_key(conn.instances[0].instance_id, composer.plan)
    assert {i.side: i.quantity for i in conn.instances} == keys_by_side(composer)
    assert len({i.instance_id for i in conn.instances}) == len(conn.instances)
    assert composer.pin_need_for("left")[0] <= before[0]
