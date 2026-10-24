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
        # courtyards stay clear of the outline by the copper-to-edge clearance
        assert outline.buffer(-0.45).contains(it.footprint_poly()), it.ref
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


def test_a_part_number_fetched_under_another_function_serves_the_block_that_names_it(
    tmp_path: Path,
) -> None:
    class Source:
        name = "stub"

        def query(self, *a: Any, **k: Any) -> list[dict[str, Any]]:
            return []

        def get_part(self, part_id: str) -> dict[str, Any]:
            raise KeyError(part_id)

    path = tmp_path / "fetched.jsonl"
    row = {
        "part_id": "lcsc:pmw3360dm_t2qu_c1",
        "display_name": "PMW3360DM-T2QU (PixArt)",
        "mpn": "PMW3360DM-T2QU",
        "functions": [{"function_id": "component.ic", "primary": True}],
    }
    path.write_text(json.dumps(row) + "\n")

    def cli(term: str, function: str, timeout: float) -> tuple[int, str]:
        raise AssertionError("the cache should answer")

    need = cp.Need("s", "sense.motion", "Motion sensor", terms=("PMW3360DM-T2QU",))
    part = Resolver(Overlay(Source()), cli=cli, fetched_path=path).fetch(need)
    assert part is not None and part["functions"][0]["function_id"] == "sense.motion"
    # a description search never borrows a row filed under another function
    vague = cp.Need("v", "sense.motion", "pmw3360dm t2qu", terms=())
    calls: list[str] = []
    r = Resolver(
        Overlay(Source()), cli=lambda t, f, s: (calls.append(t), (1, "no"))[1], fetched_path=path
    )
    assert r.fetch(vague) is None


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
        SimpleNamespace(name="b", items=[]), tmp_path / "w", tmp_path / "g", (0.0, 0.0), 600.0, 5,
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


def test_footprintless_module_becomes_an_off_board_item_with_a_board_connector() -> None:
    from bara.board.generic import plan_device_board

    def rec(name: str, role: str, bbox: Any = None) -> dict[str, Any]:
        r: dict[str, Any] = {"display_name": name, "role": role, "kind": "module"}
        if bbox:
            r["mechanical"] = {"bbox_mm": bbox}
        return r

    parts = [
        {
            "instance_id": "i1", "part_id": "p1", "slot_id": "panel", "quantity": 1,
            "label": "Panel",
            "record": rec("Panel", "screen", {"min": [0, 0, 0], "max": [60, 40, 3]}),
        },
    ]  # fmt: skip
    plan = plan_device_board(parts, [], {})
    mods = [i for i in plan.items if i.role == "module"]
    assert len(mods) == 1 and not mods[0].on_pcb and mods[0].size_mm == (60.0, 40.0)
    assert any(i.role == "module_connector" for i in plan.items)


def test_fetch_falls_back_to_a_description_when_no_part_number_matches(tmp_path: Path) -> None:
    class Source:
        name = "stub"

        def query(self, *a: Any, **k: Any) -> list[dict[str, Any]]:
            return []

    calls: list[str] = []

    def cli(term: str, function: str, timeout: float) -> tuple[int, str]:
        calls.append(term)
        return 1, "no match"

    r = Resolver(Overlay(Source()), cli=cli, fetched_path=tmp_path / "f.jsonl")
    need = cp.Need("v", "output.motor", "ERM rumble motor", terms=("RF-300",))
    assert r.fetch(need) is None
    assert calls == ["RF-300", "keyword:ERM rumble motor"]
    named = cp.Need("c", "component.ic", "Some IC", terms=("X1",))
    calls.clear()
    r.fetch(named)
    assert calls == ["X1", "keyword:Some IC"]  # then the block described in words
    cap = cp.need_from_block(
        {"function_id": "mech.knob", "label": "Thumbstick cap", "category": "input",
         "touchpoint": True, "count": 2, "search_terms": ["RKJXV1224005"]}, set()
    )  # fmt: skip
    calls.clear()
    assert cap.mechanical and r.fetch(cap) is None
    assert calls == []  # the part number a cap names is the stick it fits


def test_touched_mechanical_block_without_a_part_is_made_by_the_case() -> None:
    need = cp.need_from_block(
        {"function_id": "mech.knob", "label": "Trigger levers", "category": "mechanical",
         "touchpoint": True, "count": 2}, set()
    )  # fmt: skip
    assert need.mechanical
    hidden = cp.need_from_block(
        {"function_id": "mech.fastener", "label": "Spring", "category": "mechanical",
         "touchpoint": False, "count": 2}, set()
    )  # fmt: skip
    assert not hidden.mechanical


def test_off_board_modules_do_not_share_a_spot() -> None:
    from bara.board.generic import plan_device_board

    def mod(i: str) -> dict[str, Any]:
        box = {"min": [0, 0, 0], "max": [20, 20, 5]}
        rec = {
            "display_name": i,
            "role": "module",
            "kind": "module",
            "mechanical": {"bbox_mm": box},
        }
        return {
            "instance_id": i,
            "part_id": i,
            "slot_id": i,
            "quantity": 1,
            "label": i,
            "record": rec,
        }

    plan = plan_device_board([mod("a"), mod("b"), mod("c")], [], {})
    mods = [i for i in plan.items if i.role == "module"]
    assert len(mods) == 3
    for k, a in enumerate(mods):
        for b in mods[k + 1 :]:
            if a.side == b.side:
                assert a.footprint_poly().intersection(b.footprint_poly()).area < 0.01


def test_body_is_thickened_to_the_real_stack() -> None:
    from types import SimpleNamespace

    from bara.live.runner import LiveRunner as Runner

    seen: list[str] = []
    fake = SimpleNamespace(
        WALL_STACK_MM=3.0, STACK_CLEARANCE_MM=1.0, _warn=lambda *a: seen.append(a[-1])
    )
    board = {
        "boards": [
            {
                "thickness_mm": 1.6,
                "placements": [
                    {"side": "top", "height_mm": 12.0},
                    {"side": "bottom", "height_mm": 20.0, "on_pcb": False},
                ],
            }
        ]
    }
    brief: dict[str, Any] = {}
    Runner._thicken_to_stack(fake, None, None, brief, board, SimpleNamespace(thickness_mm=25.0))  # type: ignore[arg-type]
    assert brief["body_thickness_mm"] == pytest.approx(12 + 1.6 + 20 + 7)
    assert seen
    brief2: dict[str, Any] = {}
    Runner._thicken_to_stack(fake, None, None, brief2, board, SimpleNamespace(thickness_mm=60.0))  # type: ignore[arg-type]
    assert brief2 == {}


def test_locating_pegs_keep_the_other_side_clear() -> None:
    def holder(ref: str) -> Item:
        fp = FootprintInfo(
            "t",
            Path("t.pretty"),
            ref,
            [
                Pad("1", "smd", -8, 0, 1, 1, ["F.Cu"]),
                Pad("", "np_thru_hole", -3, 3, 1, 1, ["*.Cu"]),
                Pad("", "np_thru_hole", 3, -3, 1, 1, ["*.Cu"]),
            ],
            (-10, -5, 10, 5),
            None,
            [],
        )
        return Item(ref, "battery", fp, 0.0, 0.0, 0.0, "top")

    a, b = holder("BT1"), holder("BT2")
    pf = {"silhouette": [(-13, -9), (13, -9), (13, 9), (-13, 9)], "anchors": []}
    place_in_form([a, b], None, pf, [])
    assert pf["fit_report"]["ok"] is False  # a hole through one is a hole through the other


def test_identity_redraw_below_the_fit_floor_keeps_the_fitting_form(monkeypatch: Any) -> None:
    from types import SimpleNamespace

    from bara.live import runner as rn

    def form(w: float, h: float) -> fm.Form:
        sil = [(0.0, 0.0), (w, 0.0), (w, h), (0.0, h)]
        return fm.Form("x", sil, 20.0, 10.0, [], {}, "d")

    fits, smaller = form(170, 110), form(150, 100)

    async def fake_derive(*a: Any, **k: Any) -> Any:
        return smaller, "ok"

    monkeypatch.setattr(rn.form_mod, "derive", fake_derive)
    warned: list[str] = []
    run = SimpleNamespace(
        prompt="a thing", product_form=fits, repair="too round", fit_floor=(170.0, 110.0, 18700.0)
    )
    st = SimpleNamespace(progress=lambda *a: None, emit=lambda *a, **k: None)
    fake = SimpleNamespace(
        _touches=lambda r: [], _warn=lambda *a: warned.append(a[-1]), _stage=None
    )
    result = SimpleNamespace(log=[])
    got = asyncio.run(rn.LiveRunner.form_stage(fake, run, result, st))  # type: ignore[arg-type]
    assert got is fits and any("below the fit floor" in w for w in warned)
    # at or above the floor the redraw is accepted
    bigger = form(172, 112)

    async def fake_big(*a: Any, **k: Any) -> Any:
        return bigger, "ok"

    monkeypatch.setattr(rn.form_mod, "derive", fake_big)
    got2 = asyncio.run(rn.LiveRunner.form_stage(fake, run, result, st))  # type: ignore[arg-type]
    assert got2 is bigger


# ---------------------------------------------------------------- block diagram survival
def test_a_cap_without_a_key_switch_is_dropped_and_counts_reach_the_slots() -> None:
    from bara.live.compose import derive_slots

    spec: dict[str, Any] = {
        "functions": [
            {"function_id": "mech.keycap", "required": True, "count": 1, "source": "implicit"},
            {"function_id": "input.button", "required": True, "count": 1, "source": "explicit"},
        ]
    }
    blocks = {
        "device_class": "gadget",
        "mains_input": False,
        "portable": False,
        "avg_current_ma": 10,
        "shell_g": 5,
        "blocks": [
            block("input.button", "Face buttons", 4),
            block("input.button", "Shoulder buttons", 9),
            block("input.joystick", "Thumbstick", 2),
            block("mech.keycap", "Cap", 1, category="mechanical"),
        ],
    }
    comp = cp.apply(spec, {}, None, blocks)
    assert "mech.keycap" not in {f["function_id"] for f in spec["functions"]}
    assert all(n.function_id != "mech.keycap" for n in comp.needs.values())
    slots = derive_slots(spec, {}, None, comp)
    qty = {s.function_id: sum(i.quantity for i in s.instances) for s in slots}
    assert qty["input.button"] == 13
    assert qty["input.joystick"] == 2
    assert "mech.keycap" not in qty


def test_ask_json_asks_again_when_the_answer_was_cut_off(monkeypatch: pytest.MonkeyPatch) -> None:
    import types

    from bara.live import ask

    budgets: list[int] = []

    class Messages:
        async def create(self, **kw: Any) -> Any:
            budgets.append(kw["max_tokens"])
            cut = len(budgets) == 1
            text = '{"a": "unterminated' if cut else '{"a": "done"}'
            return types.SimpleNamespace(
                stop_reason="max_tokens" if cut else "end_turn",
                content=[types.SimpleNamespace(type="text", text=text)],
            )

    class Client:
        def __init__(self, **_: Any) -> None:
            self.messages = Messages()

        async def close(self) -> None:
            return None

    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setattr("anthropic.AsyncAnthropic", Client)
    schema = {
        "type": "object",
        "required": ["a"],
        "properties": {"a": {"type": "string"}},
        "additionalProperties": False,
    }
    data, note = asyncio.run(ask.ask_json("s", "p", schema, name="t", max_tokens=100))
    assert data == {"a": "done"}, note
    assert budgets == [100, 200]


def test_mating_parts_share_a_spot_but_strangers_still_collide() -> None:
    from bara.geometry.case import Feature
    from bara.geometry.validate import _mates

    def feat(ref: str, role: str, x: float, w: float) -> Feature:
        return Feature(ref, role, x, 0.0, 0.0, "top", 5.0, w, 10.0)

    sw, stab = feat("SW1", "switch", 0.0, 14.0), feat("ST1", "stabilizer", 0.0, 40.0)
    assert _mates(sw, stab)
    assert not _mates(feat("SW2", "switch", 30.0, 14.0), stab)  # another switch under it
    assert not _mates(sw, feat("BT1", "battery", 0.0, 20.0))


def test_every_part_traces_to_a_user_job_and_dropped_blocks_are_logged() -> None:
    from bara.live import blocks as bl
    from bara.live.compose import derive_slots

    spec: dict[str, Any] = {"functions": []}
    blocks = {
        "device_class": "gadget",
        "mains_input": False,
        "portable": True,
        "avg_current_ma": 10,
        "shell_g": 5,
        "use_case": {
            "jobs": ["see the time at night"],
            "environment": "bedside",
            "power": "battery",
            "handling": "sits on a table",
        },
        "blocks": [
            block("input.button", "Set button", 2, why="set the time"),
            block("comms.ble", "Radio", 1, why="sync the time", category="comms"),
        ],
    }
    comp = cp.apply(spec, {}, None, blocks)
    slots = derive_slots(spec, {}, None, comp)
    got = bl.chain(blocks, slots, comp.dropped)
    assert got["use_case"]["jobs"] == ["see the time at night"]
    link = next(k for k in got["links"] if k["function_id"] == "input.button")
    assert link["job"] == "set the time" and link["quantity"] == 2
    assert link["outcome"].startswith("UNRESOLVED")  # nothing chosen yet, never silently ok
    assert [d["label"] for d in got["dropped"]] == ["Radio"]
    assert got["dropped"][0]["why"] == "sync the time"


def test_a_routing_timeout_retries_with_relaxed_rules(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import types

    import bara.board as board
    from bara.board import kicad as K

    seen: list[tuple[float, int, bool]] = []

    def freeroute(dsn: Path, ses: Path, timeout_s: float, passes: int = 100, **_: Any) -> dict:
        seen.append((timeout_s, passes, True))
        if len(seen) == 1:
            raise K.ToolError(f"freerouting timed out after {timeout_s:.0f} s")
        ses.write_text("ses")
        return {"seconds": 1.0, "unrouted": 0, "passes": passes}

    rules_used: list[Any] = []
    monkeypatch.setattr(K, "freeroute", freeroute)
    monkeypatch.setattr(K, "plan_json", lambda plan, pcb, dsn: {"pcb": str(pcb)})

    def build_pcb(p: Path) -> None:
        rules_used.append(json.loads(p.read_text()))
        (p.parent / "main.kicad_pcb").write_text("pcb")

    monkeypatch.setattr(K, "build_pcb", build_pcb)
    monkeypatch.setattr(K, "import_ses", lambda *a, **k: None)
    monkeypatch.setattr(K, "run_drc", lambda *a, **k: {"errors": 0, "unconnected": 0})
    monkeypatch.setattr(K, "export_glb", lambda *a, **k: None)
    monkeypatch.setattr(K, "count_routing", lambda p: {})
    monkeypatch.setattr(board, "_fp_lib_table", lambda d: "")
    pcb_stub = types.SimpleNamespace(pads=[object()] * 600)
    plan = types.SimpleNamespace(name="b", items=[types.SimpleNamespace(fp=pcb_stub)])
    res = board._route_one(plan, tmp_path / "w", tmp_path / "g", (0.0, 0.0), 100.0, 100, print)
    assert len(seen) == 2
    assert seen[0][0] <= 100.0 * 4 * 0.6 and seen[0][0] > 100.0  # scaled by pad count
    assert rules_used[1]["rules"] == K.WIDE_RULES
    assert seen[1][1] == 50  # fewer passes on the retry
    assert res["routing"]["strategy"] == "wide_rules"
    assert res["routing"]["attempts"][0]["timed_out"] is True


def test_a_function_with_no_part_is_composed_from_a_generic_primitive() -> None:
    fp = "kicadgen:kicad:fp:Connector_JST:JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical"

    class Src:
        extra: dict[str, Any] = {}

        def search(self, text: str, kind: str | None = None, limit: int = 20) -> list[dict]:
            if kind == "footprint" and fp.endswith(":" + text):
                return [{"part_id": fp, "fp_ok": True, "functions": []}]
            return []

        def add(self, part: dict[str, Any]) -> None:
            self.extra[part["part_id"]] = part

    r = Resolver(Src())  # type: ignore[arg-type]
    motor = cp.Need(key="rumble", function_id="actuator.motor", label="ERM rumble motor")
    part = r.composed(motor)
    assert part is not None and part["part_id"] == fp
    assert part["composed"].startswith("wire-to-board")
    assert part["functions"][0]["function_id"] == "actuator.motor"
    sensor = cp.Need(key="optic", function_id="sensor.optical", label="optical tracking sensor")
    assert r.composed(sensor) is None  # a sensor is never faked by a connector


def test_an_upright_product_is_stood_up_for_the_hero_view() -> None:
    import numpy as np

    from bara.live import hero

    # a flat slab, main face toward +z, 100 wide (x) and 60 tall (y)
    verts = np.array([[-50, -30, 0], [50, -30, 0], [50, 30, 5], [-50, 30, 5]], dtype=float)
    ((stood, _, _),) = hero.stand_up([(verts, np.zeros((0, 3), dtype=int), (0.5, 0.5, 0.5))])
    assert np.ptp(stood[:, 2]) == 60  # its top edge is now up
    assert np.ptp(stood[:, 1]) == 5  # its thickness runs front to back
    mesh = [(verts, np.zeros((0, 3), dtype=int), (0.0, 0.0, 0.0))]

    def elevation(pose: str) -> float:
        eye, target = hero.hero_camera(mesh, pose)
        d = np.subtract(eye, target)
        return float(d[2] / np.linalg.norm(d))

    assert elevation("upright") < elevation("face_up")  # nearer eye height for a standing face


def test_a_cable_connector_sits_on_the_rim_with_its_mouth_out() -> None:
    """A receptacle with no anchor still goes to the edge, not the middle of the board, turned so
    the body (which runs past the pads toward the mouth) faces out."""
    mcu = _item("U1", "mcu", "controller", 12.0)
    usb = Item(
        "J1",
        "usb_in",
        FootprintInfo(
            "t",
            Path("t.pretty"),
            "J1",
            [Pad(str(i), "smd", -3 + i, -3.0, 0.6, 1.2, ["F.Cu"]) for i in range(6)],
            (-4.5, -3.8, 4.5, 4.0),  # body runs to +y: the mouth is at +y
            None,
            [],
        ),
        0,
        0,
        0,
        "top",
        meta={"slot_id": "power"},
    )
    pf = {"silhouette": [[-40, -25], [40, -25], [40, 25], [-40, 25]], "anchors": []}
    place_in_form([mcu, usb], mcu, pf, [])
    region = form_region(pf, 1.0)
    body = usb.world(usb.local_poly())
    assert region.exterior.distance(body) < 1.0  # against the edge
    pads = usb.world(usb.local_poly("pads")).centroid
    c = body.centroid
    nearest = region.exterior.interpolate(region.exterior.project(c))
    out = (nearest.x - pads.x, nearest.y - pads.y)
    assert (c.x - pads.x) * out[0] + (c.y - pads.y) * out[1] > 0  # mouth toward that edge


def test_an_off_board_cell_moves_clear_of_the_parts_on_its_side() -> None:
    from bara.board.generic import _clear_of

    sensor = _item("U1", "sensor", "s", w=5.0)
    sensor.side = "bottom"
    cell = Item("BT1", "battery", None, 0.0, 0.0, 0.0, "bottom", on_pcb=False, size_mm=(12, 30))
    region = Polygon([(-30, -60), (30, -60), (30, 60), (-30, 60)])
    _clear_of(cell, {"top": [], "bottom": []}, [sensor], region, False)
    # either side works: beside the sensor, or flipped above the board where nothing sits
    clear = cell.footprint_poly().intersection(sensor.footprint_poly()).area < 0.01
    assert clear or cell.side == "top"


def test_two_catch_all_blocks_on_one_part_are_one_part() -> None:
    from bara.live import compose as cmp

    comp = object.__new__(cmp.Composer)
    sensor = cmp.Slot("sensor", "Optical sensor", "other", "critical", 1, [])
    sensor.chosen = {"part_id": "lcsc:pmw3360"}
    lens = cmp.Slot("lens", "Lens matched to the sensor", "other", "critical", 1, [])
    left = cmp.Slot("left", "Left click", "input.button", "critical", 1, [])
    left.chosen = {"part_id": "lcsc:d2fc"}
    middle = cmp.Slot("middle", "Middle click", "input.button", "critical", 1, [])
    comp.slots = [sensor, lens, left, middle]
    assert comp.twin_slot(lens, {"part_id": "lcsc:pmw3360"}) is sensor
    # the same switch under two clicks is two switches
    assert comp.twin_slot(middle, {"part_id": "lcsc:d2fc"}) is None


def test_a_required_block_nothing_meets_takes_the_closest_real_part(monkeypatch: Any) -> None:
    from bara.live import compose as cmp

    async def none_meet(system: str, user: str, schema: Any, **kw: Any) -> Any:
        return {"meets": []}, ""

    monkeypatch.setattr(cmp, "ask_json", none_meet)
    comp = object.__new__(cmp.Composer)
    comp.resolver = type("R", (), {"rejected": set(), "notes": {}})()  # type: ignore[assignment]
    comp.extra, comp.near_miss, comp.warning_n = {}, {}, 0
    need = cp.Need("sensor", "sense.distance", "Mouse sensor", requirement="26000 DPI")
    slot = cmp.Slot("sensor", "Mouse sensor", "sense.distance", "critical", 1, [], need=need)
    pmw = {"part_id": "lcsc:pmw3360", "display_name": "PMW3360DM-T2QU"}
    assert asyncio.run(comp.vet(slot, [pmw])) == []
    assert "lcsc:pmw3360" in comp.resolver.rejected
    seen: list[Any] = []
    comp.take_closest(slot, lambda *a, **k: seen.append(a))
    assert comp.extra["sensor"] == [pmw] and "lcsc:pmw3360" not in comp.resolver.rejected
    assert "falls short" in seen[0][1]["warning"]["message"]


def test_an_off_board_part_anchored_to_the_front_stays_on_the_front() -> None:
    from shapely.geometry import box

    from bara.board.generic import _clear_of
    from bara.board.layout import Item

    def cell(ref: str, side: str) -> Item:
        return Item(ref, "module", None, 0, 0, 0, side, on_pcb=False, size_mm=(10.0, 10.0))

    stick, under = cell("M1", "top"), cell("U1", "top")
    _clear_of(stick, {"top": [], "bottom": []}, [under], box(-60, -60, 60, 60), True)
    assert (
        stick.side == "top"
        and stick.footprint_poly().intersection(under.footprint_poly()).area < 0.01
    )
    loose = cell("M2", "top")
    _clear_of(loose, {"top": [], "bottom": []}, [under], box(-60, -60, 60, 60), False)
    assert loose.side == "bottom"  # an unanchored part may still use the back
