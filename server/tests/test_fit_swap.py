"""A part with no free spot in the product is swapped for a smaller candidate of its slot.

No network, no KiCad: synthetic footprints, a stub part source and a stub board planner.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from bara.board.generic import place_in_form
from bara.board.layout import Item
from bara.board.libs import FootprintInfo, Pad
from bara.live import runner as R
from bara.live.compose import Composer, ComposeResult, Instance, Slot

PILL = [(-60, -20), (-40, -30), (40, -30), (60, -20), (60, 20), (40, 30), (-40, 30), (-60, 20)]


def _bar(ref: str, w: float, h: float, iid: str) -> Item:
    fp = FootprintInfo(
        "t", Path("t.pretty"), ref, [Pad("1", "smd", 0, 0, 1, 1, ["F.Cu"])],
        (-w / 2, -h / 2, w / 2, h / 2), None, [],
    )  # fmt: skip
    return Item(ref, "battery", fp, 0, 0, 0, "top", label=ref, meta={"instance_id": iid})


def test_overflow_report_names_the_stuck_part_and_its_size() -> None:
    pf = {"silhouette": [list(p) for p in PILL], "anchors": []}
    place_in_form([_bar("BT1", 150.0, 20.0, "bat_main")], None, pf, [])
    stuck = pf["fit_report"]["stuck"]
    assert stuck["instance_id"] == "bat_main"
    assert max(stuck["mm"]) == 150.0 and stuck["mm2"] == 3000


def test_place_in_form_that_fits_reports_no_stuck_part() -> None:
    pf = {"silhouette": [list(p) for p in PILL], "anchors": []}
    place_in_form([_bar("BT1", 30.0, 10.0, "bat_main")], None, pf, [])
    assert pf["fit_report"]["ok"] and "stuck" not in pf["fit_report"]


def _box(w: float, h: float) -> dict[str, Any]:
    return {"mechanical": {"bbox_mm": {"min": [0, 0, 0], "max": [w, h, 5]}}}


def test_resize_repicks_the_slot_with_the_first_ranked_part_that_fits() -> None:
    comp = Composer.__new__(Composer)
    slot = Slot("battery", "Battery", "power.battery", "required", 3, [Instance("bat", "none", 1)])
    big, mid, small = ({"part_id": p, "display_name": p} for p in ("big", "mid", "small"))
    slot.chosen = big
    comp.slots = [slot]
    comp.result = ComposeResult(slots=[slot], parts=[{"instance_id": "bat", "part_id": "big"}])
    comp.narrow = lambda s: ([], [big, mid, small], [])  # type: ignore[method-assign]
    comp.next_decision = lambda: "d1"  # type: ignore[method-assign]
    comp.propagated = lambda s: []  # type: ignore[method-assign]
    comp.sized_part = lambda s, i, p: p  # type: ignore[method-assign]
    comp.build_part = lambda s, i, p: {"instance_id": i.instance_id, "part_id": p["part_id"]}  # type: ignore[method-assign]
    comp.connections_for = lambda s, ps: []  # type: ignore[method-assign]
    events: list[tuple[str, dict[str, Any]]] = []
    got = comp.resize(
        "bat",
        lambda p: p["part_id"] == "small",
        "too long",
        lambda t, p, **_: events.append((t, p)),
    )
    assert got is small and slot.chosen is small
    assert comp.result.parts == [{"instance_id": "bat", "part_id": "small"}]
    kinds = [t for t, _ in events]
    assert "decision.made" in kinds and "part.updated" in kinds
    assert comp.resize("bat", lambda p: False, "x", lambda *a, **k: None) is None


class _Source:
    RECORDS = {"holder": _box(88, 22), "aa": _box(60, 16), "pouch": _box(30, 12)}

    def get_part(self, pid: str) -> dict[str, Any]:
        return self.RECORDS[pid]


class _Composer:
    def __init__(self, result: ComposeResult) -> None:
        self.result = result
        self.asked: list[str] = []

    def resize(self, iid: str, fits: Any, why: str, emit: Any) -> dict[str, Any] | None:
        current = self.result.parts[0]["part_id"]
        for pid in ("holder", "aa", "pouch"):
            if pid != current and fits({"part_id": pid}):
                self.asked.append(pid)
                self.result.parts = [{"instance_id": iid, "part_id": pid}]
                return {"part_id": pid, "display_name": pid}
        return None


def test_swap_to_fit_swaps_until_the_board_fits(monkeypatch: Any) -> None:
    result = ComposeResult(slots=[], parts=[{"instance_id": "bat", "part_id": "holder"}])
    gb: dict[str, Any] = {"product_form": {}}

    def plan(gb_: dict[str, Any], parts: list[dict[str, Any]], bid: str) -> tuple[dict, None]:
        pid = parts[0]["part_id"]
        w, h = _Source.RECORDS[pid]["mechanical"]["bbox_mm"]["max"][:2]
        ok = w < 40  # only the pouch fits this product
        rep = {"ok": ok}
        if not ok:
            rep["stuck"] = {"instance_id": "bat", "part": pid, "mm": [w, h], "mm2": w * h}
        gb_["product_form"]["fit_report"] = rep
        return {"boards": []}, None

    monkeypatch.setattr(R.A, "plan_board", plan)
    lr = R.LiveRunner.__new__(R.LiveRunner)
    lr.source = _Source()
    warned: list[str] = []
    lr._warn = lambda run, stage, wid, code, sev, msg: warned.append(msg)  # type: ignore[method-assign]

    class Run:
        build_id = "b_test"

    run = Run()
    run.live_composer = _Composer(result)  # type: ignore[attr-defined]
    board, err = plan(gb, [{"part_id": "holder"}], "b_test")

    class St:
        def emit(self, *a: Any, **k: Any) -> None:
            pass

    board, err, parts = asyncio.run(
        lr._swap_to_fit(run, St(), gb, result, [], board, err)  # type: ignore[arg-type]
    )
    assert gb["product_form"]["fit_report"]["ok"]
    assert run.live_composer.asked == ["aa", "pouch"]  # type: ignore[attr-defined]
    assert parts[0]["part_id"] == "pouch" and len(warned) == 2


class _TallSource:
    RECORDS = {
        "nine_volt": {"mechanical": {"bbox_mm": {"min": [0, 0, 0], "max": [55, 31, 26.9]}}},
        "pouch": {"facets": {}},  # an off-board cell with no stated height
    }

    def get_part(self, pid: str) -> dict[str, Any]:
        return self.RECORDS[pid]


def test_a_part_far_taller_than_the_product_is_swapped_for_a_lower_one(monkeypatch: Any) -> None:
    result = ComposeResult(slots=[], parts=[{"instance_id": "bat", "part_id": "nine_volt"}])

    def plan(gb_: dict[str, Any], parts: list[dict[str, Any]], bid: str) -> tuple[dict, None]:
        h = 26.9 if parts[0]["part_id"] == "nine_volt" else 3.0
        pl = {"for_instance_id": "bat", "side": "bottom", "height_mm": h}
        return {"boards": [{"thickness_mm": 1.6, "placements": [pl]}]}, None

    class Composer_:
        def resize(self, iid: str, fits: Any, why: str, emit: Any) -> dict[str, Any] | None:
            if fits({"part_id": "pouch"}):
                result.parts = [{"instance_id": iid, "part_id": "pouch"}]
                return {"part_id": "pouch", "display_name": "pouch"}
            return None

    monkeypatch.setattr(R.A, "plan_board", plan)
    lr = R.LiveRunner.__new__(R.LiveRunner)
    lr.source = _TallSource()
    warned: list[str] = []
    lr._warn = lambda run, stage, wid, code, sev, msg: warned.append(msg)  # type: ignore[method-assign]

    class Run:
        build_id = "b_test"
        live_composer = Composer_()

    class St:
        def emit(self, *a: Any, **k: Any) -> None:
            pass

    class Product:
        thickness_mm = 15.0

    parts = [
        {"instance_id": "bat", "part_id": "nine_volt", "record": _TallSource.RECORDS["nine_volt"]}
    ]
    board, err = plan({}, parts, "b_test")
    board, err, parts = asyncio.run(
        lr._swap_to_thickness(Run(), St(), {}, result, parts, board, err, Product())  # type: ignore[arg-type]
    )
    assert parts[0]["part_id"] == "pouch" and len(warned) == 1
    assert lr._stack_mm(board)[0] < 15.0 * R.LiveRunner.THICK_SLACK


def _disc(r: float, n: int = 48) -> list[list[float]]:
    import math

    turn = [2 * math.pi * k / n for k in range(n)]
    return [[r * math.cos(a), r * math.sin(a)] for a in turn]


def test_a_tight_form_packs_on_both_sides_before_it_overflows() -> None:
    # a small round tag: a sounder the form anchors on the face fills the middle, and the
    # controller has no room beside it on that side, but the back of the board is free
    pf = {
        "silhouette": _disc(17.0),
        "anchors": [
            {
                "slot_id": "sounder",
                "centre": [0.0, 0.0],
                "mount": "front",
                "count": 1,
                "pattern": "single",
            }
        ],
    }
    sounder = _bar("LS1", 12.0, 12.0, "sounder")
    sounder.role = "buzzer"
    sounder.meta["slot_id"] = "sounder"
    mcu = _bar("U1", 18.0, 12.0, "mcu")
    mcu.role = "mcu"
    log: list[str] = []
    place_in_form([sounder, mcu], mcu, pf, log)
    assert pf["fit_report"]["ok"], log
    assert sounder.side == "top" and mcu.side == "bottom"
