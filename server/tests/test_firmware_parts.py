"""ESPHome and Arduino firmware configure the sensor and display the build actually picked."""

from types import SimpleNamespace

from bara.live.firmware import make_firmware

ESP = {"part_id": "kicad:xiao_esp32c3", "display_name": "XIAO ESP32C3"}


def slot(slot_id: str, function_id: str, part: dict) -> SimpleNamespace:
    return SimpleNamespace(slot_id=slot_id, function_id=function_id, chosen=part, instances=[])


def files_of(slots: list[SimpleNamespace]) -> tuple[dict, list[dict]]:
    return make_firmware({"device": "clock", "features": []}, None, slots, None)


def test_clock_with_tmp117_and_seven_segment_writes_their_esphome_config() -> None:
    slots = [
        slot("controller", "compute.mcu", ESP),
        slot("sensor", "sense.temperature", {"part_id": "lcsc:C1", "display_name": "TMP117"}),
        slot(
            "display", "display.segment", {"part_id": "lcsc:C2", "display_name": "TM1637 4-digit"}
        ),
    ]
    record, checks = files_of(slots)
    text = "".join(f["content"] for f in record["files"])
    assert "platform: tmp117" in text and "bme280" not in text
    assert "platform: tm1637" in text and "platform: sntp" in text
    assert all(c["status"] == "pass" for c in checks if c["rule_id"] == "fw.driver.available")


def test_two_sensors_both_get_configured() -> None:
    slots = [
        slot("controller", "compute.mcu", ESP),
        slot("temp", "sense.temperature", {"part_id": "x", "display_name": "SHT31-DIS"}),
        slot("light", "sense.light", {"part_id": "y", "display_name": "VEML7700"}),
    ]
    text = "".join(f["content"] for f in files_of(slots)[0]["files"])
    assert "platform: sht3xd" in text and "platform: veml7700" in text


def test_arduino_uses_the_picked_sensor_library() -> None:
    slots = [
        slot("controller", "compute.mcu", {"part_id": "kicad:rp2040", "display_name": "RP2040"}),
        slot("sensor", "sense.temperature", {"part_id": "x", "display_name": "SHT31"}),
    ]
    text = "".join(f["content"] for f in files_of(slots)[0]["files"])
    assert "Adafruit_SHT31.h" in text and "BME280" not in text
