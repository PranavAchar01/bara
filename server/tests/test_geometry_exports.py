"""Exports: case STL/3MF, BOM and wiring CSV, KiCad zip, board STEP, honest E_ASSET_MISSING."""

from __future__ import annotations

import csv
import io
import shutil
import zipfile
from pathlib import Path
from typing import Any

import pytest
from conftest import Ws, make_client

from bara.geometry import ExportError, enclose_report, export
from bara.geometry.exports import parse_kicad_pcb
from bara.geometry.meshio import read_3mf, read_stl
from bara.geometry.samples import macropad_board

KICAD_PCB = """(kicad_pcb (version 20240108) (generator "bara_test")
  (general (thickness 1.6))
  (paper "A4")
  (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (44 "Edge.Cuts" user))
  (net 0 "")
  (net 1 "GND")
  (net 2 "VCC")
  (footprint "Resistor_SMD:R_0603_1608Metric" (layer "F.Cu") (at 10 10)
    (property "Reference" "R1" (at 0 -1.5 0) (layer "F.SilkS"))
    (property "Value" "10k" (at 0 1.5 0) (layer "F.Fab"))
    (pad "1" smd roundrect (at -0.8 0) (size 0.8 0.95) (layers "F.Cu")
      (roundrect_rratio 0.25) (net 1 "GND"))
    (pad "2" smd roundrect (at 0.8 0) (size 0.8 0.95) (layers "F.Cu")
      (roundrect_rratio 0.25) (net 2 "VCC"))
  )
  (gr_rect (start 0 0) (end 20 20) (stroke (width 0.1) (type default)) (fill none)
    (layer "Edge.Cuts"))
)
"""


@pytest.fixture
def build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setenv("BARA_DATA_DIR", str(tmp_path))
    board, brief = macropad_board()
    rep = enclose_report(board, [], brief)
    pcb_dir = tmp_path / "assets" / "cache" / "boards"
    pcb_dir.mkdir(parents=True)
    (pcb_dir / "test.kicad_pcb").write_text(KICAD_PCB)
    return {
        "build_id": "b_geomtest01",
        "revision": 1,
        "parts": [],
        "enclosures": [rep.enclosure],
        "boards": [
            {
                "board_id": "pcb_macropad",
                "assets": [{"kind": "kicad_pcb", "url": "/assets/cache/boards/test.kicad_pcb"}],
            }
        ],
    }


def test_case_stl_and_3mf(build):
    data, media = export(build, "stl")
    assert media == "model/stl"
    tris = read_stl(data)
    assert len(tris) > 100
    assert tris[:, :, 2].min() == pytest.approx(0.0, abs=1e-3)
    data, media = export(build, "3mf")
    assert media == "model/3mf"
    objs = read_3mf(data)
    assert len(objs) == 2


def test_bom_and_wiring_csv(build):
    data, media = export(build, "bom_csv")
    assert media == "text/csv"
    rows = list(csv.DictReader(io.StringIO(data.decode())))
    assert data.decode().startswith("part_id,")
    libs = {r["lib_id"] for r in rows}
    assert "Resistor_SMD:R_0603_1608Metric" in libs
    r1 = next(r for r in rows if r["lib_id"] == "Resistor_SMD:R_0603_1608Metric")
    if Path("/Applications/KiCad/KiCad.app").exists():
        assert r1["source_url"].startswith("https://")
        assert r1["licence"]
    assert any("case" in r["name"].lower() or r["part_id"].startswith("e_") for r in rows)
    data, _ = export(build, "wiring_csv")
    wires = list(csv.DictReader(io.StringIO(data.decode())))
    nets = {w["signal"] for w in wires}
    assert {"GND", "VCC"} <= nets


def test_parse_kicad_pcb():
    (fp,) = parse_kicad_pcb(KICAD_PCB)
    assert fp["lib_id"] == "Resistor_SMD:R_0603_1608Metric"
    assert fp["ref"] == "R1"
    assert fp["value"] == "10k"


def test_kicad_zip(build):
    data, media = export(build, "kicad")
    assert media == "application/zip"
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = set(zf.namelist())
        assert {"test/test.kicad_pcb", "test/test.kicad_pro", "bom.csv", "wiring.csv"} <= names
        assert zf.read("test/test.kicad_pcb").decode().startswith("(kicad_pcb")


@pytest.mark.skipif(
    not (shutil.which("kicad-cli") or Path("/opt/homebrew/bin/kicad-cli").exists()),
    reason="kicad-cli not installed",
)
def test_board_step(build):
    data, media = export(build, "step")
    assert media == "model/step"
    assert data.startswith(b"ISO-10303-21;")


def test_missing_assets_are_honest(build):
    gone = {**build, "enclosures": [], "boards": []}
    for fmt in ("stl", "3mf", "kicad", "step"):
        with pytest.raises(ExportError) as err:
            export(gone, fmt)
        assert err.value.code == "E_ASSET_MISSING"
    lost = {
        **build,
        "boards": [{"assets": [{"kind": "kicad_pcb", "url": "/assets/../etc/passwd"}]}],
    }
    with pytest.raises(ExportError) as err:
        export(lost, "kicad")
    assert err.value.code == "E_ASSET_MISSING"


def test_rest_mock_build_reports_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("BARA_DATA_DIR", str(tmp_path))

    with make_client(monkeypatch) as client, client.websocket_connect("/v1/ws") as sock:
        build_id, _ = Ws(sock).build("a wireless split keyboard with an oled")
        for fmt in ("stl", "3mf", "step", "kicad"):
            r = client.get(f"/v1/builds/{build_id}/export?format={fmt}")
            assert r.status_code == 404, (fmt, r.status_code, r.text)
            assert r.json()["error"]["code"] == "E_ASSET_MISSING"
        r = client.get(f"/v1/builds/{build_id}/export?format=bom_csv")
        assert r.status_code == 200 and r.text.startswith("part_id,")
        assert "lib_id" in r.text.splitlines()[0]
        r = client.get(f"/v1/builds/{build_id}/export?format=zip")
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            assert "wiring.csv" in zf.namelist()


def test_asset_path_ignores_version_suffix(build):
    from bara.geometry.exports import asset_path

    plain = asset_path("/assets/cache/boards/test.kicad_pcb")
    assert plain is not None
    assert asset_path("/assets/cache/boards/test.kicad_pcb?v=0123456789abcdef") == plain
    assert asset_path("/assets/cache/boards/../../../etc/passwd?v=1") is None
