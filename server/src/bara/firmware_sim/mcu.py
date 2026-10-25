"""MCU boards the simulator knows: GPIO lists, ADC pins, the on-board LED, pin drive and pull-up
figures, where the application image lives, and which emulator (if any) runs it.

Pin lists are from each vendor's published pinout (nice!nano v2 docs, Seeed XIAO nRF52840
wiki, Raspberry Pi Pico datasheet). Electrical figures are datasheet typicals: nRF52840 PS v1.7
(GPIO standard drive 2 mA, high drive 10 mA, pull-up 13 kOhm) and RP2040 datasheet 2.19.5
(4 mA default drive, 50-80 kOhm pulls).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Board:
    board_id: str
    label: str  # generic, shown to people: no maker or product names
    family: str  # nrf52840 | rp2040 | esp32 | avr | unknown
    core: str  # cortex-m4 | cortex-m0plus | xtensa | avr | host
    zig_target: str | None  # cross target for zig cc, None when no cross build is possible
    zig_cpu: str | None
    emulator: str  # unicorn-nrf52840 | unicorn-rp2040 | host
    gpio: list[str]
    adc: dict[str, int]  # pin -> ADC channel
    reserved: dict[str, str]  # pin -> why it is not free
    led_pin: str | None
    led_active_low: bool
    image_origin: int
    ram_origin: int
    ram_size: int
    flash_size: int
    uf2_family: int | None
    clock_hz: int
    drive_ma: float  # what a GPIO may source by default
    pullup_ohm: float
    vdd: float = 3.3
    notes: list[str] = field(default_factory=list)
    reference: str = ""  # the open board it follows, for generated-code comments only


def _p(port: int, pins: list[int]) -> list[str]:
    return [f"P{port}.{n:02d}" for n in pins]


NRF_ADC = {
    "P0.02": 0,
    "P0.03": 1,
    "P0.04": 2,
    "P0.05": 3,
    "P0.28": 4,
    "P0.29": 5,
    "P0.30": 6,
    "P0.31": 7,
}

BOARDS: dict[str, Board] = {
    "nice_nano_v2": Board(
        board_id="nice_nano_v2",
        label="Wireless controller board (nRF52840)",
        reference="nice!nano v2",
        family="nrf52840",
        core="cortex-m4",
        zig_target="thumb-freestanding-eabi",
        zig_cpu="cortex_m4",
        emulator="unicorn-nrf52840",
        gpio=[
            *_p(0, [6, 8, 17, 20, 22, 24, 11, 9, 10, 2, 29, 31]),
            *_p(1, [0, 4, 6, 11, 13, 15, 1, 2, 7]),
        ],
        adc=NRF_ADC,
        reserved={
            "P0.15": "on-board blue LED",
            "P0.13": "VCC cut-off switch",
            "P0.04": "battery voltage sense",
            "P0.18": "reset",
            "P0.00": "32 kHz crystal",
            "P0.01": "32 kHz crystal",
        },
        led_pin="P0.15",
        led_active_low=False,
        # Adafruit nRF52 bootloader with S140 6.1.1: the application starts at 0x26000
        image_origin=0x26000,
        ram_origin=0x20000000,
        ram_size=0x40000,
        flash_size=0x100000,
        uf2_family=0xADA52840,
        clock_hz=64_000_000,
        drive_ma=2.0,
        pullup_ohm=13_000.0,
    ),
    "xiao_nrf52840": Board(
        board_id="xiao_nrf52840",
        label="Compact wireless controller board (nRF52840)",
        reference="Seeed XIAO nRF52840",
        family="nrf52840",
        core="cortex-m4",
        zig_target="thumb-freestanding-eabi",
        zig_cpu="cortex_m4",
        emulator="unicorn-nrf52840",
        gpio=["P0.02", "P0.03", "P0.28", "P0.29", "P0.04", "P0.05", *_p(1, [11, 12, 13, 14, 15])],
        adc=NRF_ADC,
        reserved={
            "P0.26": "on-board red LED",
            "P0.30": "on-board green LED",
            "P0.06": "on-board blue LED",
            "P0.18": "reset",
        },
        led_pin="P0.26",
        led_active_low=True,
        # Seeed's Adafruit-derived bootloader with S140 7.3.0: application at 0x27000
        image_origin=0x27000,
        ram_origin=0x20000000,
        ram_size=0x40000,
        flash_size=0x100000,
        uf2_family=0xADA52840,
        clock_hz=64_000_000,
        drive_ma=2.0,
        pullup_ohm=13_000.0,
    ),
    "rpi_pico": Board(
        board_id="rpi_pico",
        label="Controller board (RP2040)",
        reference="Raspberry Pi Pico",
        family="rp2040",
        core="cortex-m0plus",
        zig_target="thumb-freestanding-eabi",
        zig_cpu="cortex_m0plus",
        emulator="unicorn-rp2040",
        gpio=[f"GP{n}" for n in [*range(0, 23), 26, 27, 28]],
        adc={"GP26": 0, "GP27": 1, "GP28": 2},
        reserved={
            "GP23": "SMPS power-save",
            "GP24": "VBUS sense",
            "GP25": "on-board LED",
            "GP29": "VSYS/3 sense",
            "GP0": "UART0 TX (serial console)",
            "GP1": "UART0 RX (serial console)",
        },
        led_pin="GP25",
        led_active_low=False,
        # a RAM image, the layout pico-sdk uses for no_flash UF2 builds
        image_origin=0x20000000,
        ram_origin=0x20000000,
        ram_size=0x42000,
        flash_size=0x200000,
        uf2_family=0xE48BFF56,
        clock_hz=12_000_000,
        drive_ma=4.0,
        pullup_ohm=50_000.0,
    ),
    "esp32": Board(
        board_id="esp32",
        label="Wireless controller board (ESP32)",
        reference="ESP32 dev board",
        family="esp32",
        core="xtensa",
        zig_target=None,
        zig_cpu=None,
        emulator="host",
        gpio=[
            f"GPIO{n}"
            for n in [2, 4, 5, 12, 13, 14, 15, 16, 17, 18, 19, 21, 22, 23, 25, 26, 27, 32, 33]
        ],
        adc={"GPIO32": 4, "GPIO33": 5, "GPIO34": 6, "GPIO35": 7},
        reserved={"GPIO1": "UART0 TX", "GPIO3": "UART0 RX", "GPIO0": "boot strap"},
        led_pin="GPIO2",
        led_active_low=False,
        image_origin=0,
        ram_origin=0,
        ram_size=0,
        flash_size=0,
        uf2_family=None,
        clock_hz=240_000_000,
        drive_ma=20.0,
        pullup_ohm=45_000.0,
        notes=["Xtensa cores need Espressif's toolchain, which LLVM upstream does not ship."],
    ),
    "avr": Board(
        board_id="avr",
        label="Controller board (ATmega32U4)",
        reference="Pro Micro",
        family="avr",
        core="avr",
        zig_target=None,
        zig_cpu=None,
        emulator="host",
        gpio=[
            "D0",
            "D1",
            "D2",
            "D3",
            "D4",
            "D5",
            "D6",
            "D7",
            "D8",
            "D9",
            "D10",
            "D14",
            "D15",
            "D16",
            "A0",
            "A1",
            "A2",
            "A3",
        ],
        adc={"A0": 7, "A1": 6, "A2": 5, "A3": 4},
        reserved={},
        led_pin="D17",
        led_active_low=True,
        image_origin=0,
        ram_origin=0,
        ram_size=0,
        flash_size=0,
        uf2_family=None,
        clock_hz=16_000_000,
        drive_ma=20.0,
        pullup_ohm=35_000.0,
        notes=["No AVR simulator (simavr) is installed here."],
    ),
}


def board_for(mcu_part: dict[str, Any] | None) -> Board:
    """The board record for the build's controller part: its id, its summary, then its part record
    (`record`: catalog or live source, which keeps the maker data the generic card drops:
    display_name, mpn, facets.mcu_family)."""
    card = (mcu_part or {}).get("card") or {}
    record = (mcu_part or {}).get("record") or {}
    blob = " ".join(
        str(x).lower()
        for x in (
            (mcu_part or {}).get("part_id"),
            card.get("display_name"),
            card.get("summary"),
            card.get("source_url"),
            (mcu_part or {}).get("display_name"),
            record.get("display_name"),
            record.get("mpn"),
            *(str(v) for v in (record.get("facets") or {}).values()),
        )
    )
    if "xiao" in blob and "nrf52" in blob:
        return BOARDS["xiao_nrf52840"]
    if re.search(r"nice.?nano|nrf52", blob):
        return BOARDS["nice_nano_v2"]
    if re.search(r"pico|rp2040", blob):
        return BOARDS["rpi_pico"]
    if "esp32" in blob:
        return BOARDS["esp32"]
    if re.search(r"32u4|atmega|pro.?micro", blob):
        return BOARDS["avr"]
    return BOARDS["rpi_pico"] if not blob.strip() else BOARDS["nice_nano_v2"]


def pin_number(board: Board, pin: str) -> int:
    """The number the HAL uses: port*32+pin on nRF52, the GPIO number elsewhere."""
    # a pad name can carry a suffix after the port and pin (nice!nano marks "P0.09-LF")
    m = re.match(r"P(\d)\.(\d+)(?!\d)", pin)
    if m:
        return int(m.group(1)) * 32 + int(m.group(2))
    m = re.search(r"(\d+)$", pin)
    return int(m.group(1)) if m else 255
