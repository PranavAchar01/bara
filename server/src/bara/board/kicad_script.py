"""Runs inside KiCad's bundled Python (pcbnew). Do not import bara here.

Usage (spawned by bara.board.kicad):
    python3 kicad_script.py build PLAN.json   -> writes plan["board_path"] and plan["dsn_path"]
    python3 kicad_script.py import BOARD SES  -> applies a Specctra session, saves BOARD

Python 3.9 syntax only: this file is executed by KiCad's interpreter, not the server's.
"""

from __future__ import annotations

import json
import math
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
        # Append's hole index -1 means the outline itself: name the new hole, or its points
        # extend the outer ring into a self-crossing band that covers the board's middle
        h = poly.NewHole()
        for x, y in hole:
            poly.Append(_mm(x), _mm(y), -1, h)
    board.Add(zone)


_DROPPED: list = []


def _fit_holes(board, fp) -> None:
    """Bring a footprint's plated holes inside the board's hole rules.

    Footprints converted from other tools carry mil-rounded rings a hair under the minimum
    and unnumbered thermal vias drilled below the minimum hole; those vias only stitch an
    exposed pad, so they are dropped, and thin rings are grown to the minimum.
    """
    ds = board.GetDesignSettings()
    min_hole, ring = ds.m_MinThroughDrill, ds.m_ViasMinAnnularWidth
    pth = [p for p in fp.Pads() if p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH]
    # a thermal via is unnumbered or carries its exposed pad's number (an SMD pad's)
    smd = {p.GetNumber() for p in fp.Pads() if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD}
    vias = [
        p
        for p in pth
        if (not p.GetNumber() or p.GetNumber() in smd) and min(p.GetDrillSize()) < min_hole
    ]
    for pad in vias:
        fp.Remove(pad)
    # a removed pad freed by Python corrupts the footprint's pad list; keep it alive
    _DROPPED.extend(vias)
    for pad in pth:
        if pad in vias:
            continue
        drill = pad.GetDrillSize()
        size = pad.GetSize(pcbnew.F_Cu)
        want = pcbnew.VECTOR2I(
            max(size.x, drill.x + 2 * ring + _mm(0.01)), max(size.y, drill.y + 2 * ring + _mm(0.01))
        )
        if want.x != size.x or want.y != size.y:
            pad.SetSize(pcbnew.F_Cu, want)


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
    # Edge.Cuts that do not close (a jack drawn to splice into the board edge) are not
    # a cutout on our outline; keep them as a drawing so the outline stays closed.
    if not spec.get("edge_cuts", True):
        for g in fp.GraphicalItems():
            if g.GetLayer() == pcbnew.Edge_Cuts:
                g.SetLayer(pcbnew.Cmts_User)
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
    _fit_holes(board, fp)
    bottom = spec.get("side") == "bottom"
    if bottom:
        fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
    fp.SetPosition(_vec(spec["x"], spec["y"]))
    # A flip stores the pads mirrored in y; the extra half turn makes it the x
    # mirror the packer laid out (layout.Item.world), so pads land where planned.
    fp.SetOrientationDegrees(float(spec.get("rot", 0.0)) + (180.0 if bottom else 0.0))
    pads = spec.get("pads", {})
    for pad in fp.Pads():
        net_name = pads.get(pad.GetNumber())
        if net_name:
            pad.SetNet(_net(board, nets, net_name))
        else:
            pad.SetNetCode(0)
    # unnumbered holes inside an exposed pad are its thermal vias: they carry its net, or
    # every one is a short against the pad (DRV8833 HTSSOP)
    for pad in fp.Pads():
        if pad.GetNumber() or pad.GetAttribute() != pcbnew.PAD_ATTRIB_PTH:
            continue
        host = [p for p in fp.Pads() if p.GetNumber() and p.HitTest(pad.GetPosition())]
        if host and host[0].GetNetCode() > 0:
            pad.SetNet(host[0].GetNet())


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


def _foreign(board, net: int, layer: int) -> list:
    items = list(board.GetTracks()) + list(board.GetPads())
    foreign = [i for i in items if i.GetNetCode() != net and i.IsOnLayer(layer)]
    return [i.GetEffectiveShape(layer) for i in foreign]


def _put(t, joined: list, pa, pb, width: int) -> None:
    t.SetStart(pa)
    t.SetEnd(pb)
    t.SetWidth(width)
    for u, end, at_a in joined:
        (u.SetStart if end == "s" else u.SetEnd)(pa if at_a else pb)


def _repair_necks(board) -> int:
    """Widen Freerouting's sub-minimum necks, sliding each sideways until it clears.

    Freerouting narrows a trace where it squeezes past a fine-pitch pad, below the board's
    minimum width even with neckdown off. Widening in place hits the pad it squeezed past,
    so the neck and the ends of the traces joined to it slide along its normal in 5 um
    steps to the first spot where the full-width trace keeps clearance from other nets
    (with 5 um to spare: the shape test is looser than DRC on rounded pads).
    """
    ds = board.GetDesignSettings()
    mn = ds.m_TrackMinWidth
    clr = ds.m_NetSettings.GetDefaultNetclass().GetClearance()
    tracks = [t for t in board.GetTracks() if t.GetClass() == "PCB_TRACK"]
    fixed = 0
    for t in tracks:
        if t.GetWidth() >= mn - _mm(0.005):
            continue
        layer, net = t.GetLayer(), t.GetNetCode()
        # copies: GetStart() returns a live reference that SetStart() would move too
        a, b = pcbnew.VECTOR2I(t.GetStart()), pcbnew.VECTOR2I(t.GetEnd())
        if any(p.GetNetCode() == net and (p.HitTest(a) or p.HitTest(b)) for p in board.GetPads()):
            continue  # a pin entry: sliding it would leave the pad
        joined = []
        for u in tracks:
            if u is not t and u.GetNetCode() == net and u.GetLayer() == layer:
                for end, pos in (("s", u.GetStart()), ("e", u.GetEnd())):
                    if pos == a or pos == b:
                        joined.append((u, end, pos == a))
        n = math.hypot(b.x - a.x, b.y - a.y) or 1.0
        nx, ny = -(b.y - a.y) / n, (b.x - a.x) / n
        others = _foreign(board, net, layer)
        width = t.GetWidth()

        for k in [0] + [s * i for i in range(1, 17) for s in (1, -1)]:
            off = _mm(0.005 * k)
            dx, dy = int(round(nx * off)), int(round(ny * off))
            pa, pb = pcbnew.VECTOR2I(a.x + dx, a.y + dy), pcbnew.VECTOR2I(b.x + dx, b.y + dy)
            _put(t, joined, pa, pb, mn)
            moved = [t.GetEffectiveShape(layer)]
            moved += [u.GetEffectiveShape(layer) for u, _, _ in joined]
            if not any(m.Collide(o, clr + _mm(0.005)) for m in moved for o in others):
                fixed += 1
                break
        else:
            _put(t, joined, a, b, width)
    return fixed


def import_ses(board_path: str, ses_path: str) -> None:
    board = pcbnew.LoadBoard(board_path)
    ok = pcbnew.ImportSpecctraSES(board, ses_path)
    if not ok:
        raise RuntimeError("SES import failed")
    _repair_necks(board)
    pcbnew.SaveBoard(board_path, board)


if __name__ == "__main__":
    if sys.argv[1] == "build":
        build(sys.argv[2])
    elif sys.argv[1] == "import":
        import_ses(sys.argv[2], sys.argv[3])
    else:
        raise SystemExit("unknown command " + sys.argv[1])
