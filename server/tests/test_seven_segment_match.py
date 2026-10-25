"""A seven-segment block is matched on the words the KiCad library describes its modules with
(digits, colour, polarity), and a clock's time and temperature are one display, not two."""

from __future__ import annotations

from typing import Any

from bara.live import seven_seg
from bara.live.completeness import apply


def _sym(name: str, descr: str, pins: int = 12, model: bool = True) -> dict[str, Any]:
    return {
        "part_id": f"kicadgen:kicad:sym:Display_Character:{name}",
        "name": name,
        "display_name": f"{name} (Display_Character)",
        "summary": descr,
        "descr": descr,
        "fp_ok": True,
        "has_model": model,
        "facets": {"pin_count": pins},
        "functions": [{"function_id": "display.lcd_char", "primary": True}],
    }


LIBRARY = [
    _sym("CA56-12EWA", "4 digit 7 segment high efficiency red LED, common anode"),
    _sym("CC56-12EWA", "4 digit 7 segment high efficiency red LED, common cathode"),
    _sym("CC56-12CGKWA", "4 digit 7 segment green LED, common cathode"),
    _sym("DC56-11EWA", "Double digit 7 segment super bright red LED common cathode", 10),
    _sym("HDSP-A153", "One digit 7 segment red, common cathode", 10),
    _sym("DE122-XX-XX", "6 digit 7 segment reflective standard LCD, pin length 6.35mm", 14),
]


def _search(text: str, kind: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    return LIBRARY[:limit]


def test_digits_colour_and_polarity_are_read_from_words() -> None:
    want = seven_seg.want_from(
        "4 digits with colon, about 0.56 in digit height, red, common cathode"
    )
    assert (want.digits, want.colour, want.polarity, want.height_in) == (4, "red", "cathode", 0.56)
    assert seven_seg.want_from("Double digit module").digits == 2


def test_the_four_digit_red_common_cathode_module_wins() -> None:
    text = "4-digit 7-segment LED display module 4 digits, 0.56 in, red, common cathode"
    assert seven_seg.find(_search, text)["name"] == "CC56-12EWA"


def test_polarity_ranks_but_never_rejects() -> None:
    only_anode = [LIBRARY[0]]
    found = seven_seg.find(lambda *a, **k: only_anode, "4 digit red common cathode")
    assert found is not None and found["name"] == "CA56-12EWA"


def test_other_digit_counts_and_lcd_glass_are_not_it() -> None:
    assert seven_seg.find(_search, "6 digit display") is None  # the 6-digit one is LCD
    assert not seven_seg.meets_digits(LIBRARY[4], seven_seg.want_from("4 digit"))
    # a ten-pin single digit cannot drive four multiplexed digits, whatever it is called
    bare = {"display_name": "7-segment LED digit (LTS-6760)", "facets": {"pin_count": 10}}
    assert not seven_seg.meets_digits(bare, seven_seg.want_from("4 digits"))


def test_time_and_temperature_share_one_display() -> None:
    def block(label: str, req: str, count: int = 1) -> dict[str, Any]:
        return {
            "function_id": "display.seven_segment",
            "label": label,
            "requirement": req,
            "count": count,
            "search_terms": [],
            "kicad_names": [],
            "category": "output",
            "touchpoint": True,
            "why": "",
        }

    blocks = {
        "blocks": [
            block("4-digit 7-segment LED display module", "4 digits with colon, red", 4),
            block("2-digit 7-segment LED display module", "2 digits for temperature"),
        ]
    }
    out = apply({"prompt": "clock", "functions": []}, {}, blocks=blocks)
    displays = [n for n in out.needs.values() if n.function_id == "display.seven_segment"]
    assert len(displays) == 1
    assert displays[0].count == 1 and "4 digits" in displays[0].requirement


def _block(fid: str, label: str, touch: bool = True) -> dict[str, Any]:
    return {
        "function_id": fid,
        "label": label,
        "requirement": "",
        "count": 1,
        "search_terms": [],
        "kicad_names": [],
        "category": "output",
        "touchpoint": touch,
        "why": "",
    }


def test_a_led_digit_display_replaces_the_oled_the_brief_guessed() -> None:
    spec: dict[str, Any] = {
        "prompt": "a desk clock",
        "functions": [
            {"function_id": "display.oled", "required": True, "count": 1, "source": "explicit"}
        ],
        "hard_requirements": [{"facet": "display_type", "op": "eq", "value": "oled"}],
    }
    blocks = {"blocks": [_block("display.seven_segment", "4-digit 7-segment display")]}
    apply(spec, {}, blocks=blocks)
    assert not [f for f in spec["functions"] if f["function_id"] == "display.oled"]
    assert spec["hard_requirements"] == []


def test_a_room_temperature_sensor_is_not_a_touch_point() -> None:
    blocks = {
        "blocks": [
            _block("sense.temperature", "I2C temperature sensor"),
            _block("sense.proximity", "Proximity sensor"),
        ]
    }
    out = apply({"prompt": "clock", "functions": []}, {}, blocks=blocks)
    touch = {n.function_id: n.touch for n in out.needs.values()}
    assert touch["sense.temperature"] is False and touch["sense.proximity"] is True
