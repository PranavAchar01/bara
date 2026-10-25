from __future__ import annotations

from bara.live import brief as brief_mod
from bara.live import finish


def _build() -> dict:
    return {
        "prompt": "a pocket game console with a screen and buttons",
        "slots": [
            {"slot_id": "btn", "function_id": "input.button"},
            {"slot_id": "lcd", "function_id": "display.tft"},
        ],
        "parts": [
            {"instance_id": "b1", "part_id": "x:sw", "slot_id": "btn", "quantity": 1,
             "card": {"display_name": "Tactile switch"}},
            {"instance_id": "d1", "part_id": "disp:tft", "slot_id": "lcd", "quantity": 1,
             "card": {"display_name": "TFT", "kind": "module"}},
        ],
        "boards": [],
        "enclosures": [{"enclosure_id": "case", "kind": "generated", "assets": []}],
        "scene": {"camera": {}},
    }  # fmt: skip


GB = {
    "body": "#CFCBC0", "trim": "#4A4D55", "buttons": "#23252A",
    "accent": "#A8325E", "screen": "#B7D39A",
}  # fmt: skip


def test_proposed_palette_dresses_the_shell() -> None:
    plan = finish.plan(_build(), None, GB)
    pal = plan["palette"]
    assert pal["body"] == "#CFCBC0" and pal["trim"] == "#4A4D55" and pal["screen"] == "#B7D39A"
    assert plan["parts"]["b1"]["color"] == "#23252A"  # first control group: buttons
    assert plan["parts"]["d1"]["color"] == "#B7D39A"  # screen glass takes the tint
    assert plan["case"]["color"] == "#CFCBC0"


def test_no_palette_falls_back_to_curated_one() -> None:
    pal = finish.plan(_build())["palette"]
    assert pal["body"].startswith("#") and pal["trim"] == pal["primary"]
    assert pal["screen"] == "#0B0E12"


def test_brief_palette_is_cleaned() -> None:
    schema = brief_mod.brief_schema(["input.button"], ["handheld"])
    assert "palette" in schema["required"]
    assert set(schema["properties"]["palette"]["required"]) == set(brief_mod.PALETTE_KEYS)
