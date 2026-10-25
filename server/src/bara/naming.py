"""Generic part names for everything a person sees: what the part does, never who makes it.

A part card's display_name is filled here from the part's function id (the fixed vocabulary in
spec/schemas/vocab.schema.json) plus a few neutral facets (size, profile, wireless), so the
layers list, spec chips, inspector and simulator read "Tactile key switch", "Rotary encoder",
"Wireless controller board". Maker and MPN stay on the part record, where the shopping BOM
(bara.bom) reads them for buyers. Names come from the function, never from a list of products.
"""

from __future__ import annotations

import re
from typing import Any

# nouns for the function vocabulary; a function missing here is named from its id
NOUN: dict[str, str] = {
    "compute.mcu": "microcontroller",
    "compute.sbc": "single-board computer",
    "compute.fpga": "FPGA",
    "comms.ble": "Bluetooth radio",
    "comms.wifi": "Wi-Fi radio",
    "comms.lora": "LoRa radio",
    "comms.cellular": "cellular modem",
    "comms.nfc": "NFC reader",
    "comms.ir": "infrared transceiver",
    "comms.zigbee_thread": "Zigbee/Thread radio",
    "comms.ethernet": "Ethernet interface",
    "comms.can": "CAN transceiver",
    "comms.rs485": "RS-485 transceiver",
    "comms.usb_device": "USB interface",
    "comms.usb_host": "USB host interface",
    "comms.wired_link": "wired link connector",
    "input.key": "key switch",
    "input.key_matrix": "key matrix",
    "input.button": "push button",
    "input.rotary_encoder": "rotary encoder",
    "input.joystick": "thumb joystick",
    "input.potentiometer": "potentiometer",
    "input.touch": "touch sensor",
    "input.trackball": "trackball",
    "input.toggle_switch": "toggle switch",
    "sense.imu": "motion sensor (IMU)",
    "sense.gnss": "GNSS receiver",
    "sense.sound": "microphone",
    "sense.camera": "camera module",
    "sense.weight": "load cell",
    "sense.presence": "presence sensor",
    "display.oled": "OLED display",
    "display.lcd_char": "character LCD",
    "display.tft": "TFT display",
    "display.memory_lcd": "memory LCD",
    "display.epaper": "e-paper display",
    "display.led_matrix": "LED matrix",
    "display.seven_segment": "seven-segment display",
    "display.indicator_led": "indicator LED",
    "output.rgb_led": "RGB LED",
    "output.speaker": "speaker",
    "output.buzzer": "buzzer",
    "output.haptic": "vibration motor",
    "output.motor_dc": "DC motor",
    "output.motor_servo": "servo motor",
    "output.motor_stepper": "stepper motor",
    "output.relay": "relay",
    "output.pump": "pump",
    "output.solenoid": "solenoid",
    "output.heater": "heater",
    "output.fan": "fan",
    "power.battery": "battery",
    "power.coin_cell": "coin cell holder",
    "power.charger": "battery charger",
    "power.regulator": "voltage regulator",
    "power.usb_in": "USB power input",
    "power.solar": "solar panel",
    "power.switch": "power switch",
    "power.fuel_gauge": "battery gauge",
    "power.protection": "protection circuit",
    "storage.sd_card": "microSD slot",
    "storage.flash": "flash memory",
    "storage.eeprom": "EEPROM",
    "mech.enclosure": "enclosure",
    "mech.plate": "switch plate",
    "mech.keycap": "keycap",
    "mech.stabilizer": "stabilizer",
    "component.ic": "IC",
    "component.led": "LED",
    "interconnect.pcb": "keyboard PCB",
    "interconnect.cable": "cable",
}

_RADIOS = {"comms.ble", "comms.wifi", "comms.lora", "comms.zigbee_thread", "comms.cellular"}

_ACRONYM = {"co2": "CO2", "uv": "UV", "usb": "USB", "rgb": "RGB", "pcb": "PCB", "led": "LED"}

# neutral size and package words kept from a part's own name (never names: only numbers with
# units, resolutions, pin counts and standard package codes)
_QUALIFIERS = [
    re.compile(r"\b\d+(?:\.\d+)?\s?in\b"),
    re.compile(r"\b\d{2,4}\s?x\s?\d{2,4}\b"),
    re.compile(r"\b\d+(?:\.\d+)?\s?u\b"),
    re.compile(r"\b\d+-(?:pin|way)\b"),
    re.compile(
        r"\b(?:0201|0402|0603|0805|1206|1210|1812|SOT-23(?:-\d)?|SOD-\d+|DIP-\d+|SOIC-\d+|TO-\d+)\b"
    ),
    re.compile(r"\b\d+(?:\.\d+)?\s?mm\b"),
]


def _qualifier(name: str, noun: str) -> str:
    for rx in _QUALIFIERS:
        m = rx.search(name)
        if m and m.group(0).lower() not in noun.lower():
            return m.group(0).replace(" ", "")
    return ""


def _from_id(fn: str) -> str:
    """A noun from a function id the table does not list: sense.soil_moisture -> soil
    moisture sensor, interconnect.jst_ph -> jst ph connector."""
    group, _, leaf = fn.partition(".")
    words = " ".join(_ACRONYM.get(w, w) for w in leaf.split("_")).strip()
    suffix = {"sense": "sensor", "interconnect": "connector", "display": "display"}.get(group, "")
    if suffix and not words.endswith(suffix):
        words = f"{words} {suffix}".strip()
    return words or "part"


def _functions(part: dict[str, Any]) -> tuple[str, set[str]]:
    fns = part.get("functions") or []
    primary = str(part.get("primary_function") or "")
    if not primary:
        primary = next((f["function_id"] for f in fns if f.get("primary")), "")
    if not primary and fns:
        primary = str(fns[0].get("function_id") or "")
    return primary, {str(f.get("function_id")) for f in fns}


def generic_name(part: dict[str, Any]) -> str:
    """The generic name of a part record or card: its function as a noun, with neutral
    qualifiers from its facets (diagonal size, low profile, key units, wireless board)."""
    primary, all_fns = _functions(part)
    if not primary:
        return "Component"
    facets = part.get("facets") or {}
    noun = NOUN.get(primary) or _from_id(primary)
    kind = str(part.get("kind") or facets.get("kind") or "")
    radio = str(facets.get("wireless") or "none").lower() not in ("none", "no", "false")
    wireless = radio or bool(all_fns & _RADIOS)
    if primary == "compute.mcu":
        noun = "controller board" if kind == "module" else "microcontroller"
        if wireless:
            noun = "wireless " + noun
    elif primary == "input.key":
        style = str(facets.get("switch_type") or facets.get("actuation") or "").lower()
        adj = next((w for w in ("tactile", "linear", "clicky") if w in style), "")
        noun = f"{adj} key switch".strip()
        if str(facets.get("profile") or "").lower().startswith("low"):
            noun = "low-profile " + noun
    elif primary.startswith("comms.") and kind == "module":
        noun += " module"
    qual = _qualifier(str(part.get("display_name") or ""), noun)
    if qual and (primary.startswith(("display.", "mech.", "component.")) or "pin" in qual):
        noun = f"{qual} {noun}"
    return noun[:1].upper() + noun[1:]


def neutral(card: dict[str, Any], record: dict[str, Any] | None = None) -> dict[str, Any]:
    """The card with its display_name replaced by the generic name (in place, returned)."""
    src = {**(record or {}), **{k: v for k, v in card.items() if v not in (None, "")}}
    if record and record.get("facets"):
        src["facets"] = record["facets"]
    if record and record.get("functions"):
        src["functions"] = record["functions"]
    specs = card.get("key_specs") or []
    # a card's own spec chips stand in for facets its record lacks (radio, switch type)
    from_specs = {
        _SPEC_FACET[k]: s.get("value")
        for s in specs
        if (k := str(s.get("label") or "").lower()) in _SPEC_FACET
    }
    src["facets"] = {**from_specs, **(src.get("facets") or {})}
    card["display_name"] = generic_name(src)[:120]
    # family chips carry product and chip names; they stay on the record for the BOM
    card["key_specs"] = [
        s for s in specs if str(s.get("label") or "").lower() not in _FAMILY_LABELS
    ]
    return card


_SPEC_FACET = {
    "radio": "wireless",
    "wireless": "wireless",
    "type": "switch_type",
    "profile": "profile",
}
_FAMILY_LABELS = {
    "mcu",
    "family",
    "mcu family",
    "switch family",
    "chip",
    "brand",
    "maker",
    "manufacturer",
}
