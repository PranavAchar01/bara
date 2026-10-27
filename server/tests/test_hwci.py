"""Hardware gate: provenance, reports and the MCP server, on the boards under hardware/boards."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from bara.hwci import provenance, report
from bara.hwci.__main__ import boards, run_check
from bara.hwci.mcp_server import Server

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "hardware" / "boards"
POLICY = provenance.load_policy(REPO / "hardware" / "policy.json")
needs_kicad = pytest.mark.skipif(not shutil.which("kicad-cli"), reason="kicad-cli not installed")


def test_every_board_has_pcb_and_schematic() -> None:
    found = boards(ROOT)
    assert [b.name for b in found] == ["carrier-board", "wifi-handheld", "wifi-macropad"]
    assert all((b / "main.kicad_sch").is_file() for b in found)


def test_footprints_resolve_to_policy_sources() -> None:
    res = provenance.check(ROOT / "wifi-handheld", POLICY)
    assert len(res["parts"]) == 27
    assert res["blocked"] == 0
    by_ref = {p["ref"]: p for p in res["parts"]}
    assert by_ref["DS1"]["source"] == "kicad"
    assert by_ref["DS1"]["licence"].startswith("CC-BY-SA-4.0")
    assert {p["source"] for p in res["parts"] if p["verdict"] == "review"} == {"lcsc"}


def test_unknown_library_is_blocked(tmp_path: Path) -> None:
    b = tmp_path / "b"
    shutil.copytree(ROOT / "wifi-handheld", b)
    table = (b / "fp-lib-table").read_text().replace("catalog/fetched/src/", "somewhere/")
    (b / "fp-lib-table").write_text(table)
    res = provenance.check(b, POLICY)
    assert res["blocked"] == 5
    assert all(p["licence"] == "unknown" for p in res["parts"] if p["verdict"] == "blocked")


def test_cyclonedx_hbom_shape() -> None:
    parts = provenance.check(ROOT / "wifi-macropad", POLICY)["parts"]
    bom = provenance.cyclonedx("wifi-macropad", parts)
    assert bom["bomFormat"] == "CycloneDX" and bom["specVersion"] == "1.5"
    assert len(bom["components"]) == len(parts)
    assert all(c["type"] == "device" for c in bom["components"])


def _fake(name: str, drc_err: int = 0, erc_err: int = 0) -> dict:
    v = {"severity": "error", "type": "clearance", "description": "Clearance violation",
         "items": ["a", "b"], "at_mm": [1.0, 2.0], "environment": False}  # fmt: skip
    return {
        "name": name,
        "path": f"hardware/boards/{name}",
        "drc": {
            "errors": drc_err,
            "warnings": 0,
            "unconnected": 0,
            "environment": 0,
            "violations": [v] * drc_err,
        },  # fmt: skip
        "erc": {"errors": erc_err, "warnings": 0, "environment": 0, "violations": []},
        "provenance": {"parts": [], "ok": 1, "review": 0, "blocked": 0},
    }


def test_gate_and_reports() -> None:
    good, bad = _fake("good"), _fake("bad", drc_err=2)
    for b in (good, bad):
        b["gate"] = report.gate(b, POLICY)
    assert good["gate"] == [] and bad["gate"] == ["2 DRC errors"]
    run = {"kicad": "10.0.7", "boards": [good, bad], "passed": False}
    md = report.markdown(run)
    assert "FAIL" in md and "(1.0, 2.0) mm" in md
    xml = report.junit(run)
    assert 'tests="6" failures="1"' in xml
    cq = report.code_quality(run)
    assert len(cq) == 2 and cq[0]["severity"] == "critical"
    assert cq[0]["location"]["path"] == "hardware/boards/bad/main.kicad_pcb"


@needs_kicad
def test_real_boards_through_kicad() -> None:
    run = run_check(ROOT, POLICY)
    by = {b["name"]: b for b in run["boards"]}
    assert by["wifi-handheld"]["gate"] == []
    assert by["wifi-macropad"]["erc"]["errors"] == 2
    assert by["carrier-board"]["drc"]["errors"] == 8
    assert run["passed"] is False


def _rpc(srv: Server, mid: int, method: str, **params: object) -> dict:
    return srv.handle({"jsonrpc": "2.0", "id": mid, "method": method, "params": params})


@needs_kicad
def test_mcp_server_round_trip() -> None:
    srv = Server(ROOT, REPO / "hardware" / "policy.json")
    assert _rpc(srv, 1, "initialize")["result"]["serverInfo"]["name"] == "tangible-hardware"
    assert srv.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    names = [t["name"] for t in _rpc(srv, 2, "tools/list")["result"]["tools"]]
    assert "check_board" in names
    out = _rpc(srv, 3, "tools/call", name="check_board", arguments={"board": "wifi-macropad"})
    data = json.loads(out["result"]["content"][0]["text"])
    assert data["gate"] == ["2 ERC errors"]
    bad = _rpc(srv, 4, "tools/call", name="check_board", arguments={"board": "../etc"})
    assert bad["result"]["isError"] is True
