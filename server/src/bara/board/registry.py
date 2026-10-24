"""Role -> KiCad footprint records used when the catalog has no footprint for a part.

Data only. Footprint refs are 'lib/Pretty:Name' (see libs.LIBRARIES). Pin maps come from
the library symbol where one exists (symbol=...); maps marked hand_set were typed in from
the part's datasheet / breakout silkscreen and are listed in HAND_SET.
"""

from __future__ import annotations

# Key switches: hotswap footprints with the socket on B.Cu; the switch body model is the
# same library's switch model, added to the hotswap footprint.
SWITCHES: dict[str, dict] = {
    "choc": {
        "footprint": "kiswitch/Switch_Keyboard_Hotswap_Kailh:SW_Hotswap_Kailh_Choc_V1_1.00u",
        "extra_models": ["SW_Kailh_Choc_V1"],
        "pitch": (18.0, 17.0),  # Kailh Choc spacing (marbastlib footprint note "18x17 spacing")
        "pins": {"col": "1", "row_side": "2"},
        "label": "Kailh Choc v1 PG1350 hotswap",
        "height_mm": 8.0,  # PG1350 body+stem above PCB (CPG1350 datasheet 5.0 + 3.0 travel)
        # hand_set: Kailh Choc 1u keycap footprint 17.5 x 16.5 mm (Kailh CPG1350 keycap
        # drawing / MBK); top of cap about 3 mm above the stem.
        "keycap_mm": (17.5, 16.5),
        "keycap_top_mm": 11.0,
    },
    "mx": {
        "footprint": "kiswitch/Switch_Keyboard_Hotswap_Kailh:SW_Hotswap_Kailh_MX_1.00u",
        "extra_models": ["SW_Cherry_MX_PCB"],
        "pitch": (19.05, 19.05),
        "pins": {"col": "1", "row_side": "2"},
        "label": "Cherry MX hotswap (Kailh CPG151101S11)",
        "height_mm": 18.5,
        # hand_set: 1u MX keycap base 18 x 18 mm (Cherry/DSA common size); top ~7 mm above.
        "keycap_mm": (18.0, 18.0),
        "keycap_top_mm": 25.0,
    },
}

DIODE = {
    "footprint": "kicad/Diode_SMD:D_SOD-123",
    "pins": {"cathode": "1", "anode": "2"},  # KiCad diode convention: pad 1 = K
}

# Controllers, cheapest/smallest first. GPIO = symbol pins named P<port>.<pin> whose pad is
# on the module's two edge rows (castellations under the module are not counted).
CONTROLLERS: list[dict] = [
    {
        "id": "xiao_nrf52840",
        "label": "Seeed XIAO nRF52840",
        "footprint": "marbastlib/marbastlib-xp-promicroish:Xiao_nRF52840_ACH",
        "symbol": ("marbastlib", "marbastlib-promicroish.kicad_sym", "Seeeduino_Xiao_nRF52840"),
        "wireless": True,
        "power": {"GND": "GND", "3V3": "3V3", "BAT+": "BAT+", "BAT-": "GND", "RST": "RST"},
        "height_mm": 3.5,
    },
    {
        "id": "nice_nano_v2",
        "label": "nice!nano v2",
        "footprint": "marbastlib/marbastlib-xp-promicroish:nice_nano_H_USBup",
        "symbol": ("marbastlib", "marbastlib-promicroish.kicad_sym", "nice_nano"),
        "model": {
            "file": "garden36/nice_nano_v2.step",
            # Measured 2026-10-23 from the exported GLB: the STEP's long axis lies along X with
            # the USB-C end at -X (tall parts) and the bare antenna end at +X. The footprint is
            # USB-up (silk "USB" at y -16.2), so the model turns 90 deg and moves 1.36 mm up so
            # its PCB end meets the footprint's 33.02 mm outline (y -17.78..15.24).
            "offset": [0.0, 1.36, 0.0],
            "rotate": [0.0, 0.0, 90.0],
        },
        "wireless": True,
        "power": {"GND": "GND", "3V3": "3V3", "BAT+": "BAT+", "RST": "RST"},
        "height_mm": 3.2,
    },
]

ENCODER = {
    # marbastlib's EC11E footprint ships its own aligned STEP (ROT_EC11E.step); the KiCad
    # library footprint has none installed (Rotary_Encoder.3dshapes is not in packages3D).
    "footprint": "marbastlib/marbastlib-various:ROT_Alps_EC11E-Switch",
    "pins": {"A": "A", "B": "B", "common": "C", "push_a": "S1", "push_b": "S2"},
    # shaft top above PCB, measured from marbastlib's ROT_EC11E.step in the exported GLB
    "height_mm": 24.5,
    "label": "Alps EC11E rotary encoder with push switch",
}

SCREEN = {
    "footprint": "kicad/Display:Adafruit_SSD1306_No_Mounting_Holes",
    # hand_set: Adafruit 128x64 OLED breakout header order (DATA CLK DC RST CS 3V3 VIN GND)
    "pins": {"1": "SDA", "2": "SCL", "3": "GND", "4": "3V3", "7": "3V3", "8": "GND"},
    "height_mm": 4.5,
    "label": "SSD1306 128x64 OLED (Adafruit breakout)",
}

BATTERY_CONN = {
    "footprint": "kicad/Connector_JST:JST_PH_S2B-PH-SM4-TB_1x02-1MP_P2.00mm_Horizontal",
    "pins": {"1": "VBAT_IN", "2": "GND"},
    "label": "JST PH 2-pin battery connector",
    "height_mm": 6.0,
}
POWER_SWITCH = {
    "footprint": "kicad/Button_Switch_SMD:SW_SPDT_PCM12",
    "pins": {"2": "VBAT_IN", "1": "BAT+"},
    "label": "C&K PCM12 slide power switch",
    "height_mm": 2.5,
}
RESET = {
    "footprint": "kicad/Button_Switch_SMD:SW_SPST_SKQG_WithoutStem",
    "pins": {"1": "RST", "2": "GND"},
    "label": "Alps SKQG reset button",
    "height_mm": 2.5,
}
# Battery cell itself (not on the PCB): a LiPo pouch under the board. Dimensions from the
# common 301230 cell (3.0 x 12 x 30 mm) are a hand-set default when the catalog has none.
BATTERY_CELL = {"size_mm": (12.0, 30.0), "height_mm": 3.0, "label": "LiPo pouch 301230"}

SENSOR_LINK = {
    "footprint": "kicad/Connector_JST:JST_SH_SM07B-SRSS-TB_1x07-1MP_P1.00mm_Horizontal",
    "signals": ["3V3", "GND", "SCLK", "MOSI", "MISO", "NCS", "MOTION"],  # pins 1..7
    "label": "JST SH 7-pin sensor cable connector",
    "cable_mm": 100.0,
}
SENSOR = {
    "footprint": "fingerpunch/fingerpunch:PMW3360",
    # hand_set from the PMW3360DM-T2QU datasheet pin table
    "pins": {
        "1": "NCS",
        "2": "MISO",
        "3": "SCLK",
        "4": "MOSI",
        "5": "MOTION",
        "6": "3V3",
        "7": "GND",
        "8": "VDDPIX",
        "9": "VDD18",
        "10": "3V3",
    },
    "label": "PixArt PMW3360 optical sensor",
}
LDO = {
    "footprint": "kicad/Package_TO_SOT_SMD:SOT-23-5",
    # hand_set: TI TLV70018 (SOT-23-5 DBV) pin table: 1 IN, 2 GND, 3 EN, 5 OUT
    "pins": {"1": "3V3", "2": "GND", "3": "3V3", "5": "VDD18"},
    "label": "TLV70018 1.8 V LDO",
}
CAP = {"footprint": "kicad/Capacitor_SMD:C_0805_2012Metric", "label": "1 uF 0805"}
TRACKBALL = {"ball_mm": 34.0, "label": "34 mm trackball"}

HAND_SET = [
    "Adafruit SSD1306 breakout header pin order",
    "PMW3360 pin table (datasheet), TLV70018 SOT-23-5 pin table (datasheet)",
    "battery cell 301230 size when the catalog has no battery",
    "layout spacing defaults: column stagger profile, thumb fan angles, gap between halves",
    "rules: clearance 0.15 mm, track 0.2 mm, via 0.5/0.3 mm (JLCPCB 2-layer capable), "
    "edge clearance 0.3 mm, edge band 0.45 mm, board margin 1.0 mm, outline close radius 12 mm",
    "nice!nano STEP model offset/rotation onto its footprint",
    "keycap envelopes: Choc 17.5 x 16.5 mm (top 11 mm), MX 18 x 18 mm (top 25 mm); "
    "encoder bezel opening ring 1.5 + 1.0 mm",
    "Freerouting retry ladder: default, via_costs=100, start_ripup_costs=50, then 200",
]
