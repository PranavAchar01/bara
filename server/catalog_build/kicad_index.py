"""Index the whole KiCad library (plus kiswitch and marbastlib) as the "generated" tier.

    cd server
    # one-off build, under ~/helloworld/.heavy-lock:
    nice -n 19 uv run python -m catalog_build.kicad_index build
    uv run python -m catalog_build.kicad_index stats
    uv run python -m catalog_build.kicad_index prewarm [--limit 300]   # optional GLBs

Reads every .kicad_sym (symbol, description, keywords, default footprint, datasheet, pin
count, pin names) and every .kicad_mod (description, tags, pad count, 3D model), joins
symbol -> footprint -> 3D model, and writes

    data/catalog/kicad_index.jsonl     one row per symbol and per footprint
    data/catalog/kicad_index.sqlite    kicad_parts table + kicad_fts (FTS5)

Both files are large and gitignored: they are rebuilt from the installed libraries.
They live beside catalog.sqlite (not inside it) because ``catalog_build.build parts``
rewrites that file from scratch and it is committed. Nothing is converted to GLB here:
bara.kicad_generated converts one footprint on first request.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .sources import SOURCES

SERVER = Path(__file__).resolve().parent.parent
CATALOG = SERVER / "data/catalog"
INDEX_JSONL = CATALOG / "kicad_index.jsonl"
INDEX_SQLITE = CATALOG / "kicad_index.sqlite"

TIER = "kicad_generated"
KICAD_LICENCE_NAME = "CC-BY-SA-4.0 WITH KiCad library exception"

# (source key, folder under the source root that holds the libraries)
INDEXED = ("kicad", "kiswitch", "marbastlib")

_Q = r'"((?:[^"\\]|\\.)*)"'
_SYM_START = re.compile(r"^\t\(symbol " + _Q, re.M)
_PROP = re.compile(r"\(property " + _Q + r"\s+" + _Q)
_EXTENDS = re.compile(r"\(extends " + _Q + r"\)")
_PIN_NUM = re.compile(r"\(number " + _Q)
_PIN_NAME = re.compile(r"\n\t\t\t\t?\(name " + _Q)
_FP_DESCR = re.compile(r"\(descr " + _Q)
_FP_TAGS = re.compile(r"\(tags " + _Q)
_FP_ATTR = re.compile(r"\(attr ([a-z_ ]+)\)")
_FP_PAD = re.compile(r"\(pad " + _Q + r"\s+(\w+)")
_FP_MODEL = re.compile(r"\(model " + _Q)
_ESC = re.compile(r"\\(.)")
_MODEL_VAR = re.compile(r"^\$\{KICAD\d*_3DMODEL_DIR\}/(.*)$")


def say(*parts: object) -> None:
    sys.stdout.write(" ".join(str(p) for p in parts) + "\n")


def unescape(s: str) -> str:
    return _ESC.sub(lambda m: "\n" if m.group(1) == "n" else m.group(1), s)


# lib-name prefix -> function id (first match wins); symbols/footprints fall back to
# keyword rules and then to component.ic / other.
LIB_FUNCTIONS: tuple[tuple[str, str], ...] = (
    ("MCU_", "compute.mcu"),
    ("Module_Raspberry", "compute.sbc"),
    ("Module_Arduino", "compute.mcu"),
    ("Sensor_Motion", "sense.imu"),
    ("Sensor_Temperature", "sense.temperature"),
    ("Sensor_Humidity", "sense.humidity"),
    ("Sensor_Pressure", "sense.pressure"),
    ("Sensor_Proximity", "sense.proximity"),
    ("Sensor_Distance", "sense.distance"),
    ("Sensor_Optical", "sense.light"),
    ("Sensor_Magnetic", "sense.magnetic"),
    ("Sensor_Current", "sense.current"),
    ("Sensor_Gas", "sense.gas"),
    ("Sensor_Audio", "sense.sound"),
    ("Sensor_Touch", "input.touch"),
    ("Display_Character", "display.lcd_char"),
    ("Display_Graphic", "display.tft"),
    ("Regulator_", "power.regulator"),
    ("Battery_Management", "power.charger"),
    ("Battery", "power.battery"),
    ("Power_Protection", "power.protection"),
    ("Memory_Flash", "storage.flash"),
    ("Memory_EEPROM", "storage.eeprom"),
    ("Motor", "output.motor_dc"),
    ("Relay", "output.relay"),
    ("Buzzer", "output.buzzer"),
    ("Transistor_", "component.transistor"),
    ("Diode", "component.diode"),
    ("LED", "component.led"),
    ("Crystal", "component.crystal"),
    ("Oscillator", "component.crystal"),
    ("Resistor", "component.resistor"),
    ("Capacitor", "component.capacitor"),
    ("Inductor", "component.inductor"),
    ("RF_Bluetooth", "comms.ble"),
    ("RF_WiFi", "comms.wifi"),
    ("Interface_USB", "comms.usb_device"),
    ("Interface_Ethernet", "comms.ethernet"),
    ("Interface_CAN", "comms.can"),
    ("Connector_PinHeader", "interconnect.header"),
    ("Connector_PinSocket", "interconnect.header"),
    ("Connector", "interconnect.connector"),
    ("Button_Switch", "input.button"),
    ("Switch", "input.button"),
    ("Rotary_Encoder", "input.rotary_encoder"),
    ("MountingHole", "mech.fastener"),
    ("Fuse", "power.protection"),
)
KEYWORD_FUNCTIONS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(p, re.I), f)
    for p, f in (
        (r"\bjoystick\b|\bthumbstick\b", "input.joystick"),
        (r"\brotary encoder\b", "input.rotary_encoder"),
        (r"\btrackball\b", "input.trackball"),
        (r"\bpotentiometer\b", "input.potentiometer"),
        (r"\bkey ?switch\b|\bcherry mx\b|\bkailh\b", "input.key"),
        (r"\boled\b", "display.oled"),
        (r"\be-?paper\b|\beink\b", "display.epaper"),
        (r"\bspeaker\b", "output.speaker"),
        (r"\bbuzzer\b", "output.buzzer"),
        (r"\bservo\b", "output.motor_servo"),
        (r"\bstepper\b", "output.motor_stepper"),
        (r"\bimu\b|\bgyro|\baccelerometer\b", "sense.imu"),
        (r"\bcoin cell\b", "power.coin_cell"),
        (r"\bli-?po\b|\bli-?ion\b|\bbattery\b", "power.battery"),
        (r"\bsd card\b|\bmicrosd\b", "storage.sd_card"),
        (r"\braspberry pi\b", "compute.sbc"),
        (r"\bphoto ?(transistor|diode)\b|\bambient light\b", "sense.light"),
    )
)


def infer_function(lib: str, name: str, descr: str, keywords: str, kind: str) -> str:
    for prefix, fn in LIB_FUNCTIONS:
        if lib.startswith(prefix):
            return fn
    blob = f"{name} {descr} {keywords}"
    for rx, fn in KEYWORD_FUNCTIONS:
        if rx.search(blob):
            return fn
    return "component.ic" if kind == "symbol" else "other"


@dataclass
class Row:
    part_id: str
    kind: str  # symbol | footprint
    source: str
    lib: str
    name: str
    descr: str
    keywords: str
    datasheet: str
    function: str
    pins: int
    pads: int
    footprint: str  # "Lib:Name" as the symbol states it, or this footprint's own id
    footprint_part: str | None  # part_id of the joined footprint row
    fp_path: str | None  # relative to the source root
    model_source: str | None
    model_path: str | None  # relative to model_source root
    mount: str | None
    pin_names: list[str]
    filters: str

    @property
    def has_model(self) -> bool:
        return self.model_path is not None

    def as_record(self) -> dict[str, Any]:
        rec = {k: getattr(self, k) for k in self.__dataclass_fields__}
        rec["has_model"] = self.has_model
        rec["tier"] = TIER
        rec["licence"] = licence_name(self.source)
        return rec


def licence_name(source: str) -> str:
    if source == "kicad":
        return KICAD_LICENCE_NAME
    return SOURCES[source].licence.spdx


def source_root(source: str, kind: str = "lib") -> Path:
    return SOURCES[source].root


# ---------------------------------------------------------------- footprints


def _props(block: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in _PROP.finditer(block):
        out.setdefault(unescape(m.group(1)), unescape(m.group(2)))
    return out


def parse_footprint(text: str) -> dict[str, Any]:
    descr = _FP_DESCR.search(text)
    tags = _FP_TAGS.search(text)
    attr = _FP_ATTR.search(text)
    numbers = [m.group(1) for m in _FP_PAD.finditer(text)]
    return {
        "descr": unescape(descr.group(1)) if descr else "",
        "tags": unescape(tags.group(1)) if tags else "",
        "mount": attr.group(1).split()[0] if attr else None,
        "pads": len({n for n in numbers if n}),
        "pad_total": len(numbers),
        "models": [unescape(m.group(1)) for m in _FP_MODEL.finditer(text)],
    }


def resolve_model_file(model: str, fp_file: Path) -> tuple[str, str] | None:
    """KiCad model reference -> (source key, path relative to that source root), preferring
    STEP, only when the file exists locally."""
    m = _MODEL_VAR.match(model)
    if m:
        key, root, rel = "kicad3d", SOURCES["kicad3d"].root, m.group(1)
    else:
        key = fp_file_source(fp_file)
        if key is None:
            return None
        root = SOURCES[key].root
        if model.startswith("/"):
            return None
        base = fp_file.parent
        cand = (base / model).resolve() if not model.startswith("${") else None
        if cand is None:
            from .resolve import resolve_model

            try:
                res = resolve_model(model, fp_file)
            except Exception:
                return None
            if res is None:
                return None
            return res.source.key, str(res.path.relative_to(res.source.root))
        try:
            rel = str(cand.relative_to(root))
        except ValueError:
            return None
    p = root / rel
    for ext in (".step", ".stp", ".STEP", ".STP"):
        if p.with_suffix(ext).is_file():
            return key, str(Path(rel).with_suffix(ext))
    return (key, rel) if p.is_file() else None


def fp_file_source(path: Path) -> str | None:
    for key in INDEXED:
        try:
            path.relative_to(SOURCES[key].root)
            return key
        except ValueError:
            continue
    return None


def iter_footprint_files(source: str) -> Iterator[tuple[str, Path]]:
    root = SOURCES[source].root
    base = root / "footprints" if source == "kicad" else root
    if not base.is_dir():
        return
    for pretty in sorted(base.rglob("*.pretty")):
        if ".git" in pretty.parts or "node_modules" in pretty.parts:
            continue
        for f in sorted(pretty.glob("*.kicad_mod")):
            yield pretty.stem, f


def iter_symbol_files(source: str) -> Iterator[Path]:
    root = SOURCES[source].root
    base = root / "symbols" if source == "kicad" else root
    if not base.is_dir():
        return
    for f in sorted(base.rglob("*.kicad_sym")):
        if ".git" in f.parts or "node_modules" in f.parts:
            continue
        yield f


def footprint_rows(source: str) -> list[Row]:
    rows: list[Row] = []
    root = SOURCES[source].root
    for lib, f in iter_footprint_files(source):
        info = parse_footprint(f.read_text(encoding="utf-8", errors="replace"))
        model = None
        for ref in info["models"]:
            model = resolve_model_file(ref, f)
            if model:
                break
        name = f.stem
        descr = info["descr"]
        rows.append(
            Row(
                part_id=f"kicadgen:{source}:fp:{lib}:{name}",
                kind="footprint",
                source=source,
                lib=lib,
                name=name,
                descr=descr,
                keywords=info["tags"],
                datasheet="",
                function=infer_function(lib, name, descr, info["tags"], "footprint"),
                pins=0,
                pads=info["pads"],
                footprint=f"{lib}:{name}",
                footprint_part=None,
                fp_path=str(f.relative_to(root)),
                model_source=model[0] if model else None,
                model_path=model[1] if model else None,
                mount=info["mount"],
                pin_names=[],
                filters="",
            )
        )
    return rows


# ------------------------------------------------------------------- symbols


def parse_symbol_lib(text: str) -> list[dict[str, Any]]:
    starts = list(_SYM_START.finditer(text))
    raw: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for i, m in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(text)
        block = text[m.start() : end]
        name = unescape(m.group(1))
        head = block[: block.find("\n\t\t(symbol ")] if "\n\t\t(symbol " in block else block
        ext = _EXTENDS.search(head)
        props = _props(head)
        numbers = {n for n in (x.group(1) for x in _PIN_NUM.finditer(block)) if n}
        names = [unescape(x.group(1)) for x in _PIN_NAME.finditer(block)]
        raw[name] = {
            "extends": unescape(ext.group(1)) if ext else None,
            "props": props,
            "numbers": numbers,
            "pin_names": [n for n in dict.fromkeys(names) if n and n != "~"],
        }
        order.append(name)
    out = []
    for name in order:
        rec = raw[name]
        parent = raw.get(rec["extends"]) if rec["extends"] else None
        props = dict(parent["props"]) if parent else {}
        props.update({k: v for k, v in rec["props"].items() if v != ""})
        numbers = rec["numbers"] or (parent["numbers"] if parent else set())
        pin_names = rec["pin_names"] or (parent["pin_names"] if parent else [])
        out.append(
            {
                "name": name,
                "props": props,
                "pins": len(numbers),
                "pin_names": pin_names[:60],
            }
        )
    return out


def symbol_rows(source: str) -> list[Row]:
    rows: list[Row] = []
    for f in iter_symbol_files(source):
        lib = f.stem
        for sym in parse_symbol_lib(f.read_text(encoding="utf-8", errors="replace")):
            p = sym["props"]
            name = sym["name"]
            descr = p.get("Description", "")
            kw = p.get("ki_keywords", "")
            rows.append(
                Row(
                    part_id=f"kicadgen:{source}:sym:{lib}:{name}",
                    kind="symbol",
                    source=source,
                    lib=lib,
                    name=name,
                    descr=descr,
                    keywords=kw,
                    datasheet=p.get("Datasheet", "") if p.get("Datasheet", "") != "~" else "",
                    function=infer_function(lib, name, descr, kw, "symbol"),
                    pins=sym["pins"],
                    pads=0,
                    footprint=p.get("Footprint", ""),
                    footprint_part=None,
                    fp_path=None,
                    model_source=None,
                    model_path=None,
                    mount=None,
                    pin_names=sym["pin_names"],
                    filters=p.get("ki_fp_filters", ""),
                )
            )
    return rows


def join(symbols: list[Row], footprints: list[Row]) -> int:
    """Fill each symbol's footprint, 3D model and pad count from the footprint rows.
    Returns the number of symbols that reached a footprint."""
    by_lib: dict[tuple[str, str], Row] = {}
    by_src: dict[tuple[str, str, str], Row] = {}
    for fp in footprints:
        by_src[(fp.source, fp.lib, fp.name)] = fp
        by_lib.setdefault((fp.lib, fp.name), fp)
    joined = 0
    for s in symbols:
        if ":" not in s.footprint:
            continue
        lib, _, name = s.footprint.partition(":")
        fp = by_src.get((s.source, lib, name)) or by_lib.get((lib, name))
        if fp is None:
            continue
        s.footprint_part = fp.part_id
        s.fp_path = fp.fp_path
        s.model_source, s.model_path = fp.model_source, fp.model_path
        s.mount, s.pads = fp.mount, fp.pads
        joined += 1
    return joined


# ------------------------------------------------------------------- storage

DDL = """
DROP TABLE IF EXISTS kicad_fts;
DROP TABLE IF EXISTS kicad_parts;
DROP TABLE IF EXISTS meta;
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE kicad_parts (
    part_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    source TEXT NOT NULL,
    lib TEXT NOT NULL,
    name TEXT NOT NULL,
    function TEXT NOT NULL,
    pins INTEGER NOT NULL,
    pads INTEGER NOT NULL,
    footprint_part TEXT,
    has_model INTEGER NOT NULL,
    tier TEXT NOT NULL,
    licence TEXT NOT NULL,
    row_json TEXT NOT NULL
);
CREATE INDEX kicad_parts_kind ON kicad_parts (kind);
CREATE INDEX kicad_parts_fp ON kicad_parts (footprint_part);
CREATE VIRTUAL TABLE kicad_fts USING fts5(
    part_id UNINDEXED, name, body, tokenize = 'unicode61 remove_diacritics 2'
);
"""


def search_text(r: Row) -> tuple[str, str]:
    name = f"{r.name} {r.lib}".replace("_", " ")
    bits = [
        r.name.replace("_", " "),
        r.lib.replace("_", " "),
        r.descr,
        r.keywords,
        r.footprint.replace("_", " ").replace(":", " "),
        r.function.replace(".", " ").replace("_", " "),
        " ".join(r.pin_names),
        r.mount or "",
    ]
    return name, " ".join(b for b in bits if b)


def write_index(rows: list[Row], meta: dict[str, Any]) -> None:
    CATALOG.mkdir(parents=True, exist_ok=True)
    with INDEX_JSONL.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r.as_record(), sort_keys=True) + "\n")
    tmp = INDEX_SQLITE.with_suffix(".sqlite.tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    try:
        con.executescript(DDL)
        con.executemany(
            "INSERT INTO kicad_parts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    r.part_id,
                    r.kind,
                    r.source,
                    r.lib,
                    r.name,
                    r.function,
                    r.pins,
                    r.pads,
                    r.footprint_part,
                    int(r.has_model),
                    TIER,
                    licence_name(r.source),
                    json.dumps(r.as_record(), sort_keys=True),
                )
                for r in rows
            ],
        )
        con.executemany(
            "INSERT INTO kicad_fts VALUES (?,?,?)",
            [(r.part_id, *search_text(r)) for r in rows],
        )
        con.executemany(
            "INSERT INTO meta VALUES (?,?)", [(k, json.dumps(v)) for k, v in meta.items()]
        )
        con.commit()
        con.execute("INSERT INTO kicad_fts(kicad_fts) VALUES ('optimize')")
        con.commit()
    finally:
        con.close()
    tmp.replace(INDEX_SQLITE)


def build_rows(sources: tuple[str, ...] = INDEXED) -> tuple[list[Row], dict[str, Any]]:
    symbols: list[Row] = []
    footprints: list[Row] = []
    per_source: dict[str, dict[str, int]] = {}
    for key in sources:
        fps = footprint_rows(key)
        syms = symbol_rows(key)
        footprints += fps
        symbols += syms
        per_source[key] = {"symbols": len(syms), "footprints": len(fps)}
    joined = join(symbols, footprints)
    rows = symbols + footprints
    meta = {
        "tier": TIER,
        "licence_kicad": KICAD_LICENCE_NAME,
        "kicad_version": SOURCES["kicad"].commit,
        "symbols": len(symbols),
        "footprints": len(footprints),
        "symbols_with_footprint": joined,
        "symbols_with_3d": sum(1 for s in symbols if s.has_model),
        "footprints_with_3d": sum(1 for f in footprints if f.has_model),
        "per_source": per_source,
    }
    return rows, meta


# ------------------------------------------------------------------- prewarm


def cmd_prewarm(limit: int) -> int:
    """Convert the most-referenced footprints to GLB now instead of on first request."""
    from bara.kicad_generated import KicadIndex

    idx = KicadIndex(INDEX_SQLITE)
    counts = Counter(
        r["footprint_part"]
        for r in idx.rows("SELECT footprint_part FROM kicad_parts WHERE footprint_part IS NOT NULL")
    )
    wanted = [pid for pid, _ in counts.most_common(limit * 3)]
    done = 0
    for pid in wanted:
        if done >= limit:
            break
        if not idx.has_model(pid):
            continue
        path = idx.ensure_glb(pid)
        done += 1
        say(f"{done:4d} {pid} -> {'ok' if path else 'FAILED'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="catalog_build.kicad_index")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    sub.add_parser("stats")
    pw = sub.add_parser("prewarm")
    pw.add_argument("--limit", type=int, default=300)
    args = ap.parse_args(argv)
    if args.cmd == "build":
        rows, meta = build_rows()
        write_index(rows, meta)
        say(json.dumps(meta, indent=1))
        say(f"{INDEX_SQLITE}: {INDEX_SQLITE.stat().st_size / 1e6:.1f} MB")
        return 0
    if args.cmd == "stats":
        con = sqlite3.connect(INDEX_SQLITE)
        for k, v in con.execute("SELECT key, value FROM meta"):
            say(k, v)
        return 0
    return cmd_prewarm(args.limit)


if __name__ == "__main__":
    sys.exit(main())
