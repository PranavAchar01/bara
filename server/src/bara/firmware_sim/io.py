"""The device's inputs and outputs, named in plain words, with a pin for each.

Read from the build record: the parts and their functions, the slot labels ("D-pad direction
switches (up, down, left, right)"), the firmware's keymap and pin map. The web client may send
the names it already derived from where each button sits on the control face (UP, A, START);
those win over the label order here. Pins come from the board's netlist when the board was
routed (firmware.pin_map); otherwise from a pin plan made here against the controller's free
GPIO, and the plan says so.
"""

from __future__ import annotations

import math
import re
from typing import Any

from bara.firmware_sim.mcu import Board, board_for

# ZMK key name -> USB HID usage (keyboard page 0x07), HID Usage Tables 1.5 section 10
_LETTERS = {chr(ord("A") + i): 0x04 + i for i in range(26)}
_DIGITS = {f"N{d}": 0x1E + (d - 1) for d in range(1, 10)} | {"N0": 0x27}
HID_USAGE: dict[str, int] = {
    **_LETTERS,
    **_DIGITS,
    "RET": 0x28,
    "ENTER": 0x28,
    "RETURN": 0x28,
    "ESC": 0x29,
    "ESCAPE": 0x29,
    "BSPC": 0x2A,
    "BACKSPACE": 0x2A,
    "TAB": 0x2B,
    "SPACE": 0x2C,
    "SPC": 0x2C,
    "MINUS": 0x2D,
    "EQUAL": 0x2E,
    "LBKT": 0x2F,
    "RBKT": 0x30,
    "BSLH": 0x31,
    "SEMI": 0x33,
    "SQT": 0x34,
    "GRAVE": 0x35,
    "COMMA": 0x36,
    "DOT": 0x37,
    "FSLH": 0x38,
    "CAPS": 0x39,
    **{f"F{n}": 0x3A + n - 1 for n in range(1, 13)},
    "RIGHT": 0x4F,
    "LEFT": 0x50,
    "DOWN": 0x51,
    "UP": 0x52,
    "LCTRL": 0xE0,
    "LSHFT": 0xE1,
    "LSHIFT": 0xE1,
    "LALT": 0xE2,
    "LGUI": 0xE3,
    "RCTRL": 0xE4,
    "RSHFT": 0xE5,
    "RALT": 0xE6,
    "RGUI": 0xE7,
}
_KEY_WORDS = {
    "RET": "Enter",
    "ENTER": "Enter",
    "BSPC": "Backspace",
    "SPACE": "Space",
    "TAB": "Tab",
    "ESC": "Escape",
    "LSHFT": "Shift",
    "RSHFT": "Shift",
    "LCTRL": "Ctrl",
    "RCTRL": "Ctrl",
    "LALT": "Alt",
    "RALT": "Alt",
    "LGUI": "Cmd",
    "RGUI": "Cmd",
    "SEMI": ";",
    "SQT": "'",
    "COMMA": ",",
    "DOT": ".",
    "FSLH": "/",
    "BSLH": "\\",
    "MINUS": "-",
    "EQUAL": "=",
    "LBKT": "[",
    "RBKT": "]",
    "GRAVE": "`",
}

POSITION_WORDS = {
    "UP": "D-pad up",
    "DOWN": "D-pad down",
    "LEFT": "D-pad left",
    "RIGHT": "D-pad right",
    "A": "A button",
    "B": "B button",
    "X": "X button",
    "Y": "Y button",
    "START": "Start button",
    "SELECT": "Select button",
    "MENU": "Menu button",
    "MODE": "Mode button",
    "RESET": "Reset button",
    "BOOT": "Boot button",
    "POWER": "Power button",
    "L": "L shoulder",
    "R": "R shoulder",
}
_LABEL_TOKENS = re.compile(
    r"\b(up|down|left|right|start|select|menu|mode|reset|boot|a|b|x|y|l|r)\b", re.IGNORECASE
)

SCREEN_TEXT = {  # (rows, cols) of 6x8 px text cells the firmware keeps for a panel size
    (128, 32): (4, 21),
    (128, 64): (8, 21),
    (128, 128): (16, 21),
    (240, 240): (8, 21),
    (320, 240): (8, 26),
}


# keys with no keymap yet send 1..9, 0, then A..Z, so every key still reports a usage code
DEFAULT_KEY_CODES = [f"N{d}" for d in (1, 2, 3, 4, 5, 6, 7, 8, 9, 0)] + list(_LETTERS)


def _fn(part: dict[str, Any]) -> str:
    return str((part.get("card") or {}).get("primary_function") or "")


_CONTROLLER_WORDS = re.compile(
    r"\b(controller|mcu|microcontroller)\b|nrf5\d|rp2040|rp2350|esp32|stm32|atmega|samd", re.I
)


def controller_part(parts: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The build's controller: the compute.mcu part, else the part the build names its controller
    (a radio module that carries the MCU is catalogued under its radio function)."""
    found = next((p for p in parts if _fn(p) == "compute.mcu"), None)
    if found:
        return found
    for p in parts:
        card = p.get("card") or {}
        words = f"{p.get('label') or ''} {card.get('display_name') or ''} {p.get('part_id') or ''}"
        if (p.get("instance_id") == "u_mcu" or _CONTROLLER_WORDS.search(words)) and not _fn(
            p
        ).startswith(("power.", "input.", "display.", "output.")):
            return p
    return None


def _name(part: dict[str, Any]) -> str:
    return str(part.get("label") or (part.get("card") or {}).get("display_name") or "")


def key_label(code: str | None, n: int) -> str:
    if not code:
        return f"Key {n}"
    word = _KEY_WORDS.get(code)
    if word:
        return f"{word} key"
    if re.fullmatch(r"N\d", code):
        return f"Key {code[1]}"
    return f"Key {code}"


def keymap_codes(firmware: dict[str, Any] | None) -> list[str]:
    """`&kp X` codes of the first keymap layer, in binding order."""
    for f in (firmware or {}).get("files") or []:
        if str(f.get("path", "")).endswith(".keymap") and f.get("content"):
            body = re.search(r"bindings\s*=\s*<([\s\S]*?)>", f["content"])
            if body:
                return [m.group(1) for m in re.finditer(r"&kp\s+(\w+)", body.group(1))]
    return []


def _quantity(part: dict[str, Any]) -> int:
    return max(1, int(part.get("quantity") or 1))


def _button_labels(part: dict[str, Any], client: dict[str, str]) -> list[str]:
    """One plain-word label per element of a button part."""
    n = _quantity(part)
    iid = part["instance_id"]
    label = _name(part)
    low = label.lower()
    words = [m.group(1).upper() for m in _LABEL_TOKENS.finditer(label)]
    if "shoulder" in low:
        words = [w for w in words if w in ("L", "R")] or ["L", "R"]
    elif "d-pad" in low or "dpad" in low or "direction" in low:
        words = [w for w in words if w in ("UP", "DOWN", "LEFT", "RIGHT")]
        words += [w for w in ("UP", "DOWN", "LEFT", "RIGHT") if w not in words]
    else:
        words = [w for w in words if w not in ("L", "R") or "shoulder" in low]
    out = []
    for i in range(n):
        raw = client.get(f"{iid}#{i}")
        if "shoulder" in low:
            # shoulders sit on the top edge: the client names them as face buttons by position
            raw = None
        if "d-pad" in low or "direction" in low:
            raw = raw if raw in ("UP", "DOWN", "LEFT", "RIGHT") else None
        word = raw or (words[i] if i < len(words) else None)
        out.append(POSITION_WORDS.get(word or "", f"Button {i + 1}" if n > 1 else "Button"))
    return out


def _screen(part: dict[str, Any]) -> dict[str, Any]:
    blob = _name(part) + " " + str((part.get("card") or {}).get("display_name") or "")
    m = re.search(r"(\d{2,3})\s*x\s*(\d{2,3})", blob)
    w, h = (
        (int(m.group(1)), int(m.group(2))) if m else (128, 64 if "tft" not in blob.lower() else 240)
    )
    if "tft" in _fn(part) and not m:
        w, h = 320, 240
    rows, cols = SCREEN_TEXT.get((w, h)) or SCREEN_TEXT.get((h, w)) or (8, 21)
    kind = "color" if _fn(part) == "display.tft" else "mono"
    return {"width": w, "height": h, "rows": rows, "cols": cols, "tone": kind}


def device_kind(parts: list[dict[str, Any]]) -> str:
    fns = [_fn(p) for p in parts]
    keys = sum(_quantity(p) for p in parts if _fn(p) == "input.key")
    if keys >= 2:
        return "keyboard"
    if any(f in ("input.button", "input.joystick") for f in fns):
        return "gamepad"
    return "gadget"


def plan_io(
    build: dict[str, Any],
    client: dict[str, str] | None = None,
    client_codes: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Inputs, outputs, power path and the pin of each, for the firmware generator."""
    client = client or {}
    client_codes = client_codes or {}
    parts = [p for p in build.get("parts") or [] if p.get("instance_id")]
    mcu = controller_part(parts)
    board = board_for(mcu)
    firmware = build.get("firmware") or {}
    kind = device_kind(parts)
    inputs: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    power: dict[str, Any] = {"switch": None, "battery": None, "charger": None, "regulator": None}
    unsimulated: list[dict[str, str]] = []

    codes = keymap_codes(firmware)
    key_n = 0
    for p in parts:
        f, iid = _fn(p), p["instance_id"]
        if f == "input.key":
            for i in range(_quantity(p)):
                code = (
                    client_codes.get(f"{iid}#{i}")
                    or (codes[key_n] if key_n < len(codes) else None)
                    or (DEFAULT_KEY_CODES[key_n] if key_n < len(DEFAULT_KEY_CODES) else None)
                )
                key_n += 1
                inputs.append(
                    {
                        "id": f"{iid}#{i}",
                        "label": key_label(code, key_n),
                        "kind": "key",
                        "code": code,
                        "hid": HID_USAGE.get(code or ""),
                        "instance_id": iid,
                        "index": i,
                    }
                )
        elif f == "input.button":
            for i, label in enumerate(_button_labels(p, client)):
                inputs.append(
                    {
                        "id": f"{iid}#{i}",
                        "label": label,
                        "kind": "button",
                        "instance_id": iid,
                        "index": i,
                    }
                )
        elif f == "input.rotary_encoder":
            for i in range(_quantity(p)):
                n = f" {i + 1}" if _quantity(p) > 1 else ""
                inputs.append(
                    {
                        "id": f"{iid}#{i}",
                        "label": f"Knob{n}",
                        "kind": "encoder",
                        "instance_id": iid,
                        "index": i,
                    }
                )
                if (
                    "switch" in _name(p).lower()
                    or "push" in _name(p).lower()
                    or "ec11" in _name(p).lower()
                ):
                    inputs.append(
                        {
                            "id": f"{iid}#{i}.press",
                            "label": f"Knob{n} press",
                            "kind": "button",
                            "instance_id": iid,
                            "index": i,
                        }
                    )
        elif f == "input.joystick":
            for i in range(_quantity(p)):
                n = f" {i + 1}" if _quantity(p) > 1 else ""
                for axis in ("X", "Y"):
                    inputs.append(
                        {
                            "id": f"{iid}#{i}.{axis.lower()}",
                            "label": f"Joystick{n} {axis}",
                            "kind": "axis",
                            "instance_id": iid,
                            "index": i,
                        }
                    )
                inputs.append(
                    {
                        "id": f"{iid}#{i}.press",
                        "label": f"Joystick{n} press",
                        "kind": "button",
                        "instance_id": iid,
                        "index": i,
                    }
                )
        elif f == "input.potentiometer":
            for i in range(_quantity(p)):
                n = f" {i + 1}" if _quantity(p) > 1 else ""
                inputs.append(
                    {
                        "id": f"{iid}#{i}",
                        "label": f"Dial{n}",
                        "kind": "axis",
                        "instance_id": iid,
                        "index": i,
                    }
                )
        elif f == "input.toggle_switch":
            for i in range(_quantity(p)):
                inputs.append(
                    {
                        "id": f"{iid}#{i}",
                        "label": "Toggle switch",
                        "kind": "switch",
                        "instance_id": iid,
                        "index": i,
                    }
                )
        elif f == "power.switch":
            power["switch"] = {
                "id": f"{iid}#0",
                "label": "Power switch",
                "instance_id": iid,
                "kind": "power",
            }
        elif f in ("power.battery", "power.coin_cell"):
            power["battery"] = {"instance_id": iid, "name": _name(p), "part_id": p.get("part_id")}
        elif f == "power.charger":
            power["charger"] = {"instance_id": iid, "name": _name(p), "part_id": p.get("part_id")}
        elif f == "power.regulator":
            power["regulator"] = {"instance_id": iid, "name": _name(p), "part_id": p.get("part_id")}
        elif f.startswith("display.") and f != "display.indicator_led":
            outputs.append(
                {
                    "id": f"screen:{iid}",
                    "label": _screen_label(p),
                    "kind": "display",
                    "instance_id": iid,
                    **_screen(p),
                }
            )
        elif f in ("display.indicator_led", "output.rgb_led"):
            outputs.append(
                {"id": f"led:{iid}", "label": "Indicator LED", "kind": "led", "instance_id": iid}
            )
        elif f in ("output.speaker", "output.buzzer"):
            outputs.append(
                {
                    "id": f"tone:{iid}",
                    "label": "Speaker" if "speaker" in f else "Buzzer",
                    "kind": "tone",
                    "instance_id": iid,
                }
            )
        elif f in ("input.trackball", "input.touch", "output.haptic", "output.motor_dc"):
            unsimulated.append(
                {"instance_id": iid, "label": _name(p), "why": "no peripheral model for it yet"}
            )

    if board.led_pin:
        outputs.insert(
            0,
            {
                "id": "led:onboard",
                "label": "Status LED (on the controller)",
                "kind": "led",
                "instance_id": mcu["instance_id"] if mcu else None,
            },
        )
    outputs.append({"id": "serial", "label": "Serial console (UART)", "kind": "serial"})
    hid_label = {"keyboard": "USB keyboard reports", "gamepad": "USB gamepad reports"}.get(
        kind, "USB reports"
    )
    outputs.append({"id": "hid", "label": hid_label, "kind": "hid"})

    pins = assign_pins(board, inputs, outputs, firmware)
    return {
        "device": {**(build.get("device") or {}), "name": device_name(build)},
        "kind": kind,
        "mcu": {
            "board_id": board.board_id,
            "label": board.label,
            "family": board.family,
            "core": board.core,
            "emulator": board.emulator,
            "instance_id": mcu["instance_id"] if mcu else None,
        },
        "inputs": inputs,
        "outputs": outputs,
        "power": power,
        "unsimulated": unsimulated,
        **pins,
        "labels_by": "rules",
    }


def device_name(build: dict[str, Any]) -> str:
    """A short name for the banner and the screen, from the prompt."""
    prompt = str(build.get("prompt") or (build.get("spec") or {}).get("prompt") or "device")
    name = re.split(r"\s+(?:like|similar to|with|that|for)\s+|[,.;]", prompt.strip(), maxsplit=1)[0]
    for _ in range(3):
        name = re.sub(r"^(?:a|an|the|make|build|create|me)\s+", "", name, flags=re.I).strip()
    name = name or "device"
    return (name[:1].upper() + name[1:])[:28]


def _screen_label(part: dict[str, Any]) -> str:
    s = _screen(part)
    kind = "OLED" if "oled" in _fn(part) else "TFT" if "tft" in _fn(part) else "Screen"
    return f"{kind} screen {s['width']}x{s['height']}"


def assign_pins(
    board: Board,
    inputs: list[dict[str, Any]],
    outputs: list[dict[str, Any]],
    firmware: dict[str, Any],
) -> dict[str, Any]:
    """A pin for every input and output. Keys go in a row/column matrix when direct wiring would
    not fit the controller; joystick axes and dials take ADC pins."""
    from_netlist = {e["signal"]: e["mcu_pin"] for e in firmware.get("pin_map") or []}
    free = [p for p in board.gpio if p not in board.reserved]
    adc_free = [p for p in free if p in board.adc]
    digital_free = [p for p in free if p not in board.adc] + adc_free  # ADC pins last
    used: dict[str, str] = {}

    def take(pool: list[str], why: str, prefer: str | None = None) -> str | None:
        pin = prefer if prefer and prefer in pool else (pool[0] if pool else None)
        if pin is None:
            return None
        for lst in (digital_free, adc_free):
            if pin in lst:
                lst.remove(pin)
        used[pin] = why
        return pin

    def claim(pin: str | None, why: str) -> str | None:
        """A pin the routed board already fixed: out of the free pools so nothing else takes it."""
        if pin:
            for lst in (digital_free, adc_free):
                if pin in lst:
                    lst.remove(pin)
            used[pin] = why
        return pin

    keys = [i for i in inputs if i["kind"] == "key"]
    others = [i for i in inputs if i["kind"] != "key"]
    need_direct = len(keys) + sum(2 if i["kind"] == "encoder" else 1 for i in others) + 4
    matrix: dict[str, Any] | None = None
    # axes first: they can only use ADC pins
    for i in others:
        if i["kind"] == "axis":
            i["pin"] = take(adc_free, i["label"])
            i["adc"] = board.adc.get(i["pin"] or "")
    if keys and (need_direct > len(free) or any(s.startswith("ROW") for s in from_netlist)):
        cols = max(1, math.ceil(math.sqrt(len(keys))))
        rows = math.ceil(len(keys) / cols)
        row_pins = [
            claim(from_netlist.get(f"ROW{r}"), f"matrix row {r}")
            or take(digital_free, f"matrix row {r}")
            for r in range(rows)
        ]
        col_pins = [
            claim(from_netlist.get(f"COL{c}"), f"matrix column {c}")
            or take(digital_free, f"matrix column {c}")
            for c in range(cols)
        ]
        for n, k in enumerate(keys):
            r, c = divmod(n, cols)
            k["row"], k["col"] = r, c
            k["row_pin"], k["pin"] = row_pins[r], col_pins[c]
        matrix = {
            "rows": rows,
            "cols": cols,
            "row_pins": row_pins,
            "col_pins": col_pins,
            "diodes": "col2row",
        }
    else:
        for k in keys:
            k["pin"] = take(digital_free, k["label"])
    for i in others:
        if i["kind"] == "encoder":
            i["pin"] = take(digital_free, f"{i['label']} A")
            i["pin_b"] = take(digital_free, f"{i['label']} B")
        elif i["kind"] in ("button", "switch"):
            i["pin"] = take(digital_free, i["label"])
    for o in outputs:
        if o["kind"] == "led":
            o["pin"] = board.led_pin if o["id"] == "led:onboard" else take(digital_free, o["label"])
            o["active_low"] = board.led_active_low if o["id"] == "led:onboard" else False
        elif o["kind"] == "tone":
            o["pin"] = take(digital_free, o["label"])
        elif o["kind"] == "display":
            o["pins"] = {
                "SDA": claim(from_netlist.get("SDA"), "display SDA")
                or take(digital_free, "display SDA"),
                "SCL": claim(from_netlist.get("SCL"), "display SCL")
                or take(digital_free, "display SCL"),
            }
        elif o["kind"] == "serial":
            o["pin"] = "GP0" if board.family == "rp2040" else take(digital_free, "serial TX")
    missing = [i["label"] for i in inputs if not i.get("pin")]
    return {
        "pins_source": "board netlist"
        if from_netlist
        else "pin plan (the board is not routed yet)",
        "matrix": matrix,
        "pins_used": used,
        "pins_missing": missing,
    }
