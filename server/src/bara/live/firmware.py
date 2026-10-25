"""Firmware stage: generated source from templates, with a pin map read off the KiCad nets.

ZMK for nRF52 keyboards, QMK for AVR keyboards, ESPHome for ESP32 gadgets and Arduino
otherwise. Compiling needs a toolchain this server may not have; when it is missing the
compile record says so (status skipped) instead of pretending a binary exists.
"""

from __future__ import annotations

import json
import re
import shutil
from typing import Any

from bara.firmware_sim.io import qmk_name
from bara.live.layout import KeyboardPlan

# part words -> (driver library, ZMK/QMK/ESPHome name). Hand-set from each project's docs.
DRIVERS: dict[str, dict[str, str]] = {
    "ssd1306": {
        "zmk": "zmk,ssd1306 (zephyr solomon,ssd1306fb)",
        "qmk": "qmk oled_driver",
        "esphome": "esphome ssd1306_i2c",
        "arduino": "adafruit/Adafruit_SSD1306",
    },
    "sh1106": {
        "zmk": "zephyr sinowealth,sh1106",
        "qmk": "qmk oled_driver (SH1106)",
        "esphome": "esphome ssd1306_i2c (model SH1106)",
        "arduino": "olikraus/U8g2",
    },
    "bme280": {
        "zmk": "zephyr bosch,bme280",
        "esphome": "esphome bme280_i2c",
        "arduino": "adafruit/Adafruit_BME280_Library",
    },
    "tmp117": {"esphome": "esphome tmp117", "arduino": "adafruit/Adafruit_TMP117"},
    "sht31": {"esphome": "esphome sht3xd", "arduino": "adafruit/Adafruit_SHT31"},
    "veml7700": {"esphome": "esphome veml7700", "arduino": "adafruit/Adafruit_VEML7700"},
    "tm1637": {"esphome": "esphome tm1637", "arduino": "avishorp/TM1637"},
    "max7219": {"esphome": "esphome max7219", "arduino": "wayoda/LedControl"},
    "ec11": {
        "zmk": "zmk alps,ec11",
        "qmk": "qmk encoder",
        "esphome": "esphome rotary_encoder",
        "arduino": "PaulStoffregen/Encoder",
    },
    "pmw3610": {"zmk": "badjeff/zmk-pmw3610-driver"},
    "pmw3360": {"zmk": "inorichi/zmk-pmw3360-driver", "qmk": "qmk pointing_device pmw3360"},
}

# The ANSI rows, left to right, so a key gets the legend of its place on a real keyboard.
ANSI_ROWS = [
    "ESC N1 N2 N3 N4 N5 N6 N7 N8 N9 N0 MINUS EQUAL BSPC".split(),
    "TAB Q W E R T Y U I O P LBKT RBKT BSLH".split(),
    "CAPS A S D F G H J K L SEMI SQT RET".split(),
    "LSHFT Z X C V B N M COMMA DOT FSLH RSHFT".split(),
    "LCTRL LGUI LALT SPACE RALT RGUI K_APP RCTRL".split(),
]
# A split board's bottom row has no space bar (the thumbs carry it).
SPLIT_BOTTOM = "LCTRL LGUI LALT GRAVE LBKT DEL RBKT LEFT DOWN UP RIGHT RCTRL".split()
# Which ANSI rows a board of n rows uses: the letter rows first, then numbers, then modifiers.
ROWS_FOR = {1: [1], 2: [1, 2], 3: [1, 2, 3], 4: [0, 1, 2, 3], 5: [0, 1, 2, 3, 4]}
SPARE_KEYS = "GRAVE DEL HOME END PG_UP PG_DN UP LEFT DOWN RIGHT INS".split() + [
    f"F{n}" for n in range(1, 13)
]
SPI_NETS = ("SCLK", "MOSI", "MISO", "NCS", "MOTION")
THUMBS = ["LGUI", "SPACE", "LSHFT", "RET", "BSPC", "LALT", "LCTRL", "TAB"]


def mcu_family(part: dict[str, Any] | None) -> str:
    blob = " ".join(
        str(x).lower()
        for x in (
            (part or {}).get("part_id"),
            (part or {}).get("display_name"),
            *((part or {}).get("facets") or {}).values(),
        )
    )
    if re.search(r"nrf52|nice.?nano|bluemicro|puchi|supermini", blob):
        return "nrf52"
    if re.search(r"esp32", blob):
        return "esp32"
    if re.search(r"32u4|atmega|pro.?micro", blob):
        return "avr"
    if re.search(r"rp2040", blob):
        return "rp2040"
    return "unknown"


def pad_names(controller_id: str | None) -> dict[str, str]:
    if not controller_id:
        return {}
    try:
        from bara.board import registry
        from bara.board.layout import controller_gpio

        ctrl = next(c for c in registry.CONTROLLERS if c["id"] == controller_id)
        return controller_gpio(ctrl)[1]
    except Exception:  # library files missing: pin map falls back to pad numbers
        return {}


def board_pins(board_entry: dict[str, Any]) -> dict[str, str]:
    """net name -> MCU pin name (P0.17 style) for one KiCad board."""
    mcu = next((p for p in board_entry.get("placements", []) if p.get("role") == "mcu"), None)
    if mcu is None:
        return {}
    names = pad_names(board_entry.get("controller"))
    out: dict[str, str] = {}
    for net in board_entry.get("nets", []):
        for m in net.get("members", []):
            if m.get("instance_id") == mcu["instance_id"]:
                pad = str(m.get("pin"))
                out[net["name"]] = names.get(pad, f"pad{pad}")
    return out


def _zmk_gpio(pin: str) -> str:
    m = re.match(r"P(\d)\.(\d+)", pin)
    if not m:
        return f"<&gpio0 0 GPIO_ACTIVE_HIGH> /* {pin}: no port mapping */"
    return f"<&gpio{m.group(1)} {int(m.group(2))} (GPIO_ACTIVE_HIGH | GPIO_PULL_DOWN)>"


def _row_codes(row: int, rows: int, split: bool) -> list[str]:
    pick = ROWS_FOR.get(rows, list(range(5)) + [1] * (rows - 5))
    i = pick[row] if row < len(pick) else 1
    return SPLIT_BOTTOM if split and i == 4 else ANSI_ROWS[i]


def _key_code(key: dict[str, Any], half: Any, split: bool) -> str | None:
    """The ANSI legend for a main key from its (row, column) place, or None past the row's end.
    A split half takes its columns outward from the T|Y gap; column 0 is always the outer one."""
    r, c = key["pos"]
    codes = _row_codes(r, half.rows, split)
    if split:
        inner = half.cols - 1 - c  # 0 at the gap
        at = 5 - inner if half.side == "left" else 6 + inner
    elif half.cols >= len(codes):
        at = c
    else:
        at = c + min(1, len(codes) - half.cols)  # a narrow grid starts at Q, not Tab
    return codes[at] if 0 <= at < len(codes) else None


def _keymap_codes(plan: KeyboardPlan) -> list[list[str]]:
    """One key code per key, half by half, in key order."""
    split = len(plan.halves) > 1
    codes: list[list[str | None]] = []
    used: set[str] = set()
    for half in plan.halves:
        line = [None if k.get("thumb") else _key_code(k, half, split) for k in half.keys]
        used |= {c for c in line if c}
        codes.append(line)
    spare = iter([k for k in SPARE_KEYS if k not in used] * 4)
    out: list[list[str]] = []
    t = 0
    for half, line in zip(plan.halves, codes, strict=True):
        filled = []
        for key, code in zip(half.keys, line, strict=True):
            if key.get("thumb"):
                code = THUMBS[t % len(THUMBS)]
                t += 1
            filled.append(code or next(spare))
        out.append(filled)
    return out


def _keymap_rows(plan: KeyboardPlan) -> list[str]:
    return ["  ".join(f"&kp {c}" for c in half) for half in _keymap_codes(plan)]


def _qmk(plan: KeyboardPlan) -> list[dict[str, Any]]:
    """keyboard.json with a LAYOUT over the key matrix, and a default keymap.c in key order."""
    half = plan.halves[0]
    rows, cols = half.matrix
    layout = [
        {"matrix": k.get("matrix") or k["pos"], "x": k["x_u"], "y": k["y_u"]}
        | ({"w": k["w_u"]} if k.get("w_u", 1.0) != 1.0 else {})
        for k in half.keys
    ]
    qmk = {
        "keyboard_name": "bara",
        "matrix_size": {"rows": rows, "cols": cols},
        "processor": "atmega32u4",
        "bootloader": "caterina",
        "layouts": {"LAYOUT": {"layout": layout}},
    }
    kcs = [qmk_name(c) for c in _keymap_codes(plan)[0]]
    lines = [", ".join(kcs[i : i + 14]) for i in range(0, len(kcs), 14)]
    keymap = (
        "#include QMK_KEYBOARD_H\n\n"
        "const uint16_t PROGMEM keymaps[][MATRIX_ROWS][MATRIX_COLS] = {\n"
        "    [0] = LAYOUT(\n        " + ",\n        ".join(lines) + "\n    )\n};\n"
    )
    return [
        {
            "path": "keyboards/bara/keyboard.json",
            "language": "json",
            "content": json.dumps(qmk, indent=2) + "\n",
        },
        {"path": "keyboards/bara/keymaps/default/keymap.c", "language": "c", "content": keymap},
    ]


def _zmk(
    brief: dict[str, Any], plan: KeyboardPlan, boards: list[dict[str, Any]], peripherals: set[str]
) -> list[dict[str, Any]]:
    shield = "bara"
    files: list[dict[str, Any]] = []
    rows, cols = plan.halves[0].matrix
    transform = []
    for hi, half in enumerate(plan.halves):
        off = hi * cols
        transform += [f"RC({k['matrix'][0]},{k['matrix'][1] + off})" for k in half.keys]
    dtsi = (
        "#include <dt-bindings/zmk/matrix_transform.h>\n\n/ {\n"
        "    chosen { zmk,kscan = &kscan0; zmk,matrix-transform = &default_transform; };\n"
        "    default_transform: keymap_transform_0 {\n"
        '        compatible = "zmk,matrix-transform";\n'
        f"        columns = <{cols * len(plan.halves)}>;\n        rows = <{rows}>;\n"
        f"        map = <{' '.join(transform)}>;\n    }};\n"
        "    kscan0: kscan {\n"
        '        compatible = "zmk,kscan-gpio-matrix";\n'
        '        diode-direction = "col2row";\n    };\n};\n'
    )
    files.append(
        {
            "path": f"config/boards/shields/{shield}/{shield}.dtsi",
            "language": "devicetree",
            "content": dtsi,
        }
    )
    for half, entry in zip(plan.halves, boards, strict=False):
        pins = board_pins(entry)
        row_pins = [pins.get(f"ROW{r}", "?") for r in range(rows)]
        col_pins = [pins.get(f"COL{c}", "?") for c in range(cols)]
        side = half.side if half.side != "none" else ""
        name = f"{shield}_{side}" if side else shield
        body = [f'#include "{shield}.dtsi"\n', "&kscan0 {"]
        body.append(
            "    row-gpios\n        = " + "\n        , ".join(_zmk_gpio(p) for p in row_pins) + ";"
        )
        body.append(
            "    col-gpios\n        = " + "\n        , ".join(_zmk_gpio(p) for p in col_pins) + ";"
        )
        body.append("};")
        if half.side == "right":
            body.append(f"&default_transform {{ col-offset = <{cols}>; }};")
        enc = [n for n in pins if re.match(r"ENC\d+_A", n)]
        for n in enc:
            i = n[3:-2]
            body.append(
                f"\nencoder_{i}: &left_encoder {{ /* EC11 */\n"
                f"    a-gpios = {_zmk_gpio(pins[n])};\n"
                f"    b-gpios = {_zmk_gpio(pins.get(f'ENC{i}_B', '?'))};\n"
                '    status = "okay";\n};'
            )
        if "SDA" in pins:
            body.append(
                f"\n/* OLED on I2C: SDA {pins['SDA']}, SCL {pins.get('SCL', '?')} */\n"
                '&i2c0 { status = "okay"; oled: ssd1306@3c { compatible = "solomon,ssd1306fb"; '
                "reg = <0x3c>; }; };"
            )
        if "SCLK" in pins:
            body.append(
                "\n/* PMW3610 trackball sensor on SPI: "
                + ", ".join(
                    f"{n} {pins[n]}" for n in ("SCLK", "MOSI", "MISO", "NCS", "MOTION") if n in pins
                )
                + " */"
            )
        files.append(
            {
                "path": f"config/boards/shields/{shield}/{name}.overlay",
                "language": "devicetree",
                "content": "\n".join(body) + "\n",
            }
        )
    km = "\n".join(f"                {r}" for r in _keymap_rows(plan))
    keymap = (
        "#include <behaviors.dtsi>\n#include <dt-bindings/zmk/keys.h>\n\n/ {\n"
        '    keymap {\n        compatible = "zmk,keymap";\n'
        f"        base {{\n            bindings = <\n{km}\n"
        "            >;\n        };\n    };\n};\n"
    )
    files.append({"path": f"config/{shield}.keymap", "language": "keymap", "content": keymap})
    conf = ["CONFIG_ZMK_SLEEP=y"]
    if "display" in peripherals:
        conf.append("CONFIG_ZMK_DISPLAY=y")
    if "encoder" in peripherals:
        conf.append("CONFIG_EC11=y")
    if "trackball" in peripherals:
        conf.append("CONFIG_ZMK_POINTING=y")
    if brief.get("wireless") == "ble":
        conf.append("CONFIG_ZMK_BLE=y")
    files.append(
        {"path": f"config/{shield}.conf", "language": "kconfig", "content": "\n".join(conf) + "\n"}
    )
    board = {"xiao_nrf52840": "seeeduino_xiao_ble", "nice_nano_v2": "nice_nano_v2"}
    inc = []
    for half, entry in zip(plan.halves, boards, strict=False):
        side = f"_{half.side}" if half.side in ("left", "right") else ""
        inc.append(
            f"  - board: {board.get(entry.get('controller') or '', 'nice_nano_v2')}\n"
            f"    shield: {shield}{side}"
        )
    files.append(
        {"path": "build.yaml", "language": "yaml", "content": "include:\n" + "\n".join(inc) + "\n"}
    )
    return files


def _esphome(brief: dict[str, Any], peripherals: dict[str, dict[str, Any]]) -> list[dict]:
    lines = [
        "esphome:",
        f"  name: {re.sub(r'[^a-z0-9-]', '-', (brief.get('device') or 'bara').lower())[:30]}",
        "esp32:",
        "  board: seeed_xiao_esp32c3",
        "logger:",
        "i2c:",
        "  sda: GPIO6",
        "  scl: GPIO7",
    ]
    if "sensor" in peripherals:
        lines += [
            "sensor:",
            "  - platform: bme280_i2c",
            "    address: 0x76",
            "    temperature: {name: Temperature}",
            "    humidity: {name: Humidity}",
            "    pressure: {name: Pressure}",
        ]
    if "display" in peripherals:
        lines += [
            "display:",
            "  - platform: ssd1306_i2c",
            "    model: SSD1306 128x32",
            "    address: 0x3C",
        ]
    if "encoder" in peripherals:
        lines += ["  - platform: rotary_encoder", "    pin_a: GPIO2", "    pin_b: GPIO3"]
    return [{"path": "bara.yaml", "language": "yaml", "content": "\n".join(lines) + "\n"}]


def _arduino(brief: dict[str, Any], peripherals: dict[str, dict[str, Any]]) -> list[dict]:
    inc = ["#include <Arduino.h>", "#include <Wire.h>"]
    setup = ["  Wire.begin();"]
    if "display" in peripherals:
        inc.append("#include <Adafruit_SSD1306.h>")
        setup.append("  display.begin(SSD1306_SWITCHCAPVCC, 0x3C);")
    if "sensor" in peripherals:
        inc.append("#include <Adafruit_BME280.h>")
        setup.append("  bme.begin(0x76);")
    body = "\n".join(inc) + "\n\n"
    if "display" in peripherals:
        body += "Adafruit_SSD1306 display(128, 32, &Wire);\n"
    if "sensor" in peripherals:
        body += "Adafruit_BME280 bme;\n"
    body += "\nvoid setup() {\n" + "\n".join(setup) + "\n}\n\nvoid loop() {\n  delay(1000);\n}\n"
    return [{"path": "src/main.cpp", "language": "cpp", "content": body}]


def make_firmware(
    brief: dict[str, Any],
    plan: KeyboardPlan | None,
    slots: list[Any],
    board: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Firmware record (SPEC 4.9) and its fw.driver.available checks."""
    by_slot = {s.slot_id: s for s in slots}
    ctrl = by_slot.get("controller")
    mcu_part = ctrl.chosen if ctrl else None
    family = mcu_family(mcu_part)
    boards = [b for b in (board or {}).get("boards", []) if not b["name"].endswith("sensor")]
    if plan is not None:
        framework = "qmk" if family == "avr" else "zmk"
    else:
        framework = "esphome" if family == "esp32" else "arduino"
    peripherals: dict[str, dict[str, Any]] = {}
    for s in slots:
        if s.chosen is None:
            continue
        if s.slot_id == "display":
            peripherals["display"] = s.chosen
        elif s.slot_id in ("encoder", "trackball"):
            peripherals[s.slot_id] = s.chosen
        elif s.function_id.startswith("sense."):
            peripherals["sensor"] = s.chosen
    for f in brief.get("features", []):
        if plan is not None and f["kind"] == "knob":
            peripherals.setdefault("encoder", {"part_id": "kicad:ec11", "display_name": "EC11"})
        if plan is not None and f["kind"] == "trackball":
            peripherals.setdefault(
                "trackball", {"part_id": "kicad:pmw3610", "display_name": "PMW3610"}
            )

    if framework == "zmk" and plan is not None:
        files = _zmk(brief, plan, boards, set(peripherals))
    elif framework == "qmk" and plan is not None:
        files = _qmk(plan)
    elif framework == "esphome":
        files = _esphome(brief, peripherals)
    else:
        files = _arduino(brief, peripherals)
    for f in files:
        f["asset"] = None
        f["bytes"] = len((f.get("content") or "").encode())

    instances = ctrl.instances if ctrl else []
    targets = [
        {
            "target_id": f"bara_{i.side}" if i.side in ("left", "right") else "bara",
            "mcu_instance_id": i.instance_id,
            "side": i.side if i.side in ("left", "right") else "none",
            "label": {"left": "Left half (central)", "right": "Right half"}.get(i.side, "Main"),
        }
        for i in instances
    ]
    pin_map = []
    for entry in boards:
        side = entry.get("side") or "none"
        inst = next((i for i in instances if i.side == side), instances[0] if instances else None)
        if inst is None:
            continue
        for net, pin in sorted(board_pins(entry).items()):
            if net in ("GND", "3V3", "BAT+", "VBAT_IN", "RST"):
                continue
            pin_map.append(
                {
                    "instance_id": inst.instance_id,
                    "interface_id": None,
                    "signal": net,
                    "mcu_instance_id": inst.instance_id,
                    "mcu_pin": pin,
                }
            )
    drivers = []
    checks = []
    for kind, part in peripherals.items():
        blob = (str(part.get("part_id")) + " " + str(part.get("display_name"))).lower()
        key = next((k for k in DRIVERS if k in blob), None)
        if kind == "encoder" and key is None:
            key = "ec11"
        if kind == "trackball" and key is None:
            key = "pmw3610"
        lib = DRIVERS.get(key or "", {}).get(framework)
        if lib:
            drivers.append(
                {"part_id": part["part_id"], "library": lib, "version": None, "include": None}
            )
        subj = next(
            (s.instances[0].instance_id for s in slots if s.chosen is part and s.instances), None
        )
        checks.append(
            {
                "check_key": f"fw.driver.available:{subj or kind}",
                "rule_id": "fw.driver.available",
                "status": "pass" if lib else "unknown",
                "severity": "error",
                "message": (
                    f"{framework.upper()} driver for {part.get('display_name') or kind}: {lib}"
                    if lib
                    else f"No known {framework} driver for {part.get('display_name') or kind}"
                )[:300],
                "subjects": [{"instance_id": subj}] if subj else [],
                "stage": "firmware",
            }
        )
    tool = {"zmk": "west", "qmk": "qmk", "esphome": "esphome", "arduino": "arduino-cli"}
    have_tool = shutil.which(tool.get(framework, "")) is not None
    firmware = {
        "firmware_id": "fw_main",
        "framework": framework,
        "origin": "template",
        "mode": "compiled",
        "mode_reason": "Generated board and pin map, so the source is generated for it.",
        "targets": targets,
        "files": files,
        "drivers": drivers,
        "pin_map": pin_map[:200],
        "compile": {
            "status": "pending" if have_tool else "skipped",
            "duration_ms": 0,
            "binaries": [],
            "log": None,
            "message": (
                "Queued; runs after the build finishes."
                if have_tool
                else f"{tool.get(framework)} is not installed on this server; source only."
            ),
        },
        "revision": 1,
    }
    return firmware, checks
