"""Routing makes progress: open connections on two layers go to four, and a cached
incomplete board is never handed back to a repair round unchanged."""

from __future__ import annotations

import json
import types
from pathlib import Path
from typing import Any

import pytest

import bara.board as board
from bara.board import kicad as K


def _glb(pcb: Path, glb: Path, origin: Any) -> None:
    glb.parent.mkdir(parents=True, exist_ok=True)
    glb.write_bytes(b"glb")


def _stub(monkeypatch: pytest.MonkeyPatch, open_on_two: int) -> list[dict[str, Any]]:
    built: list[dict[str, Any]] = []

    def build_pcb(p: Path) -> None:
        built.append(json.loads(p.read_text()))
        (p.parent / "main.kicad_pcb").write_text("pcb")

    def freeroute(dsn: Path, ses: Path, *a: Any, **k: Any) -> dict:
        ses.write_text("ses")
        return {"seconds": 0.1, "passes": 5}

    def drc(_pcb: Path) -> dict[str, Any]:
        layers = built[-1].get("copper_layers", 2)
        n = open_on_two if layers == 2 else 0
        return {"errors": 0, "unconnected": n, "unconnected_nets": ["ROW0"] if n else []}

    monkeypatch.setattr(
        K,
        "plan_json",
        lambda plan, pcb, dsn: {
            "rules": K.RULES,
            "footprints": [],
            "rule_areas": [{"name": "edge_band_0", "outer": [], "layers": ["F.Cu", "B.Cu"]}],
        },
    )
    monkeypatch.setattr(K, "build_pcb", build_pcb)
    monkeypatch.setattr(K, "freeroute", freeroute)
    monkeypatch.setattr(K, "import_ses", lambda *a, **k: None)
    monkeypatch.setattr(K, "run_drc", drc)
    monkeypatch.setattr(K, "export_glb", _glb)
    monkeypatch.setattr(K, "count_routing", lambda p: {})
    monkeypatch.setattr(board, "_fp_lib_table", lambda d: "")
    monkeypatch.setattr(board.glbopt, "is_valid", lambda p: True)
    return built


PLAN = types.SimpleNamespace(name="b", items=[])


def test_open_connections_on_two_layers_are_routed_on_four(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    built = _stub(monkeypatch, open_on_two=3)
    res = board._route_one(PLAN, tmp_path / "w", tmp_path / "g", (0, 0), 300.0, 50, print)
    assert res["drc"]["unconnected"] == 0
    assert res["copper_layers"] == 4
    four = [b for b in built if b.get("copper_layers") == 4]
    assert len(built) == len(K.ROUTE_STRATEGIES) + 1 and len(four) == 1
    # the edge keep-out covers the inner layers too
    assert four[0]["rule_areas"][0]["layers"] == K.COPPER[4]


def test_a_two_layer_board_that_routes_stays_two_layers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    built = _stub(monkeypatch, open_on_two=0)
    res = board._route_one(PLAN, tmp_path / "w", tmp_path / "g", (0, 0), 300.0, 50, print)
    assert res["copper_layers"] == 2 and len(built) == 1


def test_a_cached_incomplete_board_from_a_shorter_ladder_is_routed_again(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    built = _stub(monkeypatch, open_on_two=3)
    res = board._route_one(PLAN, tmp_path / "w", tmp_path / "g", (0, 0), 300.0, 50, print)
    # an older run that never tried four layers left this result in the cache
    path = Path(res["kicad_pcb"]).parent / "result.json"
    stale = {**res, "drc": {**res["drc"], "unconnected": 3}, "ladder": None}
    path.write_text(json.dumps(stale))
    n = len(built)
    again = board._route_one(PLAN, tmp_path / "w", tmp_path / "g", (0, 0), 300.0, 50, print)
    assert again["cache_hit"] is False and len(built) > n
    assert again["drc"]["unconnected"] == 0
    # the fresh complete result is reused as is
    third = board._route_one(PLAN, tmp_path / "w", tmp_path / "g", (0, 0), 300.0, 50, print)
    assert third["cache_hit"] is True


def test_a_repair_round_never_gets_the_same_cache_entry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stub(monkeypatch, open_on_two=3)
    first = board._route_one(PLAN, tmp_path / "w", tmp_path / "g", (0, 0), 300.0, 50, print)
    repair = board._route_one(
        PLAN, tmp_path / "w", tmp_path / "g", (0, 0), 300.0, 50, print, effort=1
    )
    assert repair["key"] != first["key"] and repair["cache_hit"] is False
    names = [a["strategy"] for a in repair["routing"]["attempts"]]
    assert any(n.startswith("ripup_25") for n in names) or repair["drc"]["unconnected"] == 0
