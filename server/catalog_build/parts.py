"""Manifest entry + KiCad files + mesh record -> one SPEC 4.1 Part, plus its KiCad block.

Every value is read from an upstream file (footprint pads and courtyard, symbol pin names
and properties, the exported GLB's bounds) or copied from the manifest, where the few
hand-entered values live. Nothing is guessed: a value that no source gives is left out,
and an interface whose required parameter is unknown is typed "unknown" so the
data.interface_unknown check can flag it.
"""

from __future__ import annotations

import copy
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from .build import plan_entry
from .kicad_lib import Footprint, Symbol, read_symbol
from .manifest import Entry
from .resolve import Resolved, footprint_lib_id, resolve_symbol
from .sources import SOURCES, Licence

OVERLAY = Path(__file__).resolve().parent.parent / "data/catalog/parts_overlay.json"


@lru_cache(maxsize=1)
def _overlay() -> dict[str, dict[str, Any]]:
    """Hand-authored interfaces and facets for the parts the spec fixtures use."""
    if not OVERLAY.is_file():
        return {}
    return json.loads(OVERLAY.read_text()).get("parts", {})


def _hand_interfaces(e: Entry) -> tuple[list[dict[str, Any]], list[str]]:
    """Manifest interfaces, then overlay interfaces of a type the manifest lacks."""
    out = [copy.deepcopy(i) for i in e.interfaces]
    types = {i["type"] for i in out}
    ids = {i["id"] for i in out}
    from_overlay: list[str] = []
    for i in _overlay().get(e.part_id, {}).get("interfaces", []):
        if i["type"] in types or i["id"] in ids:
            continue
        out.append(copy.deepcopy(i))
        ids.add(i["id"])
        from_overlay.append(i["id"])
    return out, from_overlay


ELECTRICAL_KEYS = ("v_in_min_v", "v_in_max_v", "v_logic_v", "i_typ_a", "i_max_a", "i_sleep_a")
STEM = {"mx": "mx_cross", "choc_v1": "choc_v1", "choc_v2": "choc_v2", "alps": "alps"}
SWITCH_FAMILIES = {"mx", "choc_v1", "choc_v2", "alps", "gateron_lp", "other"}
FORM_FACTORS = {
    "pro_micro",
    "elite_c",
    "feather",
    "pico",
    "xiao",
    "itsybitsy",
    "qt_py",
    "arduino_uno",
    "arduino_nano",
    "rpi_40pin",
    "esp32_devkit",
    "d1_mini",
}
GROUND = re.compile(r"^(A|D|P)?GND\d*$|^VSS[A-Z]*$|^EP$|^PAD$|^SHIELD$")
GPIO = re.compile(r"^(P[A-K]?\d{1,2}(\.\d{1,2})?|GPIO?\d{1,2}|IO\d{1,2}|D\d{1,2}|P\d_\d{1,2})$")
ANALOG = re.compile(r"^(A\d{1,2}|ADC\d{0,2})$")
USB_FUNCS = {"power.usb_in", "interconnect.connector", "comms.usb_device", "compute.mcu"}


def _tokens(name: str) -> set[str]:
    clean = re.sub(r"~\{([^}]*)\}", r"\1", name).upper()
    return {t for t in re.split(r"[/,\s]+", clean) if t}


def _find(pins: dict[str, set[str]], *names: str) -> str | None:
    for num, toks in pins.items():
        if toks & set(names):
            return num
    return None


def _iface(iid: str, typ: str, role: str, label: str, params: dict[str, Any], **kw: Any) -> dict:
    rec: dict[str, Any] = {"id": iid, "type": typ, "role": role, "label": label[:60]}
    rec["params"] = params
    rec["pins"] = kw.pop("pins", [])
    rec.update(kw)
    return rec


def _bus(
    iid: str,
    typ: str,
    role: str,
    label: str,
    v_logic: float | None,
    signals: dict[str, str],
    extra: dict[str, Any] | None = None,
) -> dict:
    pins = sorted(set(signals.values()), key=_natural)
    if v_logic is None:
        return _iface(
            iid,
            "unknown",
            role,
            f"{label} (logic voltage not in source)",
            {"bus": typ},
            pins=pins,
            signals=signals,
        )
    return _iface(
        iid, typ, role, label, {"v_logic_v": v_logic, **(extra or {})}, pins=pins, signals=signals
    )


def _natural(s: str) -> list[Any]:
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


def derive_interfaces(
    e: Entry, sym: Symbol | None, fp: Footprint | None, text: str
) -> list[dict[str, Any]]:
    """Interfaces from symbol pin names and the manifest facets (deterministic rules)."""
    out: list[dict[str, Any]] = []
    funcs = {e.function, *e.more_functions}
    is_mcu = "compute.mcu" in funcs
    host_role = "provides" if is_mcu else "requires"
    v_logic = e.electrical.get("v_logic_v")
    pins = {p.number: _tokens(p.name) for p in (sym.pins if sym else [])}
    used: set[str] = set()

    sda = _find(pins, "SDA")
    scl = _find(pins, "SCL")
    if not (sda and scl) and "I2C" in text:
        sda = sda or _find(pins, "SDI", "SDA/SDI")
        scl = scl or _find(pins, "SCK", "SCLK")
    if sda and scl:
        out.append(_bus("i2c0", "i2c", host_role, "I2C", v_logic, {"SDA": sda, "SCL": scl}))
        used |= {sda, scl}

    mosi = _find(pins, "MOSI", "COPI", "SDI", "DIN", "SI")
    sck = _find(pins, "SCK", "SCLK", "CLK")
    cs = _find(pins, "CS", "CSB", "SS", "NSS", "CSN", "NCS", "CS0")
    miso = _find(pins, "MISO", "CIPO", "SDO", "DOUT", "SO")
    if mosi and sck and (cs or is_mcu) and "output.rgb_led" not in funcs:
        sig = {"MOSI": mosi, "SCK": sck}
        if miso:
            sig["MISO"] = miso
        if cs:
            sig["CS"] = cs
        out.append(_bus("spi0", "spi", host_role, "SPI", v_logic, sig))
        used |= set(sig.values())

    tx = _find(pins, "TX", "TXD", "TXD0", "TX0")
    rx = _find(pins, "RX", "RXD", "RXD0", "RX0")
    if tx and rx:
        out.append(_bus("uart0", "uart", host_role, "UART", v_logic, {"TX": tx, "RX": rx}))
        used |= {tx, rx}

    dp = _find(pins, "D+", "DP", "USB_D+", "USBDP", "USB_DP", "D+_A", "DP1")
    dm = _find(pins, "D-", "DM", "USB_D-", "USBDM", "USB_DM", "D-_A", "DN1")
    if dp and dm:
        name = (fp.name if fp else "").lower()
        conn = (
            "usb_c"
            if "usb_c" in name or "type-c" in name or "typec" in name
            else "micro_b"
            if "micro" in name
            else "mini_b"
            if "mini" in name
            else "usb_a"
            if "usb_a" in name
            else "other"
        )
        role = "provides" if funcs & USB_FUNCS else "requires"
        out.append(
            _iface("usb", "usb", role, "USB", {"connector": conn}, pins=[dp, dm])
            | {"signals": {"D+": dp, "D-": dm}}
        )
        used |= {dp, dm}

    if "output.rgb_led" in funcs:
        din = _find(pins, "DIN", "DI")
        dout = _find(pins, "DOUT", "DO")
        low = f"{e.part_id} {e.name}".lower()
        proto = next((p for p in ("ws2812", "sk6812", "apa102") if p in low), None)
        if din and proto:
            sig = {"DIN": din} | ({"DOUT": dout} if dout else {})
            params: dict[str, Any] = {"protocol": proto}
            if v_logic is not None:
                params["v_logic_v"] = v_logic
            out.append(
                _iface("led_data", "addressable_led", "requires", "LED data in", params, pins=[din])
                | {"signals": sig}
            )
            used |= set(sig.values())

    if is_mcu or "component.ic" in funcs:
        gp = sorted(
            (n for n, t in pins.items() if n not in used and any(GPIO.match(x) for x in t)),
            key=_natural,
        )
        if gp:
            params = {"count": len(gp)}
            if v_logic is not None:
                params["v_logic_v"] = v_logic
            out.append(_iface("gpio", "gpio", "provides", "GPIO", params, pins=gp))
        an = sorted((n for n, t in pins.items() if any(ANALOG.match(x) for x in t)), key=_natural)
        if an and is_mcu:
            out.append(
                _iface("adc", "analog", "provides", "Analog in", {"count": len(an)}, pins=an)
            )

    supply = sorted(
        (
            p.number
            for p in (sym.pins if sym else [])
            if p.etype == "power_in" and not any(GROUND.match(t) for t in _tokens(p.name))
        ),
        key=_natural,
    )
    if supply:
        lo, hi = e.electrical.get("v_in_min_v"), e.electrical.get("v_in_max_v")
        names = ", ".join(sorted({p.name for p in sym.pins if p.number in supply}))[:30]  # type: ignore[union-attr]
        if lo is not None and hi is not None:
            out.append(
                _iface(
                    "vin",
                    "power_in",
                    "requires",
                    f"Supply ({names})",
                    {"v_min_v": lo, "v_max_v": hi},
                    pins=supply,
                )
            )
        else:
            out.append(
                _iface(
                    "supply",
                    "unknown",
                    "requires",
                    f"Supply ({names}), range not in source",
                    {"signal": "supply"},
                    pins=supply,
                )
            )

    fam = e.facets.get("switch_family")
    fam = fam if isinstance(fam, str) else None
    if fam:
        family = fam if fam in SWITCH_FAMILIES else "other"
        if e.function == "input.key":
            out.append(
                _iface("socket", "switch_socket", "requires", "Needs a socket", {"family": family})
            )
            out.append(
                _iface(
                    "stem",
                    "switch_stem",
                    "provides",
                    "Switch stem",
                    {"stem": STEM.get(fam, "other"), "family": family},
                )
            )
        elif e.function == "mech.keycap":
            out.append(
                _iface(
                    "stem",
                    "switch_stem",
                    "requires",
                    "Fits switch stem",
                    {"stem": STEM.get(fam, "other"), "family": family},
                )
            )
        elif e.function == "mech.plate":
            out.append(
                _iface("cutouts", "plate_cutout", "provides", "Switch cutouts", {"family": family})
            )
        elif e.part_id.startswith(("hs:", "sock:")) or e.facets.get("hotswap") is True:
            params = {"family": family}
            if isinstance(e.facets.get("hotswap"), bool):
                params["hotswap"] = e.facets["hotswap"]
            out.append(_iface("socket", "switch_socket", "provides", "Switch socket", params))

    screw = e.facets.get("screw")
    if e.function in ("mech.standoff", "mech.fastener") and isinstance(screw, str):
        params = {"thread": screw}
        for key in ("standoff_height_mm", "length_mm"):
            if isinstance(e.facets.get(key), int | float):
                params[key] = e.facets[key]
        out.append(_iface("thread", "fastener", "provides", f"{screw} thread", params))

    ff = e.facets.get("module_footprint")
    if isinstance(ff, str) and e.kind == "module":
        params = {"form_factor": ff if ff in FORM_FACTORS else "other"}
        if fp is not None and fp.pin_numbers:
            params["pin_count"] = len(fp.pin_numbers)
        out.append(_iface("footprint", "module_footprint", "requires", f"{ff} footprint", params))
    return out


def _merge(hand: list[dict[str, Any]], derived: list[dict[str, Any]], e: Entry) -> list:
    default_role = {"power_in": "requires", "battery": "requires", "jack": "provides"}
    out: list[dict[str, Any]] = []
    for i in hand:
        rec = dict(i)
        rec.setdefault("role", default_role.get(rec["type"], "provides"))
        rec.setdefault("pins", [])
        out.append(rec)
    have_types = {i["type"] for i in out}
    have_ids = {i["id"] for i in out}
    for d in derived:
        if d["type"] in have_types or (
            d["type"] == "unknown" and d["id"] == "supply" and "power_in" in have_types
        ):
            continue
        iid = d["id"]
        n = 1
        while iid in have_ids:
            iid = f"{d['id']}{n}"
            n += 1
        d["id"] = iid
        have_ids.add(iid)
        out.append(d)
    return out


def _licence(rec: dict[str, Any] | None, fp_src: Resolved | None) -> dict[str, Any]:
    if rec and rec.get("licence"):
        lic = dict(rec["licence"])
        parts = lic.pop("parts", None)
        if parts:
            each = "; ".join(f"{p['spdx']} ({p.get('url') or 'no url'})" for p in parts)
            lic["notes"] = f"{lic.get('notes') or ''} Components: {each}.".strip()
        return lic
    if fp_src is not None:
        return fp_src.licence.as_record()
    return Licence(
        "NOASSERTION", "No licence recorded", None, "unknown", "unknown", "unknown"
    ).as_record()


def _material(e: Entry) -> str | None:
    return "pcb" if e.kind in ("pcb", "module") else None


def build_part(e: Entry, mesh: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    plan = plan_entry(e)
    fp = plan.fp
    sym: Symbol | None = None
    sym_res: Resolved | None = None
    if e.symbol:
        sym_res, name = resolve_symbol(e.symbol)
        sym = read_symbol(sym_res.path, name)
    props = sym.properties if sym else {}
    descr = props.get("Description") or props.get("ki_description") or (fp.descr if fp else "")
    kw = props.get("ki_keywords") or (fp.tags if fp else "")
    text = f"{descr} {kw}".upper()

    part: dict[str, Any] = {"key": e.part_id}
    if sym:
        part["lib_id"] = sym.lib_id
    if plan.footprint is not None and e.footprint:
        part["footprint"] = footprint_lib_id(e.footprint, plan.footprint)
    part["family"] = e.part_id.split(":", 1)[0]
    part["name"] = sym.name if sym else (fp.name if fp else e.name)
    if descr:
        part["descr"] = descr
    if kw:
        part["kw"] = kw
    if sym and sym.pins:
        part["pins"] = sym.pin_map()
    part["pads_ok"] = bool(fp and fp.pads)
    model_files = [s for s in (mesh or {}).get("sources", []) if s.get("role") == "model"]
    part["model"] = model_files[0]["file"] if model_files else None
    datasheet = e.datasheet or props.get("Datasheet") or ""
    part["datasheet"] = "" if datasheet in ("~", "") else datasheet
    src_key = (
        plan.footprint.source.key
        if plan.footprint
        else (plan.board.source.key if plan.board else None)
    )
    part["source"] = "kicad-lib" if src_key in ("kicad", None) else f"extra:{src_key}"
    part["tags"] = sorted({e.function.split(".")[0], *(t for t in kw.lower().split() if t)})[:24]
    part["fp_ok"] = fp is not None

    part["part_id"] = e.part_id
    part["kind"] = e.kind
    part["display_name"] = e.name[:80]
    part["mpn"] = e.mpn
    part["manufacturer"] = e.manufacturer
    part["summary"] = e.summary or (descr[:200] if descr else None)
    part["functions"] = [{"function_id": e.function, "primary": True}] + [
        {"function_id": f, "primary": False} for f in e.more_functions
    ]
    hand, overlay_ids = _hand_interfaces(e)
    part["interfaces"] = _merge(hand, derive_interfaces(e, sym, fp, text), e)
    elec = {k: v for k, v in e.electrical.items() if k in ELECTRICAL_KEYS}
    if elec:
        part["electrical"] = elec

    mech: dict[str, Any] = {}
    status = (mesh or {}).get("status", "missing")
    if mesh and mesh.get("bbox_mm") and status in ("ok", "proxy"):
        mech["bbox_mm"] = mesh["bbox_mm"]
    if e.standards:
        mech["standards"] = list(e.standards)
    feats = []
    if fp:
        for i, pad in enumerate(fp.pads):
            x, y, _ = pad.at
            kind = "hole" if pad.kind == "np_thru_hole" else "pad"
            feat: dict[str, Any] = {
                "id": f"pad{i}_{pad.number}" if pad.number else f"hole{i}",
                "kind": kind,
                "subtype": pad.kind,
                "pos_mm": [round(x, 4), round(-y, 4), 0.0],
            }
            if pad.drill is not None:
                feat["diameter_mm"] = round(pad.drill, 4)
            feats.append(feat)
    if feats:
        mech["mating_features"] = feats
    if mech:
        part["mechanical"] = mech

    render: dict[str, Any] = {}
    if e.color:
        render["default_color"] = e.color
    if (m := _material(e)) is not None:
        render["material"] = m
    if render:
        part["render"] = render

    stem = ((mesh or {}).get("url") or "").rsplit("/", 1)[-1].removesuffix(".glb")
    asset: dict[str, Any] = {
        "asset_id": f"a_{stem or e.part_id.split(':', 1)[1]}_glb",
        "kind": "glb",
        "role": "model",
        "url": (mesh or {}).get("url") or f"/assets/parts/{e.part_id.split(':', 1)[1]}.glb",
        "content_type": "model/gltf-binary",
        "status": "ready" if status in ("ok", "proxy") else "missing",
        "origin": "catalog",
    }
    if status in ("ok", "proxy") and mesh:
        asset["bytes"] = mesh["bytes"]
        asset["sha256"] = mesh["sha256"]
        asset["nodes"] = mesh.get("nodes", [])
    part["assets"] = [asset]

    lic = _licence(mesh, plan.footprint)
    part["licence"] = lic
    route_src = plan.footprint or plan.board
    prov: dict[str, Any] = {
        "route": route_src.source.route if route_src else "open_model",
        "licence": lic.get("name", lic["spdx"]),
        "copyleft": lic.get("copyleft") == "yes",
        "attribution_required": None
        if lic.get("attribution_required") == "unknown"
        else lic.get("attribution_required") == "yes",
        "extractor": "kicad_parse",
        "verified": "geometry" if status == "ok" else "none",
    }
    if plan.footprint:
        prov["source_url"] = plan.footprint.url
        prov["commit"] = plan.footprint.source.commit
        prov["url"] = plan.footprint.source.url
    elif plan.board:
        prov["source_url"] = plan.board.url
        prov["commit"] = plan.board.source.commit
        prov["url"] = plan.board.source.url
    if sym_res:
        prov["symbol_url"] = sym_res.url
        prov["symbol"] = sym.lib_id if sym else ""
    if model_files:
        prov["model_url"] = model_files[0]["source_url"]
        if "source_url" not in prov:
            prov["source_url"] = model_files[0]["source_url"]
            prov["commit"] = model_files[0]["commit"]
    notes = list((mesh or {}).get("notes", []))
    if notes:
        prov["model_note"] = "; ".join(notes)
    if mesh and mesh.get("sha256") and status in ("ok", "proxy"):
        prov["sha256"] = mesh["sha256"]
    fs: dict[str, Any] = {}
    if "bbox_mm" in mech:
        fs["/mechanical/bbox_mm"] = {
            "extractor": "kicad_parse",
            "verified": "geometry" if status == "ok" else "third_party",
            "source_url": prov.get("model_url"),
        }
    if "pins" in part:
        fs["/pins"] = {
            "extractor": "kicad_parse",
            "verified": "geometry",
            "source_url": prov.get("symbol_url"),
        }
    for k in elec:
        fs[f"/electrical/{k}"] = {"extractor": "human", "verified": "none"}
    for i in hand:
        fs[f"/interfaces/{i['id']}"] = {"extractor": "human", "verified": "none"}
    part["provenance"] = prov

    facets: dict[str, Any] = dict(e.facets)
    for k, v in (_overlay().get(e.part_id, {}).get("facets") or {}).items():
        if k not in facets and k != "commercial_ok":
            facets[k] = copy.deepcopy(v)
            fs[f"/facets/{k}"] = {"extractor": "human", "verified": "none"}
    if overlay_ids:
        prov["model_note"] = (
            f"{prov.get('model_note', '')} Interfaces {', '.join(overlay_ids)} are hand-entered "
            "(server/data/catalog/parts_overlay.json)."
        ).strip()
    if fs:
        prov["field_sources"] = fs
    facets["kind"] = e.kind
    facets["has_mesh"] = status in ("ok", "proxy")
    facets["commercial_ok"] = lic["commercial_ok"]
    facets["licence_spdx"] = lic["spdx"]
    facets["interface_types"] = sorted({i["type"] for i in part["interfaces"]})
    if "v_logic_v" in elec:
        facets["v_logic_v"] = elec["v_logic_v"]
    if fp:
        attrs = set(fp.attrs)
        facets["mount"] = "smd" if "smd" in attrs else "tht" if "through_hole" in attrs else None
        facets["pin_count"] = len(fp.pin_numbers)
    if "bbox_mm" in mech:
        lo, hi = mech["bbox_mm"]["min"], mech["bbox_mm"]["max"]
        facets["width_mm"] = round(hi[0] - lo[0], 3)
        facets["depth_mm"] = round(hi[1] - lo[1], 3)
        facets["height_mm"] = round(hi[2], 3)
    if e.manufacturer:
        facets["manufacturer"] = e.manufacturer
    part["facets"] = {k: v for k, v in facets.items() if v is not None}
    part["status"] = "active"

    kicad: dict[str, Any] = {"part_id": e.part_id}
    if plan.footprint and fp:
        kicad["footprint"] = {
            "lib_id": part.get("footprint"),
            "path": str(plan.footprint.path),
            "source_url": plan.footprint.url,
            "attrs": fp.attrs,
            "courtyard_mm": fp.courtyard,
            "pads": [p.as_record() for p in fp.pads],
        }
    if plan.board:
        kicad["board"] = {"path": str(plan.board.path), "source_url": plan.board.url}
    if sym_res and sym:
        kicad["symbol"] = {
            "lib_id": sym.lib_id,
            "path": str(sym_res.path),
            "source_url": sym_res.url,
        }
    kicad["models"] = [
        {
            "path": s["file"],
            "source_url": s["source_url"],
            **({"kicad": s["kicad_model"]} if s.get("kicad_model") else {}),
            **({"placement": s["placement"]} if s.get("placement") else {}),
        }
        for s in model_files
    ]
    kicad["mesh"] = (
        {
            "status": status,
            "glb": mesh.get("glb"),
            "url": mesh.get("url"),
            "bbox_mm": mesh.get("bbox_mm"),
            "mesh_proxy_of": mesh.get("mesh_proxy_of"),
        }
        if mesh
        else {"status": "missing"}
    )
    kicad["source_key"] = src_key
    if src_key:
        kicad["source_commit"] = SOURCES[src_key].commit
    return part, kicad
