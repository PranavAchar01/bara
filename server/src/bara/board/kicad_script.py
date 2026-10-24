"""Runs inside KiCad's bundled Python (pcbnew). Do not import bara here.

Usage (spawned by bara.board.kicad):
    python3 kicad_script.py build PLAN.json   -> writes plan["board_path"] and plan["dsn_path"]
    python3 kicad_script.py import BOARD SES  -> applies a Specctra session, saves BOARD

Python 3.9 syntax only: this file is executed by KiCad's interpreter, not the server's.
"""

from __future__ import annotations

import json
import sys

import pcbnew


def _mm(v: float) -> int:
    return pcbnew.FromMM(float(v))


def _vec(x: float, y: float):
    return pcbnew.VECTOR2I(_mm(x), _mm(y))


def _layer(board, name: str) -> int:
    return board.GetLayerID(name)


def _set_rules(board, rules: dict) -> None:
    ds = board.GetDesignSettings()
    ns = ds.m_NetSettings
    default = ns.GetDefaultNetclass()
    default.SetClearance(_mm(rules["clearance_mm"]))
    default.SetTrackWidth(_mm(rules["track_mm"]))
    default.SetViaDiameter(_mm(rules["via_mm"]))
    default.SetViaDrill(_mm(rules["via_drill_mm"]))
    ds.m_CopperEdgeClearance = _mm(rules["edge_clearance_mm"])
    ds.m_MinClearance = _mm(min(rules["clearance_mm"], 0.2))
    ds.m_TrackMinWidth = _mm(rules.get("min_track_mm", rules["track_mm"]))
    for name, severity in rules.get("severities", {}).items():
        code = getattr(pcbnew, "DRCE_" + name.upper(), None)
        sev = getattr(pcbnew, "RPT_SEVERITY_" + severity.upper(), None)
        if code is not None and sev is not None:
            ds.m_DRCSeverities[code] = sev


def _net(board, nets: dict, name: str):
    if not name:
        return None
    if name not in nets:
        item = pcbnew.NETINFO_ITEM(board, name)
        board.Add(item)
        nets[name] = item
    return nets[name]


def _poly_segments(board, pts: list, layer: str, width: float = 0.1) -> None:
    lid = _layer(board, layer)
    n = len(pts)
    for i in range(n):
        a = pts[i]
        b = pts[(i + 1) % n]
        seg = pcbnew.PCB_SHAPE(board)
        seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
        seg.SetStart(_vec(a[0], a[1]))
        seg.SetEnd(_vec(b[0], b[1]))
        seg.SetLayer(lid)
        seg.SetWidth(_mm(width))
        board.Add(seg)


def _circle(board, cx: float, cy: float, r: float, layer: str, width: float = 0.1) -> None:
    c = pcbnew.PCB_SHAPE(board)
    c.SetShape(pcbnew.SHAPE_T_CIRCLE)
    c.SetCenter(_vec(cx, cy))
    c.SetEnd(_vec(cx + r, cy))
    c.SetLayer(_layer(board, layer))
    c.SetWidth(_mm(width))
    board.Add(c)


def _rule_area(board, outer: list, holes: list, layers: list, name: str) -> None:
    zone = pcbnew.ZONE(board)
    zone.SetIsRuleArea(True)
    zone.SetDoNotAllowTracks(True)
    zone.SetDoNotAllowVias(True)
    zone.SetDoNotAllowZoneFills(True)
    zone.SetDoNotAllowPads(False)
    zone.SetDoNotAllowFootprints(False)
    zone.SetZoneName(name)
    lset = pcbnew.LSET()
    for ln in layers:
        lset.AddLayer(_layer(board, ln))
    zone.SetLayerSet(lset)
    # Edit the zone's own outline: SetOutline() takes ownership of a Python-owned
    # SHAPE_POLY_SET and the later double free segfaults SaveBoard.
    poly = zone.Outline()
    poly.NewOutline()
    for x, y in outer:
        poly.Append(_mm(x), _mm(y))
    for hole in holes:
        poly.NewHole()
        for x, y in hole:
            poly.Append(_mm(x), _mm(y), -1, -1)
    board.Add(zone)


def _place_footprint(board, nets: dict, spec: dict) -> None:
    fp = pcbnew.FootprintLoad(spec["lib_dir"], spec["name"])
    if fp is None:
        raise RuntimeError(f"footprint not found: {spec['lib_dir']}/{spec['name']}")
    fp.SetReference(spec["ref"])
    fp.SetValue(spec.get("value", spec["name"]))
    fp.Reference().SetVisible(bool(spec.get("show_ref", False)))
    fp.SetFPIDAsString(spec.get("lib_id", spec["name"]))
    # Footprint rule areas that only forbid copper pours (e.g. the nice!nano "ANT" area)
    # are exported to Specctra as hard keepouts, which blocks the module's own pads. We
    # never pour copper, so drop them; areas that forbid tracks stay.
    for zone in list(fp.Zones()):
        if zone.GetIsRuleArea() and not zone.GetDoNotAllowTracks():
            fp.Remove(zone)
    # Models: replace the library paths with resolved absolute files.
    models = fp.Models()
    models.clear()
    for m in spec.get("models", []):
        mod = pcbnew.FP_3DMODEL()
        mod.m_Filename = m["path"]
        off = m.get("offset", [0, 0, 0])
        rot = m.get("rotate", [0, 0, 0])
        sc = m.get("scale", [1, 1, 1])
        mod.m_Offset = pcbnew.VECTOR3D(off[0], off[1], off[2])
        mod.m_Rotation = pcbnew.VECTOR3D(rot[0], rot[1], rot[2])
        mod.m_Scale = pcbnew.VECTOR3D(sc[0], sc[1], sc[2])
        models.push_back(mod)
    board.Add(fp)
    if spec.get("side") == "bottom":
        fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
    fp.SetPosition(_vec(spec["x"], spec["y"]))
    fp.SetOrientationDegrees(float(spec.get("rot", 0.0)))
    pads = spec.get("pads", {})
    for pad in fp.Pads():
        net_name = pads.get(pad.GetNumber())
        if net_name:
            pad.SetNet(_net(board, nets, net_name))
        else:
            pad.SetNetCode(0)


def build(plan_path: str) -> None:
    with open(plan_path) as fh:
        plan = json.load(fh)
    board = pcbnew.NewBoard(plan["board_path"])
    board.SetCopperLayerCount(2)
    _set_rules(board, plan["rules"])
    nets: dict = {}
    for name in plan.get("nets", []):
        _net(board, nets, name)
    _poly_segments(board, plan["outline"], "Edge.Cuts")
    for hole in plan.get("holes", []):
        if hole.get("circle"):
            cx, cy, r = hole["circle"]
            _circle(board, cx, cy, r, "Edge.Cuts")
        else:
            _poly_segments(board, hole["poly"], "Edge.Cuts")
    for area in plan.get("rule_areas", []):
        _rule_area(board, area["outer"], area.get("holes", []), area["layers"], area["name"])
    for spec in plan["footprints"]:
        _place_footprint(board, nets, spec)
    pcbnew.SaveBoard(plan["board_path"], board)
    if plan.get("dsn_path"):
        # Reload so KiCad rebuilds net codes and connectivity the way the editor would.
        loaded = pcbnew.LoadBoard(plan["board_path"])
        if not pcbnew.ExportSpecctraDSN(loaded, plan["dsn_path"]):
            raise RuntimeError("DSN export failed")


def import_ses(board_path: str, ses_path: str) -> None:
    board = pcbnew.LoadBoard(board_path)
    ok = pcbnew.ImportSpecctraSES(board, ses_path)
    if not ok:
        raise RuntimeError("SES import failed")
    pcbnew.SaveBoard(board_path, board)


if __name__ == "__main__":
    if sys.argv[1] == "build":
        build(sys.argv[2])
    elif sys.argv[1] == "import":
        import_ses(sys.argv[2], sys.argv[3])
    else:
        raise SystemExit("unknown command " + sys.argv[1])
