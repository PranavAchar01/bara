"""KiCad's evaluation of a routed board reaches the user as checks for any device."""

from __future__ import annotations

from pathlib import Path

from bara.board.evaluate import evaluate
from bara.board.kicad import count_routing

NETS = [
    {"name": "GND", "members": [{"instance_id": "a"}, {"instance_id": "b"}]},
    {"name": "SDA", "members": [{"instance_id": "a"}, {"instance_id": "c"}]},
    {"name": "NC1", "members": [{"instance_id": "a"}]},
]


def test_every_drc_type_and_a_dangling_net_become_checks() -> None:
    drc = {
        "errors": 1,
        "warnings": 2,
        "unconnected": 1,
        "unconnected_nets": ["SDA"],
        "by_type": {"error:clearance": 1, "warning:silk_edge_clearance": 2},
        "titles": {"error:clearance": "Clearance violation"},
    }
    routing = {"segments": 10, "vias": 2, "track_mm": {"F.Cu": 40.0, "B.Cu": 2.5}}
    out = evaluate("b1", NETS, drc, routing, {"route_s": 3.0})
    by_key = {c["check_key"]: c for c in out["checks"]}
    assert by_key["board.drc.clearance:b1"]["status"] == "fail"
    assert "Clearance violation" in by_key["board.drc.clearance:b1"]["message"]
    assert by_key["board.drc.silk_edge_clearance:b1"]["status"] == "unknown"
    assert by_key["board.nets.connected:b1"]["status"] == "fail"
    assert "NC1" in by_key["board.nets.connected:b1"]["message"]
    bench = by_key["board.bench:b1"]
    assert bench["measured"] == 50.0 and bench["status"] == "fail"
    assert out["summary"]["track_total_mm"] == 42.5


def test_a_clean_board_passes_and_old_cached_results_still_evaluate() -> None:
    out = evaluate("b2", NETS[:2], {"errors": 0, "unconnected": 0}, {}, {})
    assert all(c["status"] == "pass" for c in out["checks"])
    assert out["summary"]["routed_pct"] == 100.0


def test_track_length_is_summed_per_copper_layer(tmp_path: Path) -> None:
    pcb = tmp_path / "b.kicad_pcb"
    pcb.write_text(
        "(kicad_pcb\n\t(segment\n\t\t(start 0 0)\n\t\t(end 3 4)\n\t\t(width 0.2)\n"
        '\t\t(layer "F.Cu")\n\t\t(net "A")\n\t)\n\t(via\n\t\t(at 1 1)\n\t)\n)\n'
    )
    got = count_routing(pcb)
    assert got["segments"] == 1 and got["vias"] == 1
    assert got["track_mm"] == {"F.Cu": 5.0}
