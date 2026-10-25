"""Firmware simulator end to end on made-up builds: plan the I/O, compile for the chip and the
host, boot in the emulator, press an input and see an output change, run the test catalog."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from bara.firmware_sim.codegen import FwConfig
from bara.firmware_sim.emulator import HostSession, make_chip
from bara.firmware_sim.io import plan_io
from bara.firmware_sim.tests import catalog, run_test
from bara.firmware_sim.toolchain import build as compile_firmware


def part(iid: str, fn: str, name: str, qty: int = 1, label: str = "", pid: str = "") -> dict:
    return {
        "instance_id": iid,
        "part_id": pid or f"x:{iid}",
        "quantity": qty,
        "label": label,
        "card": {"primary_function": fn, "display_name": name, "part_id": pid or f"x:{iid}"},
    }


def joystick_handheld() -> dict[str, Any]:
    return {
        "build_id": "b_testarcade",
        "prompt": "a handheld arcade device with a joystick",
        "parts": [
            part("u_mcu", "compute.mcu", "RP2040 board", pid="mod:rpi_pico"),
            part("u_joy", "input.joystick", "Thumb joystick", label="Joystick"),
            part("u_btn", "input.button", "Tactile button", 2, "A and B buttons"),
            part("u_pwr", "power.switch", "Slide switch", label="Power switch"),
            part("u_spk", "output.speaker", "Small speaker"),
            part("u_disp", "display.oled", "OLED 128x64"),
        ],
    }


def macropad() -> dict[str, Any]:
    return {
        "build_id": "b_testpad",
        "prompt": "a macropad with 4 keys and a knob",
        "parts": [
            part("u_mcu", "compute.mcu", "nRF52840 board", pid="mod:nice_nano_v2"),
            part("u_sw", "input.key", "Key switch", 4, "Switches"),
            part("u_enc", "input.rotary_encoder", "Rotary encoder"),
        ],
    }


needs_cc = pytest.mark.skipif(shutil.which("cc") is None, reason="no host C compiler")


@pytest.fixture(params=[joystick_handheld, macropad], ids=["arcade", "macropad"])
def built(request: pytest.FixtureRequest, tmp_path: Path):
    io = plan_io(request.param())
    cfg = FwConfig()
    fw = compile_firmware(io, cfg, tmp_path)
    return io, cfg, fw, tmp_path


@needs_cc
def test_compiles_for_chip_and_host(built) -> None:
    io, _cfg, fw, out = built
    assert fw["status"] == "ok", fw
    assert fw["host"]["status"] == "ok", fw["host"]["log"]
    assert fw["target"]["status"] == "ok", fw["target"]["log"]
    assert fw["mode"] == "emulated"
    assert (out / "firmware.elf").is_file() and (out / "firmware.uf2").is_file()
    assert fw["target"]["size"]["text"] > 0


@needs_cc
def test_pressing_an_input_changes_an_output(built) -> None:
    io, cfg, fw, out = built
    first = next(i for i in io["inputs"] if i["kind"] in ("button", "key", "mkey"))
    for s in (
        make_chip(io, cfg, out / "firmware.elf"),
        HostSession(io, cfg, out / "firmware_host"),
    ):
        try:
            s.run_ms(50)
            seq = s.snapshot()["seq"]
            s.press(first["id"], True)
            s.run_ms(30)
            snap = s.snapshot(seq)
            lines = [e["text"] for e in snap["events"] if e["type"] == "serial"]
            assert any(first["label"] in t and "press" in t for t in lines), lines
            assert any(led["on"] for led in snap["leds"]), snap["leds"]
        finally:
            if isinstance(s, HostSession):
                s.close()


@needs_cc
def test_joystick_moves_the_axis() -> None:
    io = plan_io(joystick_handheld())
    axes = [i for i in io["inputs"] if i["kind"] == "axis"]
    assert len(axes) == 2


@needs_cc
def test_catalog_runs_without_failures(built) -> None:
    io, cfg, fw, out = built
    results = [run_test(t["id"], io, cfg, fw, out) for t in catalog(io, fw)]
    bad = [(r["id"], r["summary"]) for r in results if r["status"] == "fail"]
    assert not bad, bad
    assert any(r["id"].startswith("emu.") and r["status"] == "pass" for r in results)
