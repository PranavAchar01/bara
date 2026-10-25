"""The simulator's test list: firmware unit tests (host build), the same behaviour on the
emulated chip, pin-map checks, and the ngspice electrical checks. Run one or run all."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import kicad_checks, spice
from .codegen import FwConfig, input_rows
from .emulator import ChipSession, HostSession, make_chip
from .mcu import BOARDS

Session = HostSession | ChipSession


def _serial(s: Session, since: int) -> list[str]:
    return [e["text"] for e in s.snapshot(since)["events"] if e["type"] == "serial"]


def _r(status: str, summary: str, log: list[str]) -> dict[str, Any]:
    return {"status": status, "summary": summary, "log": "\n".join(log)}


# ---- behaviour scenarios, shared by the host and the chip runs -----------------------------
def t_boot(s: Session, io: dict[str, Any], cfg: FwConfig) -> dict[str, Any]:
    s.run_ms(50)
    lines = _serial(s, 0)
    ok = any(ln.startswith("bara-fw ") for ln in lines) and "ready" in lines
    return _r(
        "pass" if ok else "fail",
        "prints its banner and 'ready' within 50 ms" if ok else "no boot banner on the console",
        lines,
    )


def t_press_all(s: Session, io: dict[str, Any], cfg: FwConfig) -> dict[str, Any]:
    rows = [r for r in input_rows(io, cfg) if r["fw_kind"] in ("button", "key", "switch", "mkey")]
    if not rows:
        return _r("skip", "no buttons or keys", [])
    s.run_ms(20)
    log, bad = [], []
    for r in rows:
        mark = s.seq
        s.press(r["id"], True)
        s.run_ms(cfg.debounce_ms + 15)
        s.press(r["id"], False)
        s.run_ms(cfg.debounce_ms + 15)
        lines = _serial(s, mark)
        word = "switch on" if r["fw_kind"] == "switch" else "press"
        pressed = any(word in ln and ln.endswith(r["label"]) for ln in lines)
        hid = [ln for ln in lines if ln.startswith("HID ")]
        ok = pressed and len(hid) >= 2 and hid[-1].split()[2:] == ["00"] * len(hid[-1].split()[2:])
        if r.get("hid") and ok:
            ok = f"{int(r['hid']):02X}" in hid[0]
        log += [f"{r['label']}: " + (" | ".join(lines) or "(nothing)")]
        if not ok:
            bad.append(r["label"])
    return _r(
        "fail" if bad else "pass",
        f"{len(rows) - len(bad)}/{len(rows)} inputs report press, HID and release"
        + (f"; failed: {', '.join(bad[:6])}" if bad else ""),
        log,
    )


def t_debounce(s: Session, io: dict[str, Any], cfg: FwConfig) -> dict[str, Any]:
    rows = [r for r in input_rows(io, cfg) if r["fw_kind"] in ("button", "key", "mkey")]
    if not rows:
        return _r("skip", "no buttons or keys", [])
    r = rows[0]
    s.run_ms(20)
    mark = s.seq
    for _ in range(3):  # contact chatter faster than the debounce window
        s.press(r["id"], True)
        s.run_ms(1)
        s.press(r["id"], False)
        s.run_ms(1)
    s.press(r["id"], True)
    s.run_ms(cfg.debounce_ms + 10)
    s.press(r["id"], False)
    s.run_ms(cfg.debounce_ms + 10)
    lines = _serial(s, mark)
    presses = [ln for ln in lines if " press " in ln]
    ok = len(presses) == 1
    return _r(
        "pass" if ok else "fail",
        f"3 bounces then a press: {len(presses)} press event(s), expected 1",
        lines,
    )


def t_blink(s: Session, io: dict[str, Any], cfg: FwConfig) -> dict[str, Any]:
    led = next((o for o in io["outputs"] if o["id"] == "led:onboard" and o.get("pin")), None)
    if not led:
        return _r("skip", "no status LED", [])
    from .mcu import pin_number

    pin = pin_number(s.board, led["pin"])
    start = s.now_ms()
    s.run_ms(cfg.blink_ms * 4 + 50)
    edges: list[float] = []
    for t, _ in s.wave.get(pin, []):
        if t < start:
            continue
        if edges and t - edges[-1] < 1.0:
            edges[-1] = t  # pin set up, then driven: one change, not two
        else:
            edges.append(t)
    if len(edges) < 3:
        return _r("fail", f"LED changed {len(edges)} times in {cfg.blink_ms * 4} ms", [])
    gaps = [b - a for a, b in zip(edges, edges[1:], strict=False)]
    avg = sum(gaps) / len(gaps)
    ok = abs(avg - cfg.blink_ms) <= max(3, cfg.blink_ms * 0.02)
    return _r(
        "pass" if ok else "fail",
        f"LED toggles every {avg:.1f} ms (set to {cfg.blink_ms} ms)",
        [f"edges at {', '.join(f'{t:.1f}' for t in edges)} ms"],
    )


def t_encoder(s: Session, io: dict[str, Any], cfg: FwConfig) -> dict[str, Any]:
    rows = [r for r in input_rows(io, cfg) if r["fw_kind"] == "encoder"]
    if not rows:
        return _r("skip", "no rotary encoder", [])
    r = rows[0]
    s.run_ms(10)
    mark = s.seq
    s.turn(r["id"], 2)
    s.turn(r["id"], -1)
    lines = _serial(s, mark)
    cw = sum(1 for ln in lines if ln.endswith(" clockwise") and "anti" not in ln)
    ccw = sum(1 for ln in lines if ln.endswith("anticlockwise"))
    ok = cw == 2 and ccw == 1
    return _r(
        "pass" if ok else "fail", f"2 steps right, 1 left: read {cw} right, {ccw} left", lines
    )


def t_axis(s: Session, io: dict[str, Any], cfg: FwConfig) -> dict[str, Any]:
    rows = [r for r in input_rows(io, cfg) if r["fw_kind"] == "axis"]
    if not rows:
        return _r("skip", "no joystick or dial", [])
    log, bad = [], []
    for r in rows:
        s.run_ms(10)
        mark = s.seq
        s.set_axis(r["id"], 1.0)
        s.run_ms(30)
        s.set_axis(r["id"], 0.0)
        s.run_ms(30)
        lines = _serial(s, mark)
        log += lines
        if not any(r["label"] in ln and "+127" in ln for ln in lines):
            bad.append(r["label"])
    return _r(
        "fail" if bad else "pass",
        f"{len(rows) - len(bad)}/{len(rows)} axes report full scale and return to centre",
        log,
    )


def t_power(s: Session, io: dict[str, Any], cfg: FwConfig) -> dict[str, Any]:
    s.run_ms(20)
    mark = s.seq
    s.set_power(False)
    s.run_ms(50)
    off = s.snapshot()
    s.set_power(True)
    s.run_ms(30)
    lines = _serial(s, mark)
    leds_off = not any(led["on"] for led in off["leds"])
    rebooted = any(ln.startswith("bara-fw ") for ln in lines)
    ok = leds_off and rebooted and not off["screen"]
    return _r(
        "pass" if ok else "fail",
        "cutting the rail turns every output off; power on reboots and prints the banner"
        if ok
        else "outputs stayed on, or no reboot after power on",
        lines,
    )


SCENARIOS: list[tuple[str, str, Callable[..., dict[str, Any]]]] = [
    ("boot", "Boots and prints its banner", t_boot),
    ("press", "Every button reports press, HID and release", t_press_all),
    ("debounce", "Contact bounce gives one press", t_debounce),
    ("blink", "Status LED blinks at the set rate", t_blink),
    ("encoder", "Knob direction is read correctly", t_encoder),
    ("axis", "Joystick axes reach full scale", t_axis),
    ("power", "Power switch cuts and restores the device", t_power),
]


# ---- pin map ---------------------------------------------------------------------------------
def pin_checks(io: dict[str, Any]) -> list[dict[str, Any]]:
    board = BOARDS.get(io["mcu"]["board_id"]) or BOARDS["nice_nano_v2"]
    out = []
    missing = io.get("pins_missing") or []
    out.append(
        {
            "id": "pins.assigned",
            "name": "Every input has a pin",
            "status": "fail" if missing else "pass",
            "summary": f"{len(io['inputs']) - len(missing)}/{len(io['inputs'])} inputs wired"
            + (f"; no pin for {', '.join(missing)}" if missing else ""),
        }
    )
    owners: dict[str, list[str]] = {}
    matrix = io.get("matrix") or {}
    for n, p in enumerate(matrix.get("row_pins") or []):
        owners.setdefault(p, []).append(f"matrix row {n}")
    for n, p in enumerate(matrix.get("col_pins") or []):
        owners.setdefault(p, []).append(f"matrix column {n}")
    for i in io["inputs"]:
        if i.get("row_pin"):
            continue  # matrix keys share row and column lines by design
        for k in ("pin", "pin_b"):
            if i.get(k):
                owners.setdefault(i[k], []).append(i["label"])
    for o in io["outputs"]:
        if o.get("pin") and o["kind"] != "serial" and o["id"] != "led:onboard":
            owners.setdefault(o["pin"], []).append(o["label"])
        for p in (o.get("pins") or {}).values():
            if p:
                owners.setdefault(p, []).append(o["label"])
    shared = {p: n for p, n in owners.items() if len(n) > 1}
    out.append(
        {
            "id": "pins.unique",
            "name": "No pin drives two things",
            "status": "fail" if shared else "pass",
            "summary": "; ".join(f"{p}: {', '.join(n)}" for p, n in shared.items())
            or f"{len(owners)} pins, each used once",
        }
    )
    axes = [i for i in io["inputs"] if i["kind"] == "axis"]
    not_adc = [i["label"] for i in axes if i.get("pin") not in board.adc]
    out.append(
        {
            "id": "pins.adc",
            "name": "Analog inputs sit on ADC pins",
            "status": "skip" if not axes else "fail" if not_adc else "pass",
            "summary": "no analog inputs"
            if not axes
            else f"not on an ADC pin: {', '.join(not_adc)}"
            if not_adc
            else ", ".join(f"{i['label']} on {i['pin']} (ADC{i.get('adc')})" for i in axes),
        }
    )
    on_reserved = [f"{p} ({board.reserved[p]})" for p in owners if p in board.reserved]
    out.append(
        {
            "id": "pins.reserved",
            "name": "Nothing on a reserved pin",
            "status": "fail" if on_reserved else "pass",
            "summary": ", ".join(on_reserved) or "no reserved pin used",
        }
    )
    src = io.get("pins_source") or ""
    out.append(
        {
            "id": "pins.source",
            "name": "Pins come from the board's netlist",
            "status": "pass" if src == "board netlist" else "warn",
            "summary": "pins read from the routed board"
            if src == "board netlist"
            else "the board is not routed yet, so pins come from the simulator's pin plan",
        }
    )
    for c in out:
        c["group"] = "pinmap"
    return out


# ---- registry --------------------------------------------------------------------------------
def catalog(io: dict[str, Any], fw: dict[str, Any]) -> list[dict[str, Any]]:
    items = [
        {"id": "build.target", "group": "firmware", "name": f"Compiles for {fw['board']['label']}"},
        {"id": "build.host", "group": "firmware", "name": "Compiles for the host test harness"},
    ]
    for key, name, _ in SCENARIOS:
        items.append({"id": f"unit.{key}", "group": "firmware", "name": name})
    if fw["mode"] == "emulated":
        for key, name, _ in SCENARIOS:
            items.append({"id": f"emu.{key}", "group": "emulation", "name": f"{name} (chip)"})
    items += [{k: c[k] for k in ("id", "group", "name")} for c in pin_checks(io)]
    names = {
        "spice.rail": "Power rail holds 3.3 V under load",
        "spice.led": "LED current within the pin's drive",
        "spice.debounce": "Switch bounce settles inside the debounce window",
        "spice.charger": "Battery charging stays inside USB and cell limits",
    }
    items += [{"id": k, "group": "ngspice", "name": v} for k, v in names.items()]
    items += [
        {"id": k, "group": "kicad", "name": kicad_checks.KICAD_NAMES[k]}
        for k in kicad_checks.KICAD_IDS
    ]
    return items


def run_test(
    tid: str,
    io: dict[str, Any],
    cfg: FwConfig,
    fw: dict[str, Any],
    out_dir: Path,
    state: dict[str, Any] | None = None,
    boards_root: Path | None = None,
) -> dict[str, Any]:
    t0 = time.monotonic()
    meta = next((c for c in catalog(io, fw) if c["id"] == tid), None)
    if not meta:
        raise KeyError(tid)
    res: dict[str, Any]
    if tid in ("build.target", "build.host"):
        b = fw["target" if tid == "build.target" else "host"]
        status = {"ok": "pass", "failed": "fail", "unavailable": "skip"}[b["status"]]
        size = b.get("size")
        summary = (
            f"{b.get('compiler', '')}: {size['text']} B code, {size['bss']} B RAM"
            if size
            else b.get("message") or b.get("compiler", "")
        )
        res = {"status": status, "summary": summary, "log": f"$ {b.get('command', '')}\n{b['log']}"}
    elif tid.startswith(("unit.", "emu.")):
        key = tid.split(".", 1)[1]
        fn = next(f for k, _, f in SCENARIOS if k == key)
        if tid.startswith("unit."):
            if fw["host"]["status"] != "ok":
                res = _r("fail", "the host build failed, nothing to run", [])
            else:
                s: Session = HostSession(io, cfg, out_dir / "firmware_host")
                try:
                    res = fn(s, io, cfg)
                finally:
                    s.close()
        else:
            s = make_chip(io, cfg, out_dir / "firmware.elf")
            res = fn(s, io, cfg)
    elif tid.startswith("pins."):
        res = next(c for c in pin_checks(io) if c["id"] == tid)
    elif tid in kicad_checks.KICAD_IDS:
        res = kicad_checks.run(tid, state or {}, boards_root)
    else:
        board = BOARDS.get(io["mcu"]["board_id"]) or BOARDS["nice_nano_v2"]
        check = spice.CHECKS[tid]
        res = (
            spice.debounce_check(io, board, cfg.debounce_ms)
            if tid == "spice.debounce"
            else check(io, board)  # type: ignore[call-arg]
        )
    return {
        **meta,
        **res,
        "id": tid,
        "seconds": round(time.monotonic() - t0, 3),
        "ran_at": time.time(),
    }
