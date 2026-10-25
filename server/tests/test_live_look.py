"""Finishing pass, identity repair stop, hero camera orientation and the shopping BOM."""

from __future__ import annotations

import csv
import io

import numpy as np

from bara import bom
from bara.live import finish, hero, identity


def _build() -> dict:
    return {
        "build_id": "b_test",
        "prompt": "a pocket weather station with a screen and two buttons",
        "slots": [
            {"slot_id": "btn", "function_id": "input.button"},
            {"slot_id": "lcd", "function_id": "display.tft"},
            {"slot_id": "mcu", "function_id": "compute.mcu"},
        ],
        "parts": [
            {"instance_id": "b1", "part_id": "lcsc:tact_sw_c318884", "slot_id": "btn",
             "quantity": 1, "card": {"display_name": "Tactile switch"}},
            {"instance_id": "b2", "part_id": "lcsc:tact_sw_c318884", "slot_id": "btn",
             "quantity": 1, "card": {"display_name": "Tactile switch"}},
            {"instance_id": "d1", "part_id": "disp:tft24", "slot_id": "lcd", "quantity": 1,
             "card": {"display_name": "2.4 in TFT", "kind": "module"}},
            {"instance_id": "m1", "part_id": "mcu:board", "slot_id": "mcu", "quantity": 1,
             "card": {"display_name": "MCU board", "kind": "module"}},
        ],
        "boards": [
            {"board_id": "main", "source": "generated", "size_mm": [60, 90], "layers": 2,
             "footprints": [
                 {"ref": "SW1", "instance_id": "b1", "lib_id": "Button:SW"},
                 {"ref": "R1", "lib_id": "Resistor_SMD:R_0805_2012Metric", "label": "10k"},
                 {"ref": "R2", "lib_id": "Resistor_SMD:R_0805_2012Metric", "label": "10k"},
             ]},
        ],
        "enclosures": [
            {"enclosure_id": "case", "kind": "generated", "color_source": None,
             "assets": [{"kind": "glb", "url": "/assets/x.glb",
                         "nodes": ["case_tray", "case_bezel", "case_caps", "case_glass"]}]},
        ],
        "scene": {"camera": {}},
    }  # fmt: skip


def test_finish_case_is_clear_and_parts_stay_opaque() -> None:
    b = _build()
    plan = finish.plan(b)
    case = plan["case"]
    assert case["role"] == "case" and case["opacity"] < 0.5 and case["transmission"] > 0.5
    assert plan["parts"]["d1"]["role"] == "display" and plan["parts"]["d1"]["emissive"]
    assert plan["parts"]["b1"]["role"] == "control" and plan["parts"]["b1"]["opacity"] == 1.0
    assert plan["parts"]["b1"] == plan["parts"]["b2"]  # one slot, one colour
    assert plan["parts"]["m1"]["color"] in (finish.PCB_GREEN, finish.PCB_BLACK)
    nodes = plan["enclosures"]["case"][1]
    assert nodes["case_glass"]["role"] == "display" and nodes["case_caps"]["role"] == "control"
    assert nodes["case_tray"] == case
    types = [t for t, _ in finish.events(b)]
    assert types.count("part.updated") == 4 and "enclosure.updated" in types
    assert types[-1] == "scene.ready"


def test_case_tints_read_as_coloured_plastic() -> None:
    for pal in finish.PALETTES:
        rgb = [int(pal["tint"][i : i + 2], 16) for i in (1, 3, 5)]
        assert max(rgb) - min(rgb) >= 20 or pal["name"] == "smoke"  # a real tint
        assert max(rgb) < 245  # never a near-white that vanishes when see-through


def test_user_colour_wins() -> None:
    pal = finish.palette_for("x", [{"target": "case", "hex": "#123456"}])
    assert pal["tint"] == "#123456"


def test_same_objection_stops_a_repeat() -> None:
    a = {"mismatches": ["landscape thick slab, beige"], "form_fixes": ["make it portrait"]}
    b = {"mismatches": ["thick landscape slab"], "form_fixes": ["make it portrait, beige"]}
    c = {"mismatches": ["the buttons sit too close to the edge"], "form_fixes": ["inset them"]}
    assert identity.same_objection(a, b)
    assert not identity.same_objection(a, c)


def test_hero_camera_keeps_a_portrait_plan_portrait() -> None:
    w, d, t = 90.0, 148.0, 20.0
    corners = np.array([[x, y, z] for x in (0, w) for y in (0, d) for z in (0, t)])
    mesh = (corners, np.zeros((0, 3), dtype=np.int64), (0.5, 0.5, 0.5))
    eye, target = hero.hero_camera([mesh])
    fwd = np.subtract(target, eye)
    fwd /= np.linalg.norm(fwd)
    right = np.cross(fwd, [0, 0, 1.0])
    right /= np.linalg.norm(right)
    up = np.cross(right, fwd)
    top = corners[corners[:, 2] == t] - np.array(eye)
    xs, ys = top @ right, top @ up
    assert (ys.max() - ys.min()) > (xs.max() - xs.min())


def test_bom_rows_links_and_case_file() -> None:
    def lookup(pid: str) -> dict | None:
        if pid == "lcsc:tact_sw_c318884":
            return {"mpn": "TS-1187A", "manufacturer": "XKB Connection(中国)",
                    "provenance": {"lcsc_id": "C318884"}}  # fmt: skip
        if pid == "disp:tft24":
            return {"mpn": "ILI9341 2.4", "unit_price_usd": 4.5}
        raise KeyError(pid)

    data = bom.bom(_build(), lookup)
    rows = {r["part_id"]: r for r in data["rows"]}
    sw = rows["lcsc:tact_sw_c318884"]
    assert sw["quantity"] == 2 and sw["manufacturer"] == "XKB Connection"
    assert sw["lcsc_url"] == "https://www.lcsc.com/product-detail/C318884.html"
    assert "keywords=TS-1187A" in sw["digikey_url"] and "q=TS-1187A" in sw["mouser_url"]
    assert rows["disp:tft24"]["line_total_usd"] == 4.5 and sw["unit_price_usd"] is None
    res = rows["kicad:Resistor_SMD:R_0805_2012Metric@10k"]
    assert res["quantity"] == 2 and res["kind"] == "board_part" and res["mouser_url"]
    assert "kicad:Button:SW@" not in "".join(rows)  # mounted footprints are not doubled
    assert rows["case"]["kind"] == "3d_print" and "format=stl" in rows["case"]["file_url"]
    assert rows["pcb:main"]["kind"] == "pcb"
    assert data["case_files"][0]["3mf"].endswith("format=3mf")
    text = bom.bom_csv(_build(), lookup)
    parsed = list(csv.DictReader(io.StringIO(text)))
    assert text.startswith("part_id,") and len(parsed) == len(rows)


def test_generic_names_from_function_not_maker() -> None:
    from bara import naming

    sw = {
        "display_name": "Cherry MX2A Brown",
        "functions": [{"function_id": "input.key", "primary": True}],
        "key_specs": [{"label": "Family", "value": "MX"}, {"label": "Type", "value": "tactile"}],
    }
    naming.neutral(sw)
    assert sw["display_name"] == "Tactile key switch"
    assert [s["label"] for s in sw["key_specs"]] == ["Type"]
    mcu = {
        "display_name": "Seeed XIAO nRF52840",
        "kind": "module",
        "functions": [
            {"function_id": "compute.mcu", "primary": True},
            {"function_id": "comms.ble"},
        ],
    }
    assert naming.generic_name(mcu) == "Wireless controller board"
    stab = {
        "display_name": "Cherry MX stabilizer 2u",
        "functions": [{"function_id": "mech.stabilizer"}],
    }
    assert naming.generic_name(stab) == "2u stabilizer"
    enc = {
        "display_name": "Alps EC11E rotary encoder",
        "functions": [{"function_id": "input.rotary_encoder"}],
    }
    assert naming.generic_name(enc) == "Rotary encoder"
    odd = {"display_name": "Acme SoilPro", "functions": [{"function_id": "sense.soil_moisture"}]}
    assert naming.generic_name(odd) == "Soil moisture sensor"
