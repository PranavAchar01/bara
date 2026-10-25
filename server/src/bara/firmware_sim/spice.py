"""Electrical checks in ngspice (KiCad's own libngspice): the supply rail across the battery's
range, the current through each LED from its GPIO, a button's contact bounce against the pull-up
and the firmware's debounce window, and the battery charging path.

Each check returns pass / warn / fail / skip with the numbers and the deck it ran, so the person
can read exactly what was simulated. Figures the build does not state are datasheet typicals and
are named as assumptions in the result."""

from __future__ import annotations

import re
import time
from typing import Any

from bara.sim.ngspice import SimError, get_engine
from bara.sim.power import (
    ESR_BATT_OHM,
    LDO_DROPOUT_AT_A,
    LDO_DROPOUT_V,
    LDO_IQ_A,
    R_SWITCH_OHM,
)

from .mcu import BOARDS, Board

MCU_CURRENT_A = {"nrf52840": 0.015, "rp2040": 0.025}  # active peak, datasheet typicals
V_RAIL = 3.3
V_RAIL_MIN = 3.0  # lowest rail the display and the radio are specified for


def _result(tid: str, name: str, status: str, summary: str, **kw: Any) -> dict[str, Any]:
    return {"id": tid, "name": name, "group": "ngspice", "status": status, "summary": summary, **kw}


def _run(deck: list[str], analyses: list[str]) -> list[dict[str, list[float]]]:
    return get_engine().run(deck, analyses)


def _display_load(io: dict[str, Any]) -> tuple[float, str]:
    total, names = 0.0, []
    for o in io["outputs"]:
        if o["kind"] != "display":
            continue
        w = int(o.get("width") or 128)
        a = 0.08 if w >= 240 else 0.02  # TFT with backlight vs small OLED
        total += a
        names.append(f"{o['label']} {a * 1000:.0f} mA")
    return total, ", ".join(names)


def _battery(io: dict[str, Any]) -> dict[str, Any] | None:
    b = (io.get("power") or {}).get("battery")
    if not b:
        return None
    name = f"{b.get('name') or ''} {b.get('part_id') or ''}".strip()
    m = re.search(r"(\d{3,5})\s*mAh", name, re.I)
    if m:
        cap, src = float(m.group(1)), "part name"
    elif "18650" in name:
        cap, src = 2500.0, "18650 cell typical"
    elif re.search(r"coin|cr20", name, re.I):
        cap, src = 220.0, "coin cell typical"
    else:
        cap, src = 500.0, "assumed"
    return {"name": str(b.get("name") or "Battery"), "mah": cap, "source": src}


# ---- 1. supply rail ------------------------------------------------------------------------
def rail_check(io: dict[str, Any], board: Board) -> dict[str, Any]:
    tid, name = "spice.rail", "Power rail holds 3.3 V under load"
    i_mcu = MCU_CURRENT_A.get(board.family, 0.02)
    i_disp, disp_names = _display_load(io)
    i_led = sum(board.drive_ma / 1000 for o in io["outputs"] if o["kind"] == "led")
    i_tone = 0.03 if any(o["kind"] == "tone" for o in io["outputs"]) else 0.0
    i_load = i_mcu + i_disp + i_led + i_tone
    batt = _battery(io)
    r_do = LDO_DROPOUT_V / LDO_DROPOUT_AT_A
    points = [4.2, 3.7, 3.4, 3.2] if batt else [5.0]
    esr = ESR_BATT_OHM if batt else 0.3  # cell ESR or USB cable + connector
    rows, decks = [], []
    try:
        for v in points:
            deck = [
                f"* rail at {v} V",
                f"Vsrc src 0 DC {v}",
                f"Resr src a {esr}",
                f"Rsw a vin {R_SWITCH_OHM}",
                # regulates to 3.3 V until the input is within the dropout of it
                f"Bldo reg 0 V = min(3.3 + {r_do:.4f} * I(Vsense), V(vin))",
                f"Rdo reg n2 {r_do:.4f}",
                "Vsense n2 rail 0",
                "Fin vin 0 Vsense 1",
                f"Iq vin 0 {LDO_IQ_A}",
                f"Iload rail 0 {i_load:.5f}",
                "Cout rail 0 10u",
            ]
            res = _run(deck, ["op"])[0]
            rail = res["rail"][0]
            vin = res["vin"][0]
            rows.append({"v_source": v, "v_in": round(vin, 3), "v_rail": round(rail, 3)})
            decks.append("\n".join(deck))
    except SimError as e:
        return _result(tid, name, "fail", f"ngspice rejected the deck: {e}", log=str(e))
    nominal = next((r for r in rows if r["v_source"] in (3.7, 5.0)), rows[0])
    low = next((r for r in rows if r["v_source"] == 3.4), None)
    status = "pass" if nominal["v_rail"] >= V_RAIL_MIN else "fail"
    if status == "pass" and low and low["v_rail"] < V_RAIL_MIN:
        status = "warn"
    summary = (
        f"{nominal['v_rail']:.2f} V at {nominal['v_source']} V in with "
        f"{i_load * 1000:.0f} mA load"
        + (f"; {low['v_rail']:.2f} V when the cell is at 3.4 V" if low else "")
    )
    return _result(
        tid,
        name,
        status,
        summary,
        numbers={"load_ma": round(i_load * 1000, 1), "points": rows, "min_rail_v": V_RAIL_MIN},
        assumptions=[
            f"controller {i_mcu * 1000:.0f} mA active",
            disp_names or "no display",
            f"LDO dropout {LDO_DROPOUT_V} V at {LDO_DROPOUT_AT_A} A",
            f"source resistance {esr} ohm",
        ]
        + ([f"battery {batt['name']} ({batt['source']})"] if batt else ["USB 5 V supply"]),
        log="\n\n".join(decks),
    )


# ---- 2. LED current ------------------------------------------------------------------------
def led_check(io: dict[str, Any], board: Board) -> dict[str, Any]:
    tid, name = "spice.led", "LED current within the pin's drive"
    leds = [o for o in io["outputs"] if o["kind"] == "led"]
    if not leds:
        return _result(tid, name, "skip", "No LED in this build.")
    r_out = 0.4 / (board.drive_ma / 1000)  # VOH drop of 0.4 V at the rated drive current
    rows, decks = [], []
    try:
        for o in leds:
            r_series = 1000.0
            deck = [
                f"* {o['label']} driven high",
                f"Vpin p 0 DC {board.vdd}",
                f"Rout p pad {r_out:.1f}",
                f"Rled pad a {r_series}",
                "Dled a 0 LEDR",
                ".model LEDR D(IS=1e-19 N=1.9 RS=8)",
            ]
            res = _run(deck, ["op"])[0]
            i = res.get("vpin#branch", [0.0])[0]
            i_ma = abs(i) * 1000
            vf = res["a"][0]
            ok = 0.3 <= i_ma <= board.drive_ma
            rows.append(
                {
                    "led": o["label"],
                    "i_ma": round(i_ma, 2),
                    "vf_v": round(vf, 2),
                    "r_ohm": r_series,
                    "ok": ok,
                }
            )
            decks.append("\n".join(deck))
    except SimError as e:
        return _result(tid, name, "fail", f"ngspice rejected the deck: {e}", log=str(e))
    bad = [r for r in rows if not r["ok"]]
    summary = "; ".join(f"{r['led']}: {r['i_ma']:.2f} mA at Vf {r['vf_v']} V" for r in rows)
    return _result(
        tid,
        name,
        "fail" if bad else "pass",
        summary + f" (limit {board.drive_ma:g} mA per pin)",
        numbers={"leds": rows, "drive_limit_ma": board.drive_ma},
        assumptions=[
            "1 kOhm series resistor",
            f"pin output resistance {r_out:.0f} ohm ({board.drive_ma:g} mA standard drive)",
            "red LED diode model",
        ],
        log="\n\n".join(decks),
    )


# ---- 3. contact bounce vs debounce ---------------------------------------------------------
BOUNCE_PRESS = [(1.00, 1), (1.12, 0), (1.25, 1), (1.31, 0), (1.42, 1)]  # ms, 1 = closed
BOUNCE_RELEASE = [(4.00, 0), (4.08, 1), (4.20, 0), (4.27, 1), (4.38, 0)]


def debounce_check(io: dict[str, Any], board: Board, debounce_ms: int) -> dict[str, Any]:
    tid, name = "spice.debounce", "Switch bounce settles inside the debounce window"
    buttons = [i for i in io["inputs"] if i["kind"] in ("button", "key", "switch")]
    if not buttons:
        return _result(tid, name, "skip", "No push button or key in this build.")
    pwl = ["0 0"]
    for t, s in BOUNCE_PRESS + BOUNCE_RELEASE:
        v = 1 if s else 0
        pwl += [f"{t - 0.002:.3f}m {1 - v}", f"{t:.3f}m {v}"]
    c_pin = 10e-12 + 5e-12  # pin plus trace
    deck = [
        f"* {buttons[0]['label']} against the {board.pullup_ohm / 1000:.0f} kOhm pull-up",
        f"Vdd vdd 0 DC {board.vdd}",
        f"Rpu vdd pin {board.pullup_ohm:.0f}",
        f"Cpin pin 0 {c_pin:.3e}",
        "Ssw pin 0 ctl 0 SWMOD",
        ".model SWMOD SW(VT=0.5 VH=0.1 RON=0.2 ROFF=1e9)",
        "Vctl ctl 0 PWL(" + " ".join(pwl) + ")",
    ]
    try:
        res = _run(deck, ["tran 1u 6m"])[0]
    except SimError as e:
        return _result(tid, name, "fail", f"ngspice rejected the deck: {e}", log=str(e))
    t = res.get("time") or []
    v = res["pin"]
    vih, vil = 0.7 * board.vdd, 0.3 * board.vdd
    edges, state, last_cross = 0, 1, 0.0
    for tt, vv in zip(t, v, strict=False):
        if state == 1 and vv < vil:
            state, edges, last_cross = 0, edges + 1, tt
        elif state == 0 and vv > vih:
            state, edges, last_cross = 1, edges + 1, tt
    settle_ms = (last_cross * 1000 - BOUNCE_RELEASE[0][0]) if last_cross else 0.0
    bounce_ms = BOUNCE_PRESS[-1][0] - BOUNCE_PRESS[0][0]
    rise_us = 0.0
    for tt, vv in zip(t, v, strict=False):
        if tt * 1000 >= BOUNCE_RELEASE[-1][0] and vv > vih:
            rise_us = tt * 1e6 - BOUNCE_RELEASE[-1][0] * 1000
            break
    ok = debounce_ms > max(bounce_ms, settle_ms) and rise_us < debounce_ms * 1000
    return _result(
        tid,
        name,
        "pass" if ok else "fail",
        f"{edges} raw edges from one press and release; the line settles "
        f"{settle_ms:.2f} ms after release (rise {rise_us:.2f} us), inside the "
        f"{debounce_ms} ms debounce window"
        if ok
        else f"bounce lasts {max(bounce_ms, settle_ms):.2f} ms, longer than the "
        f"{debounce_ms} ms debounce window",
        numbers={
            "raw_edges": edges,
            "bounce_ms": round(bounce_ms, 3),
            "settle_after_release_ms": round(settle_ms, 3),
            "rise_us": round(rise_us, 2),
            "debounce_ms": debounce_ms,
            "pullup_kohm": round(board.pullup_ohm / 1000, 1),
        },
        trace={
            "t_ms": [round(x * 1000, 4) for x in t[:: max(1, len(t) // 400)]],
            "v": [round(x, 3) for x in v[:: max(1, len(v) // 400)]],
        },
        assumptions=[
            "contact bounce of 0.4 ms on press and release (typical tactile switch)",
            f"internal pull-up {board.pullup_ohm / 1000:.0f} kOhm, 15 pF on the pin",
        ],
        log="\n".join(deck),
    )


# ---- 4. charging path ----------------------------------------------------------------------
def charger_check(io: dict[str, Any], board: Board) -> dict[str, Any]:
    tid, name = "spice.charger", "Battery charging stays inside USB and cell limits"
    pw = io.get("power") or {}
    batt = _battery(io)
    if not batt:
        return _result(tid, name, "skip", "No rechargeable battery in this build.")
    chg = pw.get("charger")
    if not chg:
        return _result(
            tid,
            name,
            "warn",
            f"{batt['name'] or 'The battery'} has no charger part, so it cannot be recharged "
            "from USB.",
        )
    cname = f"{chg.get('name') or ''} {chg.get('part_id') or ''}"
    i_sys = MCU_CURRENT_A.get(board.family, 0.02) + _display_load(io)[0]
    if re.search(r"tp4056", cname, re.I):
        i_set, how = 1.0, "TP4056 with the common 1.2 kOhm PROG resistor"
    elif re.search(r"bq2407|power.?path", cname, re.I):
        # power path: the 500 mA input limit is shared by the system load and the charge
        i_set = max(0.0, min(0.5, 0.5 - i_sys))
        how = "power-path charger in USB500 mode (input limit shared with the system)"
    else:
        i_set = max(0.0, min(0.5, 0.5 - i_sys))
        how = "charge current not known for this part: assumed set to fit the 500 mA USB budget"
    deck = [
        "* USB charging a cell at 3.7 V",
        "Vusb usb 0 DC 5.0",
        "Rcable usb vbus 0.3",
        "Vbat cell 0 DC 3.7",
        f"Resr bat cell {ESR_BATT_OHM}",
        f"Bchg vbus bat I = min({i_set}, max(0, (V(vbus) - V(bat) - 0.15) / 0.4))",
        f"Isys vbus 0 {i_sys:.4f}",
    ]
    try:
        res = _run(deck, ["op"])[0]
    except SimError as e:
        return _result(tid, name, "fail", f"ngspice rejected the deck: {e}", log=str(e))
    vbus = res["vbus"][0]
    vbat = res["bat"][0]
    i_usb = abs(res.get("vusb#branch", [0.0])[0])
    i_chg = min(i_set, max(0.0, (vbus - vbat - 0.15) / 0.4))
    c_rate = i_chg * 1000 / batt["mah"]
    p_chg = (vbus - vbat) * i_chg
    problems = []
    if i_usb > 0.505:
        problems.append(
            f"draws {i_usb * 1000:.0f} mA from USB, over the 500 mA a USB 2.0 port gives"
        )
    if c_rate > 1.0:
        problems.append(f"charges at {c_rate:.2f} C, over the cell's 1 C")
    warn = p_chg > 1.0
    status = "fail" if problems else "warn" if warn else "pass"
    summary = (
        f"charges at {i_chg * 1000:.0f} mA ({c_rate:.2f} C of {batt['mah']:.0f} mAh), "
        f"USB draw {i_usb * 1000:.0f} mA, charger dissipates {p_chg:.2f} W"
    )
    if problems:
        summary += "; " + "; ".join(problems)
    elif warn:
        summary += "; the linear charger will run hot and throttle"
    return _result(
        tid,
        name,
        status,
        summary,
        numbers={
            "charge_ma": round(i_chg * 1000, 1),
            "c_rate": round(c_rate, 3),
            "usb_ma": round(i_usb * 1000, 1),
            "vbus_v": round(vbus, 3),
            "charger_w": round(p_chg, 3),
            "capacity_mah": batt["mah"],
        },
        assumptions=[how, f"cell capacity from {batt['source']}", "0.3 ohm USB cable"],
        log="\n".join(deck),
    )


def run_all(io: dict[str, Any], debounce_ms: int) -> list[dict[str, Any]]:
    board = BOARDS.get(io["mcu"]["board_id"]) or BOARDS["nice_nano_v2"]
    out = []
    for fn in (rail_check, led_check, debounce_check, charger_check):
        t0 = time.monotonic()
        try:
            r = debounce_check(io, board, debounce_ms) if fn is debounce_check else fn(io, board)
        except (SimError, OSError) as e:
            r = _result(f"spice.{fn.__name__}", fn.__name__, "fail", f"ngspice: {e}", log=str(e))
        r["seconds"] = round(time.monotonic() - t0, 3)
        out.append(r)
    return out


CHECKS = {
    "spice.rail": rail_check,
    "spice.led": led_check,
    "spice.debounce": debounce_check,
    "spice.charger": charger_check,
}
