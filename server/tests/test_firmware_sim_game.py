"""The firmware plays a game on the display framebuffer; typed keys, reboot, dials and the
KiCad checks. All on made-up builds, in the emulator and the host build."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest
from test_firmware_sim_engine import joystick_handheld, macropad, needs_cc, part

from bara.firmware_sim import kicad_checks
from bara.firmware_sim.codegen import FwConfig
from bara.firmware_sim.emulator import HostSession, make_chip
from bara.firmware_sim.io import plan_io
from bara.firmware_sim.toolchain import build as compile_firmware


def _lit(snap: dict) -> int:
    packed = base64.b64decode(snap["fb"]["b64"])
    return sum(bin(b).count("1") for b in packed)


@pytest.fixture
def arcade(tmp_path: Path):
    io = plan_io(joystick_handheld())
    cfg = FwConfig()
    fw = compile_firmware(io, cfg, tmp_path)
    assert fw["status"] == "ok", fw
    return io, cfg, tmp_path


@needs_cc
def test_game_draws_and_responds_to_buttons(arcade) -> None:
    io, cfg, out = arcade
    buttons = [i for i in io["inputs"] if i["kind"] == "button" and "press" not in i["label"]]
    for s in (
        make_chip(io, cfg, out / "firmware.elf"),
        HostSession(io, cfg, out / "firmware_host"),
    ):
        try:
            s.run_ms(300)
            before = s.snapshot()
            assert before["fb"], "the firmware drew nothing"
            s.press(buttons[0]["id"], True)
            s.run_ms(60)
            s.press(buttons[0]["id"], False)
            s.run_ms(600)
            after = s.snapshot()
            assert after["fb"]["b64"] != before["fb"]["b64"], "the game did not move"
            texts = [e["text"] for e in after["events"] if e["type"] == "serial"]
            assert any("game start" in t for t in texts), texts
        finally:
            if isinstance(s, HostSession):
                s.close()


@needs_cc
def test_joystick_steers_the_game(arcade) -> None:
    io, cfg, out = arcade
    ax = next(i for i in io["inputs"] if i["kind"] == "axis" and i["label"].endswith("Y"))
    s = make_chip(io, cfg, out / "firmware.elf")
    s.run_ms(200)
    s.set_axis(ax["id"], 1.0)
    s.run_ms(100)
    a = s.snapshot()["fb"]["b64"]
    s.run_ms(300)
    assert s.snapshot()["fb"]["b64"] != a


@needs_cc
def test_reset_restarts_the_chip_and_boot_enters_the_bootloader(arcade) -> None:
    io, cfg, out = arcade
    s = make_chip(io, cfg, out / "firmware.elf")
    s.run_ms(300)
    t0 = s.snapshot()["t_ms"]
    s.reboot()
    s.run_ms(50)
    snap = s.snapshot()
    assert not snap["bootloader"] and snap["fb"]
    assert any(e["type"] == "serial" and "bara-fw" in e["text"] for e in snap["events"][-30:])
    s.reboot(bootloader=True)
    snap = s.snapshot()
    assert snap["bootloader"] and snap["fb"] is None
    assert snap["t_ms"] >= t0
    s.reboot()
    assert not s.snapshot()["bootloader"]


@needs_cc
def test_keyboard_types_text(tmp_path: Path) -> None:
    io = plan_io(macropad())
    cfg = FwConfig(codes={f"{io['inputs'][0]['id']}": "K"})
    io = plan_io(macropad(), None, cfg.codes)
    fw = compile_firmware(io, cfg, tmp_path)
    s = make_chip(io, cfg, tmp_path / "firmware.elf")
    key = next(i for i in io["inputs"] if i["kind"] == "key")
    s.run_ms(100)
    s.press(key["id"], True)
    s.run_ms(40)
    s.press(key["id"], False)
    s.run_ms(40)
    typed = [e["text"] for e in s.snapshot()["events"] if e["type"] == "typed"]
    assert fw["status"] == "ok" and typed == ["k"], typed


def test_two_potentiometers_make_two_dials() -> None:
    build = {
        "build_id": "b_dials",
        "prompt": "a mixer with two sliders",
        "parts": [
            part("u_mcu", "compute.mcu", "RP2040 board", pid="mod:rpi_pico"),
            part("u_pot", "input.potentiometer", "Slide potentiometer", 2),
        ],
    }
    dials = [i for i in plan_io(build)["inputs"] if i["kind"] == "axis"]
    assert [d["label"] for d in dials] == ["Dial 1", "Dial 2"]
    assert len({d["id"] for d in dials}) == 2


def test_kicad_checks_say_so_without_a_board() -> None:
    for tid in kicad_checks.KICAD_IDS:
        r = kicad_checks.run(tid, {"boards": []}, Path("/nonexistent"))
        assert r["status"] == "unavailable" and r["summary"] == "not run: no board yet"
