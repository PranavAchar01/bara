"""KiCad's own DRC, ERC, schematic parity and board statistics, read into the build's checks."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from bara.board import kicad_checks as KC

FIX = Path(__file__).parent / "fixtures" / "kicad_reports"


def _load(name: str) -> dict:
    return json.loads((FIX / name).read_text())


def test_drc_report_counts_rules_and_refs() -> None:
    out = KC.parse_drc(_load("drc.json"))
    drc = out["drc"]
    # the 0.8 micron router-grid shortfall is dropped; pads of one footprint (U2) are a warning
    assert drc["counts"] == {"error": 2, "warning": 2, "info": 0}
    assert drc["unconnected"] == 1
    assert drc["passed"] is False
    assert drc["by_rule"] == {
        "error:clearance": 1,
        "error:unconnected_items": 1,
        "warning:clearance": 1,
        "warning:lib_footprint_issues": 1,
    }
    viol = out["violations"]
    clearance = next(v for v in viol if v["rule"] == "clearance" and v["severity"] == "error")
    assert clearance["refs"] == ["U1"]
    assert clearance["message"].startswith("Clearance violation")
    assert clearance["pos_mm"] == [410.5, 402.0]
    own = next(v for v in viol if v["rule"] == "clearance" and v["severity"] == "warning")
    assert own["refs"] == ["U2"] and "one library footprint" in own["note"]
    assert next(v for v in viol if v["rule"] == "unconnected_items")["refs"] == ["U1", "J1"]
    assert out["parity"]["counts"]["warning"] == 1 and out["parity"]["passed"] is True
    assert next(v for v in viol if v["tool"] == "parity")["refs"] == ["DS1"]


def test_drc_without_parity_has_no_parity_section() -> None:
    data = {k: v for k, v in _load("drc.json").items() if k != "schematic_parity"}
    assert "parity" not in KC.parse_drc(data)


def test_erc_report_reads_every_sheet() -> None:
    out = KC.parse_erc(_load("erc.json"))
    assert out["erc"]["counts"] == {"error": 2, "warning": 1, "info": 0}
    refs = [v["refs"] for v in out["violations"]]
    assert refs == [["#PWR001"], ["U1", "U2"], ["R1"]]


def test_stats_report_becomes_numbers() -> None:
    s = KC.parse_stats(_load("stats.json"))
    assert (s["width_mm"], s["height_mm"], s["area_mm2"]) == (109.0, 153.0, 16610.503)
    assert s["components"] == 20 and s["pads"] == 184 and s["vias"] == 53
    assert s["copper_fill_pct"] == pytest.approx(2.3, abs=0.05)
    assert s["min_track_width_mm"] == 0.15


def test_checks_map_refs_to_parts_and_fail_on_errors() -> None:
    report = {
        "status": "ok",
        **{k: v for k, v in KC.parse_drc(_load("drc.json")).items() if k != "violations"},
        "erc": KC.parse_erc(_load("erc.json"))["erc"],
        "violations": KC.parse_drc(_load("drc.json"))["violations"]
        + KC.parse_erc(_load("erc.json"))["violations"],
    }
    fps = [{"ref": "U1", "instance_id": "i_mcu"}, {"ref": "J1", "instance_id": None}]
    mapped = KC.attach_instances(report, fps)
    assert next(v for v in mapped["violations"] if v["refs"] == ["U1"])["instance_ids"] == ["i_mcu"]
    unmapped = [{"ref": "U1", "instance_id": None, "role": "mcu"}]
    by_slot = KC.attach_instances(report, unmapped, {"controller": "u_mcu"}, {"mcu": "controller"})
    assert next(v for v in by_slot["violations"] if v["refs"] == ["U1"])["instance_ids"] == [
        "u_mcu"
    ]
    checks = {c["check_key"]: c for c in KC.check_results("b1", mapped)}
    assert set(checks) == {"board.kicad.drc:b1", "board.kicad.erc:b1", "board.kicad.parity:b1"}
    drc = checks["board.kicad.drc:b1"]
    assert drc["status"] == "fail" and drc["measured"] == 2
    assert {"instance_id": "i_mcu"} in drc["subjects"]
    assert drc["message"].startswith("KiCad DRC: 2 errors, 2 warnings (clearance x1")
    assert checks["board.kicad.parity:b1"]["status"] == "pass"


def test_missing_kicad_degrades_instead_of_failing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(KC, "find_kicad_cli", lambda: None)
    out = KC.run_checks(tmp_path / "main.kicad_pcb", None)
    assert out == {"status": "not_installed", "message": "KiCad not installed"}
    [check] = KC.check_results("b1", out)
    assert check["status"] == "unknown" and check["message"] == "KiCad not installed"


def _game_boy_board() -> Path | None:
    """The newest finished Game Boy build's routed board, if this machine has one."""
    from bara.config import load_settings

    # this checkout's data, else the main checkout's (a worktree has no library of its own)
    for data in (load_settings().data_dir, Path.home() / "helloworld/bara/server/data"):
        if (data / "library").is_dir():
            break
    else:
        return None
    rows = []
    for meta in (data / "library").glob("b_*.meta.json"):
        try:
            row = json.loads(meta.read_text())
        except ValueError:
            continue
        prompt = str(row.get("prompt") or "").lower().replace(" ", "")
        if "gameboy" in prompt and row.get("status") == "done":
            rows.append((str(row.get("created_at") or ""), row["build_id"]))
    for _, bid in sorted(rows, reverse=True):
        for line in (data / "library" / f"{bid}.jsonl").read_text().splitlines():
            if '"board.updated"' not in line or '"cache_key"' not in line:
                continue
            key = json.loads(line)["payload"]["board"]["routing"]["cache_key"]
            work = data / "cache" / "boards" / key
            if (work / "main.kicad_pcb").exists() and (work / "main.kicad_sch").exists():
                return work
    return None


def test_game_boy_board_end_to_end(tmp_path: Path) -> None:
    if KC.find_kicad_cli() is None:
        pytest.skip("kicad-cli not installed")
    work = _game_boy_board()
    if work is None:
        pytest.skip("no Game Boy board on disk")
    # read-only: KiCad writes project files beside the board, so it runs on a copy
    for name in ("main.kicad_pcb", "main.kicad_sch", "main.kicad_pro"):
        if (work / name).exists():
            shutil.copyfile(work / name, tmp_path / name)
    out = KC.run_checks(tmp_path / "main.kicad_pcb", tmp_path / "main.kicad_sch")
    assert out["status"] == "ok", out.get("message")
    assert {"drc", "erc", "parity", "stats"} <= set(out)
    stats = out["stats"]
    assert stats["width_mm"] > 0 and stats["height_mm"] > 0 and stats["components"] > 0
    assert stats["copper_layers"] in (2, 4) and stats["track_total_mm"] > 0
    assert out["timings"]["drc_s"] > 0 and out["timings"]["erc_s"] > 0
    assert all(v["severity"] in KC.SEVERITIES for v in out["violations"])
    # the same input bytes reuse the stored report
    assert KC.run_checks(tmp_path / "main.kicad_pcb", tmp_path / "main.kicad_sch")["cached"]
