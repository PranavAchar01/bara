"""Case generation: watertight pieces, parts inside with clearance, cutouts on the right faces,
schema-valid Enclosure and CheckResults, and timing."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import manifold3d as mf
import numpy as np
import pytest
from conftest import SCHEMAS

from bara.geometry import HAND_SET, EncloseReport, enclose, enclose_report, validate
from bara.geometry.meshio import read_3mf, read_glb, read_stl
from bara.geometry.samples import macropad_board, split_right_board

SAMPLES = {"macropad": macropad_board, "split_right": split_right_board}


@pytest.fixture(scope="module")
def reports(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, EncloseReport]]:
    data = tmp_path_factory.mktemp("geodata")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("BARA_DATA_DIR", str(data))
        out = {}
        for name, fn in SAMPLES.items():
            board, brief = fn()
            out[name] = enclose_report(board, [], brief)
        _DATA.append(data)
        yield out


_DATA: list[Path] = []


def _asset_bytes(url: str) -> bytes:
    assert url.startswith("/assets/")
    return (_DATA[-1] / "assets" / url[len("/assets/") :]).read_bytes()


def _by_rule(checks: list[dict[str, Any]], rule: str) -> list[dict[str, Any]]:
    return [c for c in checks if c["rule_id"] == rule]


@pytest.mark.parametrize("name", list(SAMPLES))
def test_all_checks_pass_on_samples(reports, name):
    checks = reports[name].checks
    assert checks
    failed = [c for c in checks if c["status"] != "pass"]
    assert not failed, [c["message"] for c in failed]


@pytest.mark.parametrize("name", list(SAMPLES))
def test_schema_valid(reports, name):
    rep = reports[name]
    errs = SCHEMAS.errors("build.schema.json#/$defs/Enclosure", rep.enclosure)
    assert not errs, errs
    for check in rep.checks:
        errs = SCHEMAS.errors("check.schema.json", check)
        assert not errs, (check["check_key"], errs)
        assert check["stage"] == "enclose"
    for asset in rep.enclosure["assets"]:
        assert asset["url"].startswith("/assets/cache/enclosures/")
        assert not SCHEMAS.errors("asset.schema.json", asset), asset


@pytest.mark.parametrize("name", list(SAMPLES))
def test_watertight(reports, name):
    rep = reports[name]
    for piece in (rep.world_tray, rep.world_bezel, rep.tray, rep.bezel):
        assert piece is not None
        assert piece.status() == mf.Error.NoError
        assert piece.volume() > 1000.0
        mesh = piece.to_mesh()
        tris = np.asarray(mesh.tri_verts)
        edges = np.sort(np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]]), 1)
        _, counts = np.unique(edges, axis=0, return_counts=True)
        assert np.all(counts == 2), "open or non-manifold edges"
    rule = _by_rule(rep.checks, "mech.case.watertight")
    assert rule and all(c["status"] == "pass" for c in rule)


@pytest.mark.parametrize("name", list(SAMPLES))
def test_parts_inside_with_clearance(reports, name):
    rep = reports[name]
    fits = _by_rule(rep.checks, "mech.fit.enclosure")
    assert fits and all(c["status"] == "pass" for c in fits)
    # The board slab sits inside the tray cavity: no volume shared with the case.
    case = rep.tray + rep.bezel
    t = rep.thickness
    loops = [rep.outline.tolist()] + [np.asarray(h).tolist() for h in rep.holes]
    outline = mf.CrossSection(loops, mf.FillRule.EvenOdd)
    slab = mf.Manifold.extrude(outline, t)
    assert (slab ^ case).volume() < 1.0
    # Tray inner wall is at least the tray clearance away from the outline everywhere.
    lo, hi = np.asarray(case.bounding_box()[:3]), np.asarray(case.bounding_box()[3:])
    o_lo, o_hi = rep.outline.min(0), rep.outline.max(0)
    margin = HAND_SET["wall_mm"] + HAND_SET["tray_clearance_mm"] - 0.05
    assert np.all(o_lo - lo[:2] >= margin) and np.all(hi[:2] - o_hi >= margin)


def test_cutout_faces(reports):
    mac = {
        c["cutout_id"].split("_")[1]: c["face"] for c in reports["macropad"].enclosure["cutouts"]
    }
    split = {
        c["cutout_id"].split("_")[1]: c["face"] for c in reports["split_right"].enclosure["cutouts"]
    }
    # Macropad: USB sits at the top edge (+Y), encoder and screen are on the top face.
    assert mac.get("usb") == "pos_y"
    assert mac.get("enc") == "pos_z"
    assert mac.get("screen") == "pos_z"
    # Split right: MCU at the right end, so the USB faces +X; ball on top, sensor through the floor.
    assert split.get("usb") == "pos_x"
    assert split.get("ball") == "pos_z"
    assert split.get("sensor") == "neg_z"


def test_trackball_clearance(reports):
    rep = reports["split_right"]
    (ball,) = _by_rule(rep.checks, "mech.fit.trackball")
    assert ball["status"] == "pass"
    assert 0.1 <= ball["measured"] <= 1.5
    (lens,) = _by_rule(rep.checks, "mech.fit.sensor_window")
    assert lens["status"] == "pass"
    assert abs(lens["measured"] - HAND_SET["lens_gap_mm"]) < 0.2


def test_tenting_and_colour(reports):
    rep = reports["split_right"]
    pos, rot = rep.board_pose()
    assert rot[1] == pytest.approx(HAND_SET["tent_deg"], abs=0.01)
    assert rep.enclosure["color"]["hex"].upper() == "#8FA67A"
    lo = rep.world_tray.bounding_box()
    assert lo[2] == pytest.approx(0.0, abs=1e-3)
    mac = reports["macropad"]
    assert mac.board_pose()[1] == [0.0, 0.0, 0.0]
    assert mac.enclosure["color"]["hex"].upper() == "#F2F2EE"


def test_blocked_port_is_caught(reports):
    rep = reports["macropad"]
    (usb,) = rep.openings["usb"]
    f = next(x for x in rep.features if x.ref == usb["ref"])
    plug = mf.Manifold.cube((30.0, 30.0, 12.0), center=True).translate((f.x, f.y + 15.0, usb["z"]))
    blocked = EncloseReport(**{**rep.__dict__, "tray": rep.tray + plug})
    checks = validate(blocked)
    (panel,) = [c for c in _by_rule(checks, "mech.access.panel") if "usb" in c["check_key"]]
    assert panel["status"] == "fail"
    assert panel["fix_hint"]
    assert not SCHEMAS.errors("check.schema.json", panel)


def test_written_meshes_parse(reports):
    rep = reports["macropad"]
    eid = rep.enclosure["enclosure_id"]
    glb = next(a for a in rep.enclosure["assets"] if a["kind"] == "glb")
    data = _asset_bytes(glb["url"])
    gltf = read_glb(data)
    names = {n["name"] for n in gltf["nodes"]}
    assert {f"{eid}_tray", f"{eid}_bezel"} <= names
    stl = read_stl(
        _asset_bytes(next(a for a in rep.enclosure["assets"] if a["kind"] == "stl")["url"])
    )
    assert stl.shape[1:] == (3, 3) and len(stl) > 100
    objs = read_3mf(
        _asset_bytes(next(a for a in rep.enclosure["assets"] if a["kind"] == "3mf")["url"])
    )
    assert len(objs) == 2 and all(len(t) > 10 for _, t in objs)


def test_timing(tmp_path, monkeypatch):
    monkeypatch.setenv("BARA_DATA_DIR", str(tmp_path))
    board, brief = macropad_board()
    rep = enclose_report(board, [], brief)
    assert rep.timings_ms["geometry"] < 150
    assert rep.timings_ms["total"] < 1000
    board, brief = split_right_board()
    rep = enclose_report(board, [], brief)
    assert rep.timings_ms["geometry"] < 500
    assert rep.timings_ms["total"] < 3000
    assert enclose(board, [], brief)["enclosure_id"] == rep.enclosure["enclosure_id"]


def test_usb_slot_never_crosses_a_notch(tmp_path, monkeypatch):
    """MCU beside a notch: the nearest edge faces -x across the notch, but that ray re-enters
    the case. The slot must exit through the top wall and leave the bezel in one piece."""
    monkeypatch.setenv("BARA_DATA_DIR", str(tmp_path))
    outline = [[0, 0], [100, 0], [100, 60], [60, 60], [60, 40], [50, 40], [50, 60], [0, 60]]
    board = {
        "board_id": "pcb_main",
        "side": "none",
        "outline": outline,
        "thickness_mm": 1.6,
        "placements": [
            {
                "ref": "U1",
                "lib_id": "Module:nice_nano",
                "role": "mcu",
                "x_mm": 66.0,
                "y_mm": 48.0,
                "rot_deg": 0,
                "side": "top",
                "height_mm": 3.2,
                "size_mm": [8.0, 12.0],
            },
            {
                "ref": "EN1",
                "lib_id": "Rotary_Encoder:RotaryEncoder_Alps_EC11E-Switch_Vertical_H20mm",
                "role": "encoder",
                "x_mm": 25.0,
                "y_mm": 45.0,
                "rot_deg": 0,
                "side": "top",
                "height_mm": 20.0,
                "size_mm": [12.0, 13.0],
            },
        ],
    }
    rep = enclose_report(board, [], {"features": ["knob"]})
    (usb,) = rep.openings["usb"]
    assert usb["face"] == "pos_y"
    assert len(rep.bezel.decompose()) == 1 and len(rep.tray.decompose()) == 1
    assert rep.enclosure["enclosure_id"] == "e_case_pcb_main"  # side "none": no half guessed
    failed = [c["message"] for c in rep.checks if c["status"] != "pass"]
    assert not failed, failed


def test_a_board_side_role_reads_the_part_not_the_word_module():
    from bara.geometry.case import _feature_from_placement

    jst = {
        "role": "module_connector",
        "lib_id": "Connector_JST:JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical",
        "label": "JST PH 2-pin connector to USB bridge",
        "size_mm": [6.9, 5.5],
    }
    mov = {"role": "module", "lib_id": "", "label": "V275LA20AP varistor", "size_mm": [17, 5.6]}
    assert _feature_from_placement(jst).role == "other"
    assert _feature_from_placement(mov).role == "other"
    # an ESD IC named USBLC6 is hidden, so it is no USB port; a touched module still reads
    esd = {"role": "module", "lib_id": "", "label": "USBLC6-2SC6 (ST)", "size_mm": [2.8, 2.9]}
    knob = {"role": "module", "label": "EC11E15244G1 encoder", "touch": True, "size_mm": [12, 14]}
    assert _feature_from_placement(esd).role == "other"
    assert _feature_from_placement(knob).role == "encoder"


def test_a_loose_bezel_sliver_is_dropped_and_real_pieces_stay():
    import manifold3d as mf

    from bara.geometry.case import _drop_slivers

    main = mf.Manifold.cube((60, 40, 4))
    sliver = mf.Manifold.cube((3, 6, 4)).translate((70, 0, 0))
    assert len(_drop_slivers(main + sliver).decompose()) == 1
    big = mf.Manifold.cube((20, 20, 4)).translate((70, 0, 0))
    assert len(_drop_slivers(main + big).decompose()) == 2  # a real piece is kept and reported
    island = mf.Manifold.cube((7, 7, 4)).translate((20, 15, 8))  # ringed by button holes
    assert len(_drop_slivers(main.scale((3, 3, 1)) + island).decompose()) == 1


def test_a_desk_facing_sensor_looks_through_the_floor_and_a_knob_fits_round(tmp_path, monkeypatch):
    monkeypatch.setenv("BARA_DATA_DIR", str(tmp_path))
    board = {
        "board_id": "pcb_main",
        "side": "none",
        "outline": [[0, 0], [60, 0], [60, 90], [0, 90]],
        "thickness_mm": 1.6,
        "placements": [
            {"ref": "M1", "role": "module", "label": "PMW3360DM-T2QU optical sensor",
             "x_mm": 30.0, "y_mm": 40.0, "rot_deg": 0, "side": "bottom", "on_pcb": False,
             "touch": True, "height_mm": 5.0, "size_mm": [10.9, 16.2]},
        ],
    }  # fmt: skip
    rep = enclose_report(board, [], {})
    fit = _by_rule(rep.checks, "mech.fit.enclosure")[0]
    assert fit["status"] == "pass", fit["message"]
    # the floor is open under the lens: a ray straight down from it leaves the tray
    from bara.geometry.validate import _first_hit

    assert _first_hit(rep.tray, np.array([30.0, 40.0, -1.0]), np.array([0, 0, -1.0]), 40) is None

    from bara.geometry.case import Feature
    from bara.geometry.validate import _feature_box

    knob = Feature("M8", "knob", 0.0, 0.0, 0.0, "top", 10.0, 20.0, 20.0)
    assert _feature_box(knob, 1.6).volume() < 0.8 * 20 * 20 * 10  # a disc, not its box
