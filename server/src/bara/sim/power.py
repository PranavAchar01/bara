"""Power tree of a board plan -> SPICE deck -> ngspice results.

The deck is built from the plan's own netlist: the battery (or USB) source with internal
resistance, the power switch as a contact resistance, the regulator host as a behavioural LDO
(dropout resistance + quiescent current), every other part on the rail as a current sink from
its catalog `electrical.i_typ_a` (role defaults when the record has none), real R, C and
discrete LED elements, and one pressed key behind its matrix diode with the MCU pull-up.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .ngspice import Result, SimError, get_engine

GND_NETS = {"GND", "AGND", "GNDA", "VSS"}
RAIL_NETS = ("3V3", "+3V3", "VCC", "VDD", "3.3V")
SOURCE_PREFIX = ("BAT", "VBAT", "VBUS", "VIN", "5V", "USB")

# (typical A, sleep A, max A) when neither the part record nor its datasheet fields give one.
ROLE_DEFAULTS: dict[str, tuple[float, float, float]] = {
    "mcu": (3.0e-3, 30e-6, 15e-3),  # nRF52840 BLE keyboard, advertising + scan average
    "display": (8.0e-3, 10e-6, 20e-3),  # SSD1306 0.96 in, mostly text
    "ws_led": (1.0e-3, 1.0e-3, 12e-3),  # WS2812-class quiescent, cannot sleep unless gated
    "sensor": (15e-3, 0.5e-3, 25e-3),  # PMW33xx class optical sensor
    "sdcard": (2.0e-3, 0.1e-3, 30e-3),
    "other": (0.1e-3, 10e-6, 1e-3),
}
PULLUP_OHM = 13_000.0  # nRF52 internal pull-up, nominal
ESR_BATT_OHM = 0.35  # small LiPo, aged
R_SWITCH_OHM = 0.05
LDO_DROPOUT_V = 0.25  # at LDO_DROPOUT_AT_A, the usual 600 mA class LDO
LDO_DROPOUT_AT_A = 0.6
LDO_IQ_A = 55e-6
USABLE_CAPACITY = 0.8
DEFAULT_CAPACITY_MAH = 110.0
V_FULL, V_NOM, V_CUTOFF = 4.2, 3.7, 3.0
TX_BURST_A = 10e-3


@dataclass
class Load:
    ref: str
    kind: str
    node: str
    typ: float
    sleep: float
    peak: float
    source: str  # "catalog" | "assumed"


@dataclass
class PowerModel:
    gnd: str = "GND"
    rail: str = ""
    v_rail: float = 3.3
    src_net: str = ""  # battery or USB positive net
    in_net: str = ""  # regulator input net (after the switch)
    src_kind: str = ""  # battery | usb
    capacity_mah: float = DEFAULT_CAPACITY_MAH
    capacity_source: str = "assumed"
    v_cutoff: float = V_CUTOFF
    v_floor: float = 0.0
    host_ref: str = ""
    host_i_max: float = 0.1
    iq: float = LDO_IQ_A
    loads: list[Load] = field(default_factory=list)
    elements: list[str] = field(default_factory=list)  # R, C, LED, matrix path (real nets)
    notes: list[str] = field(default_factory=list)
    led_missing_resistor: list[str] = field(default_factory=list)
    led_nets: dict[str, tuple[str, str]] = field(default_factory=dict)
    led_series: dict[str, tuple[str, str, str, float] | None] = field(default_factory=dict)
    resistors: list[tuple[str, str, str, float]] = field(default_factory=list)
    switch: tuple[str, str] | None = None
    caps_f: float = 0.0


def node(net: str, gnd: str = "GND") -> str:
    if net == gnd or net in GND_NETS:
        return "0"
    return "n_" + re.sub(r"[^a-z0-9]+", "_", net.lower().replace("+", "p"))


def _val(text: str) -> float | None:
    """'100 nF 0805' / '4.7k' / '330R' -> SI value."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*(p|n|u|µ|m|k|M|G)?\s*([FfRrΩ]|ohm)?", text)
    if not m:
        return None
    mult = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3, "k": 1e3, "M": 1e6, "G": 1e9}
    return float(m.group(1)) * mult.get(m.group(2) or "", 1.0)


def kind_of(fp: dict) -> str:
    lib = fp.get("lib_id", "").lower()
    val = fp.get("value", "").lower()
    ref = fp.get("ref", "")
    blob = f"{lib} {val}"
    if ref.startswith("SW_PWR") or "power switch" in val:
        return "pwr_switch"
    if "battery" in val or lib.startswith(("connector_jst", "battery")) and "bat" in blob:
        return "battery"
    if "usb" in lib and any("VBUS" in n for n in fp.get("pads", {}).values()):
        return "usb"
    if lib.startswith("diode") or re.search(r"1n4148|1n914|bat54", val):
        return "diode"
    if lib.startswith("capacitor"):
        return "cap"
    if lib.startswith("resistor"):
        return "res"
    if re.search(r"ws2812|sk6812|neopixel", blob):
        return "ws_led"
    if lib.startswith("led_"):
        return "led"
    if re.search(r"oled|ssd1306|display|lcd", blob):
        return "display"
    if re.search(r"pmw|optical|sensor", blob):
        return "sensor"
    if re.search(r"microsd|card", blob):
        return "sdcard"
    if re.search(r"nice.?nano|promicro|pro_micro|xiao|mcu|esp32", blob):
        return "mcu"
    if re.search(r"encoder|rotary", blob):
        return "encoder"
    if ref.startswith("SW"):
        return "key"
    return "other"


def _record_for(fp: dict, parts: list[dict]) -> dict:
    """Merge the electrical/facets of the catalog record that matches this footprint."""
    want_name = fp.get("value", "").lower()
    want_lib = fp.get("lib_id", "")
    for p in parts or []:
        cands = [p, p.get("record") or {}, p.get("card") or {}]
        names = {str(c.get("display_name", "")).lower() for c in cands} | {
            str(c.get("name", "")).lower() for c in cands
        }
        libs = {str(c.get("footprint", "")) for c in cands}
        if (want_name and want_name in names) or (want_lib and want_lib in libs):
            out: dict[str, Any] = {}
            for c in cands:
                out.update(c.get("facets") or {})
                out.update(c.get("electrical") or {})
                if c.get("spice_model"):
                    out["spice_model"] = c["spice_model"]
            return out
    return {}


def _battery_record(parts: list[dict]) -> dict:
    for p in parts or []:
        cands = [p, p.get("record") or {}, p.get("card") or {}]
        key = " ".join(str(c.get("key", "")) + str(c.get("part_id", "")) for c in cands).lower()
        if "lipo" in key or "battery" in key and "holder" not in key and "conn" not in key:
            out: dict[str, Any] = {}
            for c in cands:
                out.update(c.get("facets") or {})
                out.update(c.get("electrical") or {})
            return out
    return {}


def build_model(plan: dict, parts: list[dict]) -> PowerModel | None:
    fps = plan.get("footprints", [])
    m = PowerModel()
    nets = set(plan.get("nets", []))
    m.rail = next((n for n in RAIL_NETS if n in nets), "")
    kinds = {fp["ref"]: kind_of(fp) for fp in fps}

    # source: battery connector or USB, positive pad = the one not on ground
    for fp in fps:
        k = kinds[fp["ref"]]
        if k in ("battery", "usb"):
            pos = [n for n in fp["pads"].values() if n not in GND_NETS]
            if pos:
                m.src_net, m.src_kind = pos[0], "battery" if k == "battery" else "usb"
                break
    if not m.src_net or not m.rail:
        return None
    m.in_net = m.src_net
    for fp in fps:
        if kinds[fp["ref"]] == "pwr_switch":
            a, b = (n for n in fp["pads"].values())
            if m.src_net in (a, b):
                m.in_net = b if a == m.src_net else a
                m.switch = (m.src_net, m.in_net)

    # regulator host: the module with pads on both the input net and the rail
    host = next(
        (
            fp
            for fp in fps
            if kinds[fp["ref"]] == "mcu"
            and m.in_net in fp["pads"].values()
            and m.rail in fp["pads"].values()
        ),
        None,
    )
    if host is None:
        return None
    m.host_ref = host["ref"]
    hrec = _record_for(host, parts)
    m.v_rail = float(hrec.get("v_logic_v") or 3.3)
    m.v_floor = 0.85 * m.v_rail
    m.v_cutoff = float(hrec.get("v_in_min_v") or V_CUTOFF)
    m.host_i_max = float(hrec.get("i_max_a") or 0.1)
    m.iq = float(hrec.get("iq_a") or LDO_IQ_A)

    if m.src_kind == "battery":
        brec = _battery_record(parts)
        cap = brec.get("capacity_mah")
        if cap:
            m.capacity_mah, m.capacity_source = float(cap), "catalog"

    for fp in fps:
        k = kinds[fp["ref"]]
        ref = fp["ref"]
        nets_of = list(fp["pads"].items())
        if k == "cap":
            c = _val(fp["value"])
            a = [n for _, n in nets_of]
            if c and len(a) >= 2 and any(n in GND_NETS for n in a):
                m.elements.append(f"C_{ref} {node(a[0])} {node(a[1])} {c:.6g}")
                if m.rail in a:
                    m.caps_f += c
            continue
        if k == "res":
            r = _val(fp["value"])
            a = [n for _, n in nets_of]
            if r and len(a) >= 2:
                m.elements.append(f"R_{ref} {node(a[0])} {node(a[1])} {r:.6g}")
                m.resistors.append((ref, a[0], a[1], r))
            continue
        if k == "led":
            pads = fp["pads"]
            kat, ano = pads.get("1"), pads.get("2")
            if kat and ano:
                m.elements.append(f"D_{ref} {node(ano)} {node(kat)} DLED")
                m.led_nets[ref] = (ano, kat)
            continue
        if k in ("pwr_switch", "battery", "usb", "diode", "key", "encoder"):
            continue
        if m.rail not in fp["pads"].values() and ref != m.host_ref:
            continue
        rec = _record_for(fp, parts)
        typ, slp, peak = ROLE_DEFAULTS.get(k, ROLE_DEFAULTS["other"])
        src = "assumed"
        if rec.get("i_typ_a") is not None:
            typ, src = float(rec["i_typ_a"]), "catalog"
            slp = float(rec.get("i_sleep_a", slp))
            peak = float(rec.get("i_max_a", max(peak, typ)))
        m.loads.append(Load(ref, k, node(m.rail), typ, slp, peak, src))

    for led, (ano, kat) in m.led_nets.items():
        link = next((r for r in m.resistors if ({ano, kat} - GND_NETS) & {r[1], r[2]}), None)
        m.led_series[led] = link
        if link is None:
            m.led_missing_resistor.append(led)
    _matrix_path(m, fps, kinds)
    return m


def _matrix_path(m: PowerModel, fps: list[dict], kinds: dict[str, str]) -> None:
    """One held key: COL pull-up -> switch -> diode -> ROW driven low."""
    for sw in fps:
        if kinds[sw["ref"]] != "key":
            continue
        nets = list(sw["pads"].values())
        col = next((n for n in nets if n.startswith("COL")), None)
        knet = next((n for n in nets if n != col and n not in GND_NETS), None)
        if not col or not knet:
            continue
        for d in fps:
            if kinds[d["ref"]] == "diode" and knet in d["pads"].values():
                row = next((n for n in d["pads"].values() if n != knet), None)
                if row:
                    a, c = (d["pads"].get("2"), d["pads"].get("1"))
                    anode, cathode = (a, c) if a and a == knet else (c, a)
                    m.elements += [
                        f"Rpu {node(col)} {node(m.rail)} {PULLUP_OHM}",
                        f"Rkey_{sw['ref']} {node(col)} {node(knet)} 0.05",
                        f"D_{d['ref']} {node(anode)} {node(cathode)} D1N4148",
                        f"Vrow {node(row)} 0 DC 0",
                    ]
                    m.notes.append(f"key held: {sw['ref']} via {d['ref']} on {col}/{row}")
                    return


def build_deck(m: PowerModel, vbat: float, mode: str = "typ", tran: bool = False) -> list[str]:
    """mode: typ | sleep | peak. tran adds soft start, a battery sag and a TX burst."""
    rail, n_in, n_src = node(m.rail), node(m.in_net), node(m.src_net)
    rdo = LDO_DROPOUT_V / LDO_DROPOUT_AT_A
    d = [
        "* bara power tree",
        ".model D1N4148 D(IS=2.52n RS=0.568 N=1.752 CJO=4p M=0.4 TT=20n BV=100 IBV=100u)",
        ".model DLED D(IS=1e-18 N=1.9 RS=5)",
    ]
    if tran:
        # switch-on edge, flat, then a compressed discharge down to cutoff
        d.append(
            f"Vbat bat_int 0 PWL(0 0 20e-6 {vbat} 1e-3 {vbat} 3e-3 {m.v_cutoff} 4e-3 {m.v_cutoff})"
        )
        start = "min(1,time/100e-6)"
    else:
        d.append(f"Vbat bat_int 0 DC {vbat}")
        start = "1"
    d.append(f"Rint bat_int {n_src} {ESR_BATT_OHM}")
    if m.switch:
        d.append(f"Rsw {n_src} {n_in} {R_SWITCH_OHM}")
    d += [
        f"Bldo regint 0 V = min({m.v_rail},v({n_in}))*{start}",
        f"Rdo regint regout {rdo:.4g}",
        f"Vsns regout {rail} 0",
        f"Bq {n_in} 0 I = i(Vsns)+{m.iq}",
    ]
    for ld in m.loads:
        i = {"typ": ld.typ, "sleep": ld.sleep, "peak": ld.peak}[mode]
        d.append(f"B_{ld.ref} {rail} 0 I = {i:.6g}*min(1,max(v({rail}),0)/2)")
    if tran:
        d.append(f"Bburst {rail} 0 I = {TX_BURST_A}*(u(time-3.2e-3)-u(time-3.4e-3))")
    d += m.elements
    d.append(".options reltol=1e-4")
    return d


def _g(res: Result, key: str) -> list[float]:
    if key in res:
        return res[key]
    raise SimError(f"vector {key} missing from ngspice output")


@dataclass
class Point:
    vbat: float
    mode: str
    v_rail: float
    i_batt: float
    i_rail: float
    v_in: float


def solve_op(m: PowerModel, vbat: float, mode: str) -> Point:
    (res,) = get_engine().run(build_deck(m, vbat, mode), ["op"])
    v_in = _g(res, node(m.in_net))[0]
    return Point(
        vbat=vbat,
        mode=mode,
        v_rail=_g(res, node(m.rail))[0],
        i_batt=-_g(res, "vbat#branch")[0],
        i_rail=_g(res, "vsns#branch")[0],
        v_in=v_in,
    )


@dataclass
class TranResult:
    v_rail_min: float
    v_rail_final: float
    i_batt_peak: float
    i_rail_peak: float
    t_brownout: float | None


def solve_tran(m: PowerModel, vbat: float) -> TranResult:
    (res,) = get_engine().run(build_deck(m, vbat, "typ", tran=True), ["tran 2u 4m"])
    t = _g(res, "time")
    v = _g(res, node(m.rail))
    ib = [-x for x in _g(res, "vbat#branch")]
    ir = _g(res, "vsns#branch")
    # ignore the start-up ramp when looking for brown-out; it is judged by the final level
    settle = [(ti, vi) for ti, vi in zip(t, v, strict=True) if ti >= 0.4e-3]
    below = next((ti for ti, vi in settle if vi < m.v_floor), None)
    return TranResult(
        v_rail_min=min(vi for _, vi in settle),
        v_rail_final=v[-1],
        i_batt_peak=max(ib),
        i_rail_peak=max(ir),
        t_brownout=below,
    )
