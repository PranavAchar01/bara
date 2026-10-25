"""The play surface cannot invent inputs: whatever the model says is checked against the plan."""

from __future__ import annotations

from bara.firmware_sim.agent import surface_ops
from bara.firmware_sim.io import plan_io
from bara.firmware_sim.surface import build_surface, clean
from tests.test_firmware_sim_sensors import monitor


def test_parts_alone_give_a_complete_surface() -> None:
    io = plan_io(monitor())
    s = build_surface(io, None)
    assert s["by"] == "parts"
    assert {c["input_id"] for c in s["controls"]} == {i["id"] for i in io["inputs"]}
    assert s["lead"] in {i["id"] for i in io["inputs"]}
    soil = next(c for c in s["controls"] if c["label"].startswith("Soil"))
    assert (soil["control"], soil["unit"]) == ("slider", "%")


def test_model_cannot_invent_or_misfit() -> None:
    io = plan_io(monitor())
    soil = next(i for i in io["inputs"] if i["kind"] == "sensor")
    model = {
        "controls": [
            {
                "input_id": "u_ghost#0",
                "control": "knob",
                "label": "Ghost",
                "unit": "",
                "group": "x",
            },
            {
                "input_id": soil["id"],
                "control": "knob",
                "label": "Soil moisture — Nordic",
                "unit": "kg",
                "group": "Measurements",
            },
        ],
        "outputs": [{"output_id": "tone:u_buz", "show": "motor", "label": "Alarm"}],
        "lead": "nope",
    }
    s = build_surface(io, model)
    ids = [c["input_id"] for c in s["controls"]]
    assert "u_ghost#0" not in ids and soil["id"] in ids
    c = next(c for c in s["controls"] if c["input_id"] == soil["id"])
    assert c["control"] == "slider" and c["unit"] == "%" and "—" not in c["label"]
    assert "Nordic" not in c["label"]
    assert next(o for o in s["outputs"] if o["output_id"] == "tone:u_buz")["show"] == "buzzer"
    assert s["lead"] in ids


def test_chat_ops_are_bounded_by_real_inputs() -> None:
    io = plan_io(monitor())
    soil = next(i for i in io["inputs"] if i["kind"] == "sensor")
    ops = surface_ops(
        [
            {"op": "set", "input_id": soil["id"], "label": "", "value": 900},
            {"op": "show", "input_id": "battery", "label": "", "value": 0},
        ],
        io,
    )
    assert ops == [{"op": "set", "input_id": soil["id"], "value": soil["max"]}]


def test_copy_has_no_dashes_or_brands() -> None:
    assert clean("Cherry MX — key") == "MX, key"
