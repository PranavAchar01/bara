"""Product form, completeness invariants, quantity grouping and the fetch fallback.

No network, no KiCad, no model: the form is validated in code, the board placement runs on
synthetic footprints, and the LCSC fetch is a stub.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from shapely.geometry import Polygon

from bara.board.generic import form_region, place_in_form
from bara.board.layout import Item
from bara.board.libs import FootprintInfo, Pad
from bara.live import completeness as cp
from bara.live import form as fm
from bara.live import hero
from bara.live.fetch import Overlay, Resolver

PILL = [(-60, -20), (-40, -30), (40, -30), (60, -20), (60, 20), (40, 30), (-40, 30), (-60, 20)]
REFERENCE = {"products": ["x"], "width_mm": 120.0, "height_mm": 60.0, "thickness_mm": 20.0}


def make_form(**kw: Any) -> fm.Form:
    base: dict[str, Any] = {
        "device_class": "thing",
        "silhouette": [(float(x), float(y)) for x, y in PILL],
        "thickness_mm": 20.0,
        "edge_thickness_mm": 12.0,
        "anchors": [
            {
                "name": "keys",
                "slot_id": "keys",
                "purpose": "press",
                "mount": "front",
                "edge_normal_deg": 0.0,
                "pattern": "row",
                "centre": [0.0, 0.0],
                "pitch_mm": 10.0,
                "cols": 1,
                "count": 3,
            }
        ],
        "reference": dict(REFERENCE),
        "description": "a pill",
    }
    base.update(kw)
    return fm.Form(**base)


TOUCH = [fm.Touch("keys", "Keys", "input.button", 3)]


def test_valid_form_passes() -> None:
    assert fm.validate(make_form(), TOUCH) == []


def test_self_crossing_silhouette_is_rejected() -> None:
    bow = [(-50.0, -20.0), (50.0, 25.0), (50.0, -20.0), (-50.0, 10.0), (-20.0, 0.0)]
    problems = fm.validate(make_form(silhouette=bow), TOUCH)
    assert any("simple closed polygon" in p or "points" in p for p in problems)


def test_size_must_match_the_cited_reference() -> None:
    form = make_form(reference={**REFERENCE, "width_mm": 300.0, "height_mm": 150.0})
    assert any("use the real size" in p for p in fm.validate(form, TOUCH))


def test_every_touch_slot_needs_an_anchor() -> None:
    more = [*TOUCH, fm.Touch("port", "USB port", "power.usb_in", 1)]
    assert any("no anchor for port" in p for p in fm.validate(make_form(), more))


def test_anchor_outside_silhouette_is_rejected() -> None:
    form = make_form()
    form.anchors[0]["centre"] = [200.0, 0.0]
    assert any("outside the silhouette" in p for p in fm.validate(form, TOUCH))


def test_expand_patterns_give_one_spot_per_instance() -> None:
    a = {"pattern": "grid", "centre": [0, 0], "pitch_mm": 10, "cols": 2}
    assert len(fm.expand(a, 5)) == 5
    assert len(fm.expand({**a, "pattern": "ring"}, 6)) == 6
    assert fm.expand({**a, "pattern": "diamond"}, 4)[0] == (0.0, 10.0)


def _item(ref: str, role: str, slot: str, w: float = 6.0, near: Item | None = None) -> Item:
    fp = FootprintInfo(
        "t",
        Path("t.pretty"),
        ref,
        [Pad("1", "smd", 0, 0, 1, 1, ["F.Cu"])],
        (-w / 2, -w / 2, w / 2, w / 2),
        None,
        [],
    )
    it = Item(ref, role, fp, 0, 0, 0, "top", meta={"slot_id": slot})
    if near is not None:
        it.meta["near"] = near
    return it


def test_parts_snap_to_anchors_inside_the_inset_silhouette() -> None:
    mcu = _item("U1", "mcu", "controller", 12.0)
    keys = [_item(f"SW{i}", "button", "keys") for i in range(3)]
    cap = _item("C1", "cap", "controller", 3.0, near=mcu)
    pf = {
        "silhouette": [list(p) for p in PILL],
        "anchors": [
            {**make_form().anchors[0], "centre": [30.0, 0.0], "pitch_mm": 12.0, "count": 3},
        ],
    }
    outline = place_in_form([mcu, *keys, cap], mcu, pf, [])
    region = form_region(pf, pf.get("scale", 1.0))
    assert outline.equals(region) or outline.area == pytest.approx(region.area, rel=0.3)
    for it in [mcu, *keys, cap]:
        assert outline.buffer(0.01).contains(it.footprint_poly()), it.ref
    # keys sit near the anchor (board y is flipped, the row is horizontal so x is enough)
    xs = [k.centre()[0] for k in keys]
    assert min(xs) > 10.0 and max(xs) < 50.0
    assert abs(cap.centre()[0] - mcu.centre()[0]) < 12.0


def test_overflow_never_scales_the_form() -> None:
    parts = [_item(f"U{i}", "ic", "x", 20.0) for i in range(40)]
    log: list[str] = []
    pf = {"silhouette": [list(p) for p in PILL], "anchors": []}
    place_in_form(parts, None, pf, log)
    assert any("FORM_OVERFLOW" in line for line in log)
    assert "scale" not in pf or pf["scale"] == 1.0


def test_through_hole_part_takes_only_its_lead_hull_from_the_other_side() -> None:
    # a 24 x 24 module whose leads run along one edge leaves the rest of the back free
    module = _item("M1", "module", "x", 24.0)
    module.fp.pads[:] = [
        Pad(str(i), "thru_hole", -11.0, i * 2.54 - 10, 1.7, 1.7, ["*.Cu"]) for i in range(8)
    ]
    smd = [_item(f"U{i}", "ic", "x", 10.0) for i in range(2)]
    pf = {"silhouette": [[-20, -20], [20, -20], [20, 20], [-20, 20]], "anchors": []}
    log: list[str] = []
    place_in_form([module, *smd], None, pf, log)
    assert pf["fit_report"]["ok"], log
    assert {u.side for u in smd} == {"bottom"} or any(u.side == "bottom" for u in smd)


def test_overflow_report_carries_the_numbers_the_form_is_redrawn_with() -> None:
    from bara.live.form import fit_note

    parts = [_item(f"U{i}", "ic", "x", 20.0) for i in range(40)]
    pf = {"silhouette": [list(p) for p in PILL], "anchors": []}
    place_in_form(parts, None, pf, [])
    rep = pf["fit_report"]
    assert rep["ok"] is False and rep["parts_mm2"] > rep["usable_mm2"] > 0
    assert str(rep["parts_mm2"]) in fit_note(rep) and "Redraw the SAME product" in fit_note(rep)


def test_declared_product_size_is_kept_by_the_fit_redraw() -> None:
    from bara.live.form import declared_size, fit_note

    assert declared_size("a 12 x 6 cm tracker") == (120.0, 60.0)
    assert declared_size("a 60 gram mouse") is None
    rep = {"parts_mm2": 900, "usable_mm2": 700, "declared_mm": [120.0, 60.0]}
    assert "keep the silhouette at that size" in fit_note(rep)


def test_inputs_become_a_diode_matrix_when_gpio_runs_short() -> None:
    from bara.board.generic import _matrix_inputs

    mcu = _item("U1", "mcu", "controller", 12.0)
    mcu.meta["pins"] = {str(i): f"GPIO{i}" for i in range(1, 9)}  # eight free pins
    keys = []
    for i in range(12):  # twelve buttons would need twelve pins
        k = _item(f"SW{i}", "button", "keys")
        k.fp.pads.append(Pad("2", "smd", 1, 0, 1, 1, ["F.Cu"]))
        k.pads = {"1": f"SW_{i}", "2": "GND"}
        keys.append(k)
    log: list[str] = []
    items = [mcu, *keys]
    _matrix_inputs(items, mcu, log)
    nets = {v for k in keys for v in k.pads.values()}
    assert {n for n in nets if n.startswith(("ROW", "COL"))} <= {
        *(f"ROW{r}" for r in range(6)),
        *(f"COL{c}" for c in range(6)),
    }
    assert len([it for it in items if it.role == "diode"]) == 12
    rows = {n for n in nets if n.startswith("ROW")}
    cols = {n for n in nets if n.startswith("COL")}
    assert len(rows) + len(cols) <= 8 and "matrix" in log[-1]


# ---------------------------------------------------------------- completeness


def block(fid: str, label: str, count: int = 1, **kw: Any) -> dict[str, Any]:
    return {
        "category": "input",
        "function_id": fid,
        "label": label,
        "count": count,
        "search_terms": [],
        "kicad_names": [],
        "touchpoint": True,
        **kw,
    }


def test_blocks_become_one_need_per_identity_with_a_count() -> None:
    spec: dict[str, Any] = {"functions": []}
    blocks = {
        "device_class": "gadget",
        "mains_input": False,
        "portable": True,
        "avg_current_ma": 40,
        "shell_g": 20,
        "blocks": [
            block("input.button", "Face buttons", 4),
            block("input.button", "Face buttons", 2),
            block("input.button", "Shoulder buttons", 2),
        ],
    }
    out = cp.apply(spec, {}, None, blocks)
    keys = [n for n in out.needs.values() if n.function_id == "input.button"]
    assert [n.count for n in keys] == [8]
    assert len(keys[0].groups) == 3
    assert all(n.touch for n in keys)


def test_same_function_blocks_merge_even_when_named_differently_but_ics_do_not() -> None:
    spec: dict[str, Any] = {"functions": []}
    blocks = {
        "device_class": "gadget",
        "mains_input": False,
        "portable": True,
        "avg_current_ma": 40,
        "shell_g": 20,
        "blocks": [
            block("input.button", "Play", 1, search_terms=["TS-1187A"]),
            block("input.button", "Menu", 2, search_terms=["tactile switch"]),
            block("component.ic", "DAC", 1, search_terms=["PCM5102A"]),
            block("component.ic", "Amp", 1, search_terms=["TPA6132A2"]),
        ],
    }
    out = cp.apply(spec, {}, None, blocks)
    buttons = [n for n in out.needs.values() if n.function_id == "input.button"]
    ics = [n for n in out.needs.values() if n.function_id == "component.ic"]
    assert [n.count for n in buttons] == [3] and set(buttons[0].terms) >= {"TS-1187A"}
    assert len(ics) == 2


def test_block_audit_adds_the_missing_links_of_a_chain(monkeypatch: Any) -> None:
    import asyncio

    from bara.live import blocks as bl

    calls: list[str] = []

    async def fake_ask(system: str, user: str, schema: Any, **kw: Any) -> Any:
        calls.append(kw["name"])
        if kw["name"] == "blocks":
            return {
                "device_class": "player",
                "mains_input": False,
                "portable": True,
                "avg_current_ma": 40,
                "shell_g": 30,
                "blocks": [block("output.speaker", "Speaker", 1, search_terms=["CMR-1206S"])],
            }, ""
        if kw["name"] == "block_audit":
            assert "Speaker" in user
            return {
                "missing": [block("component.ic", "Audio amplifier", 1, search_terms=["PAM8403"])]
            }, ""
        return {"blocks": []}, ""

    monkeypatch.setattr(bl, "ask_json", fake_ask)
    data, _ = asyncio.run(bl.derive("a player", ["output.speaker", "component.ic"]))
    assert data is not None
    assert [b["label"] for b in data["blocks"]] == ["Speaker", "Audio amplifier"]
    assert calls[:2] == ["blocks", "block_audit"]


def test_every_device_gets_a_controller_and_a_power_path() -> None:
    spec: dict[str, Any] = {"functions": []}
    blocks = {
        "device_class": "gadget",
        "mains_input": False,
        "portable": True,
        "avg_current_ma": 10,
        "shell_g": 5,
        "blocks": [block("input.button", "Button")],
    }
    cp.apply(spec, {}, None, blocks)
    fids = {f["function_id"] for f in spec["functions"]}
    assert "compute.mcu" in fids
    assert "power.battery" in fids


def test_mains_gate_follows_the_model_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter([({"low_voltage_half": True, "reason": "x"}, ""), (None, "no key")])

    async def fake(*a: Any, **k: Any) -> Any:
        return next(answers)

    monkeypatch.setattr("bara.live.ask.ask_json", fake)
    assert asyncio.run(cp.low_voltage_mains("anything")) is True
    assert asyncio.run(cp.low_voltage_mains("anything")) is False  # no answer: out of scope
    assert asyncio.run(cp.low_voltage_mains("a jammer")) is False  # unsafe never asks the model


def test_battery_limits_follow_the_spec_numbers() -> None:
    c = cp.Completeness(numbers={"hours": 10.0, "mass_g": 60.0, "avg_current_ma": 20.0})
    lo, hi = cp.battery_limits(c)
    assert lo == pytest.approx(240.0)
    assert hi is not None and hi > lo


# ---------------------------------------------------------------- fetch fallback


def test_missing_part_is_fetched_cached_and_misses_are_remembered(tmp_path: Path) -> None:
    class Source:
        name = "stub"

        def query(self, *a: Any, **k: Any) -> list[dict[str, Any]]:
            return []

        def get_part(self, part_id: str) -> dict[str, Any]:
            raise KeyError(part_id)

    path = tmp_path / "fetched.jsonl"
    calls: list[str] = []

    def cli(term: str, function: str, timeout: float) -> tuple[int, str]:
        calls.append(term)
        if term != "GOOD123":
            return 1, "no match"
        row = {
            "part_id": "fetched:good123",
            "display_name": "GOOD123 sensor",
            "functions": [{"function_id": "sense.motion", "primary": True}],
        }
        with path.open("a") as f:
            f.write(json.dumps(row) + "\n")
        return 0, "fetched:good123"

    need = cp.Need("m", "sense.motion", "Motion", terms=("BAD1", "GOOD123"))
    r = Resolver(Overlay(Source()), cli=cli, fetched_path=path)
    part = r.fetch(need)
    assert part is not None and part["part_id"] == "fetched:good123"
    assert calls == ["BAD1", "GOOD123"]
    # second resolver: the cache answers without the network
    again = Resolver(Overlay(Source()), cli=cli, fetched_path=path).fetch(need)
    assert again is not None and calls == ["BAD1", "GOOD123"]
    # a term with no match is a loud note, not a part
    miss = cp.Need("z", "sense.motion", "Other", terms=("NOPE9",))
    r2 = Resolver(Overlay(Source()), cli=cli, fetched_path=path)
    assert r2.fetch(miss) is None and "NOPE9" in r2.notes["z"]


def test_unresolved_block_is_retried_with_relaxed_names(monkeypatch: Any) -> None:
    import asyncio

    from bara.live import compose as cmp

    seen: list[str] = []

    class FakeResolver:
        rejected: set[str] = set()
        notes: dict[str, str] = {}

        def generated(self, need: Any) -> Any:
            seen.append("gen:" + ",".join(need.kicad))
            return (
                {"part_id": "kicadgen:ok", "display_name": "ok"} if "Family" in need.kicad else None
            )

        def fetch(self, need: Any) -> Any:
            return None

    async def fake_ask(system: str, user: str, schema: Any, **kw: Any) -> Any:
        assert "Already tried: BAD1" in user
        return {"search_terms": [], "kicad_names": ["Family"]}, ""

    monkeypatch.setattr(cmp, "ask_json", fake_ask)
    comp = object.__new__(cmp.Composer)
    comp.resolver = FakeResolver()  # type: ignore[assignment]
    comp.extra, comp.fetched = {}, []
    comp.next_warning = lambda prefix: prefix + "1"  # type: ignore[method-assign]
    comp.vet = lambda slot, parts: asyncio.sleep(0, parts)  # type: ignore[method-assign]
    need = cp.Need("lcd", "display.lcd", "LCD", terms=("BAD1",), kicad=("Nope",))
    slot = cmp.Slot("lcd", "LCD", "display.lcd", "required", 1, [], need=need)
    asyncio.run(comp.resolve_missing(slot, lambda *a, **k: None))
    assert comp.extra["lcd"][0]["part_id"] == "kicadgen:ok"
    assert seen == ["gen:Nope", "gen:Nope,Family"]


def test_optional_slot_without_a_part_is_dropped_not_failed() -> None:
    from bara.live import compose as cmp

    rows = {
        c["check_key"]: c
        for c in (
            cmp.slot_check(cmp.Slot("mount", "Mount", "mech.mount", "optional", 1, [])),
            cmp.slot_check(cmp.Slot("mcu", "MCU", "component.ic", "critical", 2, [])),
        )
        if c is not None
    }
    assert rows["slot.optional_missing:mount"]["status"] == "unknown"
    assert "left out" in rows["slot.optional_missing:mount"]["message"]
    assert rows["slot.critical_filled:mcu"]["status"] == "fail"


def test_drc_errors_from_tight_copper_get_one_wide_rules_pass(
    tmp_path: Path, monkeypatch: Any
) -> None:
    from types import SimpleNamespace

    import bara.board as B
    from bara.board import kicad as K

    seen: list[float] = []
    state = {"rules": K.RULES}

    def build(plan_path: Path) -> None:
        state["rules"] = json.loads(plan_path.read_text())["rules"]
        plan_path.with_name("main.kicad_pcb").write_text(str(state["rules"]["clearance_mm"]))

    def drc(board: Path) -> dict[str, Any]:
        wide = state["rules"]["clearance_mm"] > K.RULES["clearance_mm"]
        seen.append(state["rules"]["clearance_mm"])
        errors = 0 if wide else 2
        return {
            "errors": errors,
            "warnings": 0,
            "unconnected": 0,
            "unconnected_nets": [],
            "by_type": {"error:clearance": errors} if errors else {},
        }

    monkeypatch.setattr(K, "plan_json", lambda plan, pcb, dsn: {"rules": K.RULES, "footprints": []})
    monkeypatch.setattr(K, "build_pcb", build)
    monkeypatch.setattr(K, "freeroute", lambda *a, **k: {"seconds": 0.1, "passes": 1})
    monkeypatch.setattr(K, "import_ses", lambda *a: None)
    monkeypatch.setattr(K, "run_drc", drc)
    monkeypatch.setattr(K, "export_glb", lambda *a, **k: None)
    monkeypatch.setattr(K, "count_routing", lambda pcb: {"tracks": 1})
    res = B._route_one(
        SimpleNamespace(name="b"), tmp_path / "w", tmp_path / "g", (0.0, 0.0), 600.0, 5,
        lambda *a, **k: None,
    )  # fmt: skip
    assert res["drc"]["errors"] == 0
    assert res["routing"]["strategy"] == "wide_rules"
    assert seen[-1] == K.WIDE_RULES["clearance_mm"] and len(seen) == len(K.ROUTE_STRATEGIES) + 1


# ---------------------------------------------------------------- hero renderer


def test_hero_renders_a_png_of_a_box() -> None:
    import numpy as np

    v = np.array([[x, y, z] for x in (0, 40) for y in (0, 40) for z in (0, 10)], dtype=float)
    tris = np.array(
        [[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1], [2, 3, 7], [2, 7, 6]]
    )
    png = hero.render([(v, tris, (0.5, 0.6, 0.7))], (20, -120, 90), (20, 20, 5), size=160)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert Polygon(PILL).is_valid
