"""A device requirement filters only the parts whose own job the slot is: a radio requirement
never empties a speaker slot because an audio controller offered there carries a radio facet.
An archetype's screen yields to the screen the prompt named."""

from __future__ import annotations

from typing import Any

from bara.live.archetype import apply
from bara.live.compose import Composer, Slot


def _composer(reqs: list[dict[str, Any]]) -> Composer:
    c = object.__new__(Composer)
    c.spec = {"hard_requirements": reqs, "soft_requirements": []}
    c.slots = []
    return c


def _part(pid: str, primary: str, other: str | None, facets: dict[str, Any]) -> dict[str, Any]:
    fns = [{"function_id": primary, "primary": True}]
    if other:
        fns.append({"function_id": other, "primary": False})
    return {"part_id": pid, "functions": fns, "facets": facets}


BLE = {"req_id": "r1", "facet": "wireless", "op": "eq", "value": "ble", "label": "BLE"}


def test_a_radio_requirement_does_not_filter_a_speaker_slot() -> None:
    slot = Slot("speaker", "Speaker", "output.speaker", "critical", 1, [])
    cands = [
        _part("mod:audio_mcu", "compute.mcu", "output.speaker", {"wireless": "none"}),
        _part("out:speaker", "output.speaker", None, {}),
    ]
    filters = _composer([BLE]).filters_for(slot, cands)
    assert not [f for f in filters if f.facet == "wireless"]


def test_a_radio_requirement_still_filters_radio_parts() -> None:
    slot = Slot("radio", "Radio", "comms.ble", "critical", 1, [])
    cands = [_part("rf:a", "comms.ble", None, {"wireless": "ble"})]
    filters = _composer([BLE]).filters_for(slot, cands)
    assert [f for f in filters if f.facet == "wireless"]


class _Source:
    def query(self, function: str | None = None, facets: Any = None, limit: int = 1) -> list:
        return [{"part_id": "x"}]


def test_the_named_screen_replaces_the_archetype_screen(tmp_path) -> None:
    arch = {
        "archetypes": [
            {
                "id": "a",
                "name": "a clock pattern",
                "source": {"kind": "pattern", "url": None},
                "words": ["clock"],
                "default_for": ["clock"],
                "brief": {},
                "functions": [
                    {
                        "function_id": "display.seven_segment",
                        "count": 4,
                        "any_of": ["display.seven_segment", "display.oled"],
                    },
                    {"function_id": "input.button", "count": 2},
                ],
                "form": None,
                "size_range_mm": None,
            }
        ]
    }
    import json

    path = tmp_path / "arch.json"
    path.write_text(json.dumps(arch))
    brief = {"device": "desk clock", "functions": ["compute.mcu", "display.epaper"]}
    apply("a desk clock with an e-paper display", brief, _Source(), path)
    assert "display.seven_segment" not in brief["functions"]
    assert "display.epaper" not in brief.get("function_counts", {})
    assert "input.button" in brief["functions"]
