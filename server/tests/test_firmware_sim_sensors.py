"""A sensing part is an input with a physical range: the person sets the value, the chip reads the
matching ADC code, the screen and the console show the reading and an out-of-range value raises the
alert on the speaker and the lamp."""

from __future__ import annotations

from pathlib import Path

from bara.firmware_sim.codegen import FwConfig
from bara.firmware_sim.emulator import make_chip
from bara.firmware_sim.io import plan_io
from bara.firmware_sim.toolchain import build as compile_firmware
from tests.test_firmware_sim_engine import part


def monitor() -> dict:
    return {
        "build_id": "b_testplant",
        "prompt": "a plant soil moisture monitor with a buzzer",
        "parts": [
            part("u_mcu", "compute.mcu", "nRF52840 board", pid="mod:nice_nano_v2"),
            part("u_soil", "sense.soil_moisture", "Capacitive soil sensor"),
            part("u_t", "sense.temperature", "Temperature sensor"),
            part("u_buz", "output.buzzer", "Buzzer"),
            part("u_disp", "display.oled", "OLED 128x64"),
        ],
    }


def test_sensor_inputs_are_planned_with_units() -> None:
    io = plan_io(monitor())
    sensors = [i for i in io["inputs"] if i["kind"] == "sensor"]
    assert [s["unit"] for s in sensors] == ["%", "°C"]
    assert all(s.get("pin") and s["min"] < s["max"] for s in sensors)


def test_sensor_reading_reaches_screen_and_alert(tmp_path: Path) -> None:
    io = plan_io(monitor())
    cfg = FwConfig()
    fw = compile_firmware(io, cfg, tmp_path)
    assert fw["status"] == "ok"
    s = make_chip(io, cfg, tmp_path / "firmware.elf")
    s.run_ms(400)
    soil = next(i for i in io["inputs"] if i["quantity"].startswith("Soil"))
    assert any("35" in r for r in s.snapshot()["screen"])
    s.set_sensor(soil["id"], 2)
    s.run_ms(600)
    snap = s.snapshot()
    assert any("sense" in e.get("text", "") and "Soil" in e.get("text", "") for e in snap["events"])
    assert any(l["kind"] == "tone" for l in snap["leds"])
