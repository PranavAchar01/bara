"""A part the person typed by number is the part they get, and a sensor they never asked for
does not ride in on the brief's second reading of one they did ("proximity sensor" read as
presence and distance as well)."""

from __future__ import annotations

from typing import Any

from bara.live import completeness as cp
from bara.live.compose import names_typed_mpn, typed_mpns

MOUSE = (
    "an ergonomic mouse with a PAW3212 optical sensor, two main click 6x6 switches, an EC11 "
    "encoder, a slide switch, an IMU, a proximity sensor and an nRF52840 board"
)


def block(fid: str, label: str, **kw: Any) -> dict[str, Any]:
    return {"function_id": fid, "label": label, "count": 1, "search_terms": [], **kw}


def test_typed_part_numbers_are_read_from_the_prompt() -> None:
    typed = typed_mpns(MOUSE)
    assert {"paw3212", "nrf52840"} <= typed
    assert "6x6" not in typed and "ec11" not in typed
    assert names_typed_mpn({"mpn": "PAW3212DB-TJDT"}, typed)
    assert not names_typed_mpn({"display_name": "Trackball 34 mm"}, typed)


def test_sensors_the_prompt_never_names_are_dropped() -> None:
    explicit = ("sense.imu", "sense.proximity", "sense.camera", "sense.presence")
    spec: dict[str, Any] = {
        "prompt": MOUSE,
        "functions": [
            {"function_id": f, "required": True, "count": 1, "source": "explicit"}
            for f in (*explicit, "sense.distance", "input.toggle_switch")
        ],
    }
    blocks = {
        "device_class": "mouse",
        "portable": True,
        "blocks": [
            block("input.trackball", "PAW3212 optical tracking sensor", search_terms=["PAW3212"]),
            block("sense.imu", "6-axis IMU"),
            block("sense.proximity", "Infrared proximity sensor"),
            block("power.switch", "SPDT slide power switch"),
        ],
    }
    out = cp.apply(spec, {}, None, blocks)
    kept = {f["function_id"] for f in spec["functions"]}
    assert not kept & {"sense.camera", "sense.presence", "sense.distance", "input.toggle_switch"}
    assert {"sense.imu", "sense.proximity"} <= kept
    assert {d["function_id"] for d in out.dropped} >= {"sense.camera", "sense.distance"}


def test_a_named_sensor_the_diagram_missed_stays() -> None:
    spec: dict[str, Any] = {
        "prompt": "a plant monitor with a camera and a soil sensor",
        "functions": [
            {"function_id": "sense.camera", "required": True, "count": 1, "source": "explicit"}
        ],
    }
    cp.apply(spec, {}, None, {"device_class": "gadget", "blocks": [block("sense.soil", "Soil")]})
    assert any(f["function_id"] == "sense.camera" for f in spec["functions"])
