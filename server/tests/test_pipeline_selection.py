"""The build path is chosen by what the product is, never by a keyboard-shaped brief field.

A brief that carries a key grid (layout_style, rows, cols, switch_family) for a product that is
not itself a keyboard must not run the keyboard pipeline or be given keyboard parts. Device
names here are placeholders; nothing in the engine knows them.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from bara.catalog import load_catalog
from bara.live import concept as concept_mod
from bara.live.brief import normalise_brief, rules_brief
from bara.live.layout import keyboard_product, plan_keyboard
from bara.router import Router

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(ROOT.parent / "spec", ROOT / "data" / "catalog")


def grid_brief(**kw: Any) -> dict[str, Any]:
    brief = {
        "summary": "A thing with a grid of keys and a screen.",
        "device": "gadget",
        "device_class": "handheld",
        "functions": ["compute.mcu", "input.key", "input.key_matrix", "mech.keycap"],
        "layout_style": "macropad",
        "key_count": 16,
        "rows": 4,
        "cols": 4,
        "thumb_keys": None,
        "stagger": "ortho",
        "switch_family": "mx",
        "features": [],
        "colours": [],
    }
    brief.update(kw)
    return brief


def concept(path: str) -> dict[str, Any]:
    return {
        "device_name": "test device",
        "build_path": path,
        "build_path_reason": "test",
        "device_class_hint": "handheld",
        "functions": ["input.button"],
    }


def test_key_grid_on_a_non_keyboard_runs_the_device_path(catalog) -> None:
    brief = normalise_brief(grid_brief(), catalog)
    assert not keyboard_product(brief)
    assert plan_keyboard(brief) is None
    assert brief["layout_style"] == "none"
    assert brief["switch_family"] is None
    assert brief["key_count"] is None and brief["rows"] is None
    assert "mech.keycap" not in brief["functions"]
    assert "input.key" not in brief["functions"]
    assert "input.button" in brief["functions"]


def test_concept_device_path_overrides_a_keyboard_class(catalog) -> None:
    brief = concept_mod.apply(grid_brief(device_class="input_device"), concept("device"))
    brief = normalise_brief(brief, catalog)
    assert plan_keyboard(brief) is None
    assert "mech.keycap" not in brief["functions"]


def test_concept_keyboard_path_runs_the_keyboard_pipeline(catalog) -> None:
    brief = concept_mod.apply(grid_brief(layout_style="none"), concept("keyboard"))
    brief = normalise_brief(brief, catalog)
    assert brief["device_class"] == "input_device"
    assert keyboard_product(brief)
    assert plan_keyboard(brief) is not None
    for fid in ("input.key", "mech.keycap", "compute.mcu"):
        assert fid in brief["functions"]


def test_without_a_concept_only_an_input_device_is_a_keyboard(catalog) -> None:
    kb = normalise_brief(grid_brief(device_class="input_device"), catalog)
    assert plan_keyboard(kb) is not None
    other = normalise_brief(grid_brief(device_class="display_device"), catalog)
    assert plan_keyboard(other) is None


def test_normalise_is_stable(catalog) -> None:
    once = normalise_brief(grid_brief(), catalog)
    assert normalise_brief(once, catalog) == once


def test_concept_text_carries_the_layout() -> None:
    c = {
        **concept("device"),
        "what_it_is": "w",
        "orientation": "portrait",
        "rest_pose": "handheld",
        "size_mm": {"width": [60, 80], "height": [100, 140], "thickness": [8, 14]},
        "layout": ["screen across the top", "button grid below"],
        "controls": [
            {
                "name": "buttons",
                "count": 12,
                "part_kind": "tactile switch",
                "size_mm": "6 x 6",
                "arrangement": "grid 4 x 3",
            }
        ],
        "identity_cues": ["slab"],
        "reference_parts": ["tactile switch"],
    }
    text = concept_mod.concept_text(c)
    assert "portrait" in text and "button grid below" in text and "grid 4 x 3" in text
    assert concept_mod.concept_text(None) == ""


def test_a_device_made_to_pair_is_read_from_its_own_words(catalog) -> None:
    router = Router(catalog, SimpleNamespace(data_dir=ROOT / "data"))  # type: ignore[arg-type]
    line = (
        "a mouse that pairs with the keyboard; case colours the same as the keyboard"
        " (body #1f2a44); Bluetooth like the keyboard."
    )
    brief = rules_brief(line, router, catalog)
    assert brief["layout_style"] == "none"
    assert "keyboard" not in brief["device"]
    assert brief["wireless"]  # the look and the radio still come from the whole line
    assert rules_brief("a split keyboard", router, catalog)["layout_style"] == "split"
