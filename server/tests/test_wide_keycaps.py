"""Every key width on a row-staggered preset gets a keycap of its own size, with a model to draw."""

from pathlib import Path

import pytest

from bara.catalog import load_catalog
from bara.live.catalog_source import open_part_source
from bara.live.compose import Composer
from bara.live.layout import plan_keyboard

ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS = ["input.key", "mech.keycap", "mech.stabilizer"]


@pytest.fixture(scope="module")
def composer() -> Composer:
    catalog_dir = ROOT / "data" / "catalog"
    source = open_part_source(load_catalog(ROOT.parent / "spec", catalog_dir), catalog_dir)
    brief = {
        "layout_style": "unibody",
        "layout_preset": "ansi_60",
        "device": "keyboard",
        "functions": FUNCTIONS,
        "features": [],
    }
    spec = {"functions": [{"function_id": f, "required": True, "count": 1} for f in FUNCTIONS]}
    return Composer(source, spec, brief, plan_keyboard(brief), None)


@pytest.mark.parametrize("chosen", ["cap:dsa_1u_pbt", "cap:klp_mx_1u", "cap:dsa_1u_homing"])
def test_each_width_gets_its_own_sized_cap_with_a_model(composer: Composer, chosen: str) -> None:
    slot = next(s for s in composer.slots if s.slot_id == "keycaps")
    part = composer.source.get_part(chosen)
    widths = set()
    for inst in slot.instances:
        size = max(inst.key_widths or (1.0,))
        sized = composer.sized_part(slot, inst, part)
        assert float(sized["facets"]["key_units"]) == pytest.approx(size)
        built = composer.build_part(slot, inst, sized)
        assert built["placement"]["key_widths_u"] == list(inst.key_widths or ())
        assert any(a.get("url") and a.get("status") == "ready" for a in built["assets"])
        widths.add(size)
    assert {1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.75, 6.25} <= widths
