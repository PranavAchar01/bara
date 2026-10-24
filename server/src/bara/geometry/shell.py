"""Sculpted product shell: a smooth plan outline, a body whose thickness follows the plan, real
edge fillets, and features cut at the form's anchors.

Everything here is driven by the generic product form only: the silhouette (as the board outline
plus the case wall), the thickness profile (thickness_mm and edge_thickness_mm) and the anchors
(kind of control, where it sits, which way an edge anchor faces). There is no per-device logic.

Frame: the board frame of case.py (mm, Z up, board bottom at z = 0).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

import manifold3d as mf
import numpy as np
import shapely
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import unary_union

# ---------------------------------------------------------------- plan outline


def chaikin(ring: np.ndarray, rounds: int = 3) -> np.ndarray:
    """Corner cutting on a closed ring: each round replaces every corner by two points at 1/4
    and 3/4 of its edges, converging on a quadratic B-spline."""
    pts = np.asarray(ring, dtype=np.float64)
    for _ in range(rounds):
        nxt = np.roll(pts, -1, axis=0)
        out = np.empty((len(pts) * 2, 2))
        out[0::2] = 0.75 * pts + 0.25 * nxt
        out[1::2] = 0.25 * pts + 0.75 * nxt
        pts = out
    return pts


def resample_ring(ring: np.ndarray, step: float) -> np.ndarray:
    """Uniform arc-length resample of a closed ring (no repeated end point)."""
    closed = np.vstack([ring, ring[:1]])
    seg = np.linalg.norm(np.diff(closed, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    n = max(8, int(round(s[-1] / step)))
    t = np.linspace(0.0, s[-1], n, endpoint=False)
    return np.column_stack([np.interp(t, s, closed[:, 0]), np.interp(t, s, closed[:, 1])])


def gaussian_ring(ring: np.ndarray, sigma_pts: float) -> np.ndarray:
    """Circular Gaussian smoothing of a closed ring's coordinates."""
    if sigma_pts < 0.5:
        return ring
    half = int(math.ceil(3 * sigma_pts))
    k = np.exp(-0.5 * (np.arange(-half, half + 1) / sigma_pts) ** 2)
    k /= k.sum()
    n = len(ring)
    out = np.empty_like(ring)
    for c in range(2):
        pad = np.concatenate([ring[-half:, c], ring[:, c], ring[:half, c]]) if half < n else None
        if pad is None:
            return ring
        out[:, c] = np.convolve(pad, k, mode="valid")
    return out


def smooth_loop(points: list[tuple[float, float]], radius: float) -> list[tuple[float, float]]:
    """A lumpy closed polygon as a smooth closed curve: corner cutting, then arc-length
    resampling at 1 mm and a Gaussian whose width follows the minimum corner radius."""
    ring = np.asarray(points, dtype=np.float64)
    if len(ring) > 1 and np.allclose(ring[0], ring[-1]):
        ring = ring[:-1]
    ring = chaikin(ring, 2)
    ring = resample_ring(ring, 1.0)
    ring = gaussian_ring(ring, 0.5 * radius)
    return [(float(x), float(y)) for x, y in ring]


def plan_min_radius(w: float, h: float) -> float:
    """Smallest corner radius of the outline, from the size class of the product."""
    short = min(w, h)
    return float(min(14.0, max(3.5, 0.07 * short)))


def _largest(g: Any) -> Polygon:
    if isinstance(g, MultiPolygon):
        g = max(g.geoms, key=lambda p: p.area)
    return Polygon(g.exterior)


def smooth_plan(raw: Polygon, radius: float, required: Polygon | None = None) -> Polygon:
    """A smooth, simple outline that contains `required` (the board plus its wall), with every
    corner at least `radius` round. Smoothing may only add material where it would cut in."""
    smooth = Polygon(smooth_loop(list(raw.exterior.coords), radius))
    if not smooth.is_valid:
        smooth = _largest(smooth.buffer(0))
    r = 0.7 * radius
    shape = smooth.buffer(r, join_style="round").buffer(-2 * r, join_style="round")
    shape = shape.buffer(r, join_style="round")  # closing, then opening
    shape = _largest(shape) if not shape.is_empty else smooth
    if required is not None:
        shape = _largest(unary_union([shape, required]))
    return shape.simplify(0.02)


# ---------------------------------------------------------------- distance raster


def _blur(a: np.ndarray, sigma: float) -> np.ndarray:
    if sigma < 0.5:
        return a
    half = int(math.ceil(3 * sigma))
    k = np.exp(-0.5 * (np.arange(-half, half + 1) / sigma) ** 2)
    k /= k.sum()
    for axis in (0, 1):
        pad = [(0, 0), (0, 0)]
        pad[axis] = (half, half)
        p = np.pad(a, pad, mode="edge")
        out = np.zeros_like(a)
        for i, w in enumerate(k):
            sl = [slice(None), slice(None)]
            sl[axis] = slice(i, i + a.shape[axis])
            out += w * p[tuple(sl)]
        a = out
    return a


def _dilate(a: np.ndarray, r: int) -> np.ndarray:
    for axis in (0, 1):
        pad = [(0, 0), (0, 0)]
        pad[axis] = (r, r)
        p = np.pad(a, pad, mode="edge")
        out = a.copy()
        for i in range(0, 2 * r + 1, max(1, r // 12)):
            sl = [slice(None), slice(None)]
            sl[axis] = slice(i, i + a.shape[axis])
            out = np.maximum(out, p[tuple(sl)])
        a = out
    return a


@dataclass
class Raster:
    x0: float
    y0: float
    step: float
    d: np.ndarray  # (ny, nx) signed distance to the outline, positive inside

    @property
    def ny(self) -> int:
        return self.d.shape[0]

    @property
    def nx(self) -> int:
        return self.d.shape[1]

    def sample(self, arr: np.ndarray, x: float, y: float) -> float:
        fx, fy = (x - self.x0) / self.step, (y - self.y0) / self.step
        ix, iy = int(math.floor(fx)), int(math.floor(fy))
        ix, iy = min(max(ix, 0), self.nx - 2), min(max(iy, 0), self.ny - 2)
        tx, ty = min(max(fx - ix, 0.0), 1.0), min(max(fy - iy, 0.0), 1.0)
        a = arr[iy, ix] * (1 - tx) + arr[iy, ix + 1] * tx
        b = arr[iy + 1, ix] * (1 - tx) + arr[iy + 1, ix + 1] * tx
        return float(a * (1 - ty) + b * ty)


def build_raster(poly: Polygon, step: float) -> Raster:
    x0, y0, x1, y1 = poly.bounds
    pad = 4 * step
    xs = np.arange(x0 - pad, x1 + pad + step, step)
    ys = np.arange(y0 - pad, y1 + pad + step, step)
    ring = resample_ring(np.asarray(poly.exterior.coords)[:-1], step)
    a, b = ring, np.roll(ring, -1, axis=0)
    ab = b - a
    den = np.maximum((ab**2).sum(axis=1), 1e-12)
    gx, gy = np.meshgrid(xs, ys)
    pts = np.column_stack([gx.ravel(), gy.ravel()])
    dist = np.empty(len(pts))
    for lo in range(0, len(pts), 4000):
        p = pts[lo : lo + 4000][:, None, :]
        t = np.clip(((p - a) * ab).sum(axis=2) / den, 0.0, 1.0)
        proj = a + t[:, :, None] * ab
        dist[lo : lo + 4000] = np.sqrt(((p - proj) ** 2).sum(axis=2)).min(axis=1)
    inside = shapely.contains_xy(poly, pts[:, 0], pts[:, 1])
    d = np.where(inside, dist, -dist).reshape(gx.shape)
    return Raster(float(xs[0]), float(ys[0]), step, d)


# ---------------------------------------------------------------- body


@dataclass
class Profile:
    """The vertical shape of the body, over the plan. Heights are board-frame z."""

    z_floor: float  # underside where the stack needs it (never higher than this inside)
    z_top: float  # top plateau before the crown
    crown: float  # extra height at the middle of the top
    belly: float  # extra depth at the middle of the underside
    rt: float  # top edge fillet radius
    rb: float  # bottom edge fillet radius


def profile_for(
    z_bot: float,
    seat: float,
    bezel_top: float,
    body: float,
    edge: float,
    short: float,
    r_min: float,
) -> Profile:
    """Thickness profile -> shape. `body` is the thickest the product gets, `edge` the thinnest
    rim; the stack (board, parts, floor, bezel plate) is the floor on both."""
    ref = max(body, 14.0)
    rt = min(0.2 * ref, 4.5, 0.8 * r_min)
    rb = min(0.3 * ref, 7.0, 0.9 * r_min)
    z_top = max(bezel_top, seat + 0.6 * rt)
    plateau = z_top - z_bot
    spread = max(body - max(plateau, edge), 0.0)
    flat = min(0.04 * short, 2.0)
    crown = min(max(0.35 * spread, 0.6 * flat), 6.0, 0.1 * short)
    belly = max(spread - crown, flat)
    land = (z_top - rt) - (z_bot + rb)
    if land < 1.5:  # a thin product: keep a straight band at the parting line
        k = max(0.3, 1.0 - (1.5 - land) / max(rt + rb, 1e-6))
        rt, rb = rt * k, rb * k
    return Profile(z_bot, z_top, crown, belly, rt, rb)


def _fillet(d: np.ndarray, r: float) -> np.ndarray:
    """Quarter-circle drop at the rim: r at d = 0, zero from d = r inward."""
    x = np.clip(d, 0.0, r)
    return r - np.sqrt(np.maximum(r * r - (r - x) ** 2, 0.0))


@dataclass
class Body:
    plan: Polygon
    raster: Raster
    top: np.ndarray
    bottom: np.ndarray
    profile: Profile
    solid: mf.Manifold

    def top_at(self, x: float, y: float) -> float:
        return self.raster.sample(self.top, x, y)

    def bottom_at(self, x: float, y: float) -> float:
        return self.raster.sample(self.bottom, x, y)

    def land(self) -> tuple[float, float]:
        """Rim band: lowest and highest z of the straight wall at the outline."""
        p = self.profile
        return p.z_floor + p.rb, p.z_top - p.rt


def build_body(plan: Polygon, prof: Profile, edge_len: float = 1.0) -> Body:
    x0, y0, x1, y1 = plan.bounds
    step = max(0.5, max(x1 - x0, y1 - y0) / 360.0)
    ras = build_raster(plan, step)
    d = ras.d
    dpos = np.maximum(d, 0.0)
    ds = _blur(dpos, 2.5 / step)
    dmax = float(ds.max()) or 1.0
    # a lobe is as thick as its own middle: depth relative to the deepest point nearby, so the
    # necks between lobes read thinner than the lobes themselves
    reach = max(2, int(0.5 * dmax / step))
    dil = np.maximum(_dilate(ds, reach), 1e-6)
    u = np.clip(ds / dil, 0.0, 1.0)
    u = _blur(u, 2.0 / step)
    s_top = 1.0 - (1.0 - u) ** 2
    s_bot = 1.0 - (1.0 - u) ** 1.6
    top0 = prof.z_top + prof.crown * s_top  # the surface before the rim is rounded
    bot0 = prof.z_floor - prof.belly * s_bot
    top = top0 - _fillet(dpos, prof.rt)
    bot = bot0 + _fillet(dpos, prof.rb)

    tl, bl, dl = top0.ravel().tolist(), bot0.ravel().tolist(), d.ravel().tolist()
    nx, ny, inv = ras.nx, ras.ny, 1.0 / step
    rx0, ry0 = ras.x0, ras.y0
    rt, rb = prof.rt, prof.rb
    hypot = math.hypot

    def sdf(x: float, y: float, z: float) -> float:
        fx, fy = (x - rx0) * inv, (y - ry0) * inv
        ix, iy = int(fx), int(fy)
        if fx < 0 or fy < 0 or ix >= nx - 1 or iy >= ny - 1:
            return -1.0
        tx, ty = fx - ix, fy - iy
        i = iy * nx + ix
        w00, w10, w01, w11 = (1 - tx) * (1 - ty), tx * (1 - ty), (1 - tx) * ty, tx * ty
        dd = dl[i] * w00 + dl[i + 1] * w10 + dl[i + nx] * w01 + dl[i + nx + 1] * w11
        tt = tl[i] * w00 + tl[i + 1] * w10 + tl[i + nx] * w01 + tl[i + nx + 1] * w11
        bb = bl[i] * w00 + bl[i + 1] * w10 + bl[i + nx] * w01 + bl[i + nx + 1] * w11
        # distance to the top and bottom faces; within a fillet radius of the rim the rounded
        # edge is a true circle (a distance field, so the iso-surface stays smooth)
        a, b = tt - z, z - bb
        if dd < rt and a < rt:
            a = rt - hypot(rt - dd, rt - a)
        if dd < rb and b < rb:
            b = rb - hypot(rb - dd, rb - b)
        return min(dd, a, b)

    zlo = float(bot.min()) - 1.0
    zhi = float(top.max()) + 1.0
    lo = (x0 - 2 * step, y0 - 2 * step, zlo)
    hi = (x1 + 2 * step, y1 + 2 * step, zhi)
    solid = mf.Manifold.level_set(sdf, [*lo, *hi], edge_len)
    return Body(plan, ras, top, bot, prof, solid)


# ---------------------------------------------------------------- anchors -> sites

KIND_WORDS: list[tuple[str, str]] = [
    ("screen", r"screen|display|lcd|oled|e-?ink|epaper|tft|panel"),
    ("port", r"usb|connector|charg|jack|socket|plug|cable|hdmi|ethernet|\bport"),
    ("stick", r"stick|joy|analog|trackpoint"),
    ("dpad", r"d-?pad|directional|\bcross\b|arrow|navigation"),
    ("shoulder", r"shoulder|trigger|bumper|\blb\b|\brb\b|\blt\b|\brt\b"),
    ("knob", r"knob|dial|encoder|crown|wheel"),
    ("button", r"button|key|switch|press|click|action|face|start|select|menu|home|power|side"),
]


def classify(anchor: dict[str, Any]) -> str:
    text = " ".join(str(anchor.get(k) or "") for k in ("name", "purpose", "slot_id")).lower()
    for kind, pat in KIND_WORDS:
        if re.search(pat, text):
            return kind
    return "touch"


@dataclass
class Site:
    kind: str
    group: int  # anchor index: instances of one anchor share a group
    x: float
    y: float
    mount: str
    normal_deg: float  # board frame (y down)
    w: float = 0.0
    d: float = 0.0
    rot: float = 0.0
    round_window: bool = False
    ref: str = ""
    pitch: float = 0.0
    z_hi: float = 0.0  # top of the part under it, board frame


def sites_from_anchors(
    anchors: list[dict[str, Any]], feats: list[Any], board_top: float = 0.0
) -> list[Site]:
    """One site per anchor instance, sized from the nearest unclaimed part footprint."""
    from bara.live.form import expand  # local: live imports geometry

    sites: list[Site] = []
    claimed: set[str] = set()
    for gi, a in enumerate(anchors):
        kind = classify(a)
        n = max(1, int(a.get("count") or 1))
        pitch = float(a.get("pitch_mm") or 0.0)
        text = f"{a.get('purpose', '')} {a.get('name', '')}".lower()
        for x, y in expand(a, n):
            s = Site(
                kind=kind,
                group=gi,
                x=float(x),
                y=-float(y),
                mount=str(a.get("mount") or "front"),
                normal_deg=-float(a.get("edge_normal_deg") or 0.0),
                pitch=pitch,
                round_window=bool(re.search(r"round|circular", text)),
            )
            near = None
            best = 30.0 if kind == "port" else max(6.0, 0.7 * pitch)
            for f in feats:
                if f.ref in claimed or f.role in ("battery", "sensor", "trackball"):
                    continue
                if (kind == "port") != (f.role in ("usb", "mcu")):
                    continue
                dist = math.hypot(f.x - s.x, f.y - s.y)
                if dist < best:
                    best, near = dist, f
            if near is not None:
                claimed.add(near.ref)
                s.x, s.y = near.x, near.y  # the feature sits over the part, not the loose anchor
                s.w, s.d, s.rot, s.ref = near.w, near.d, near.rot_deg, near.ref
                s.z_hi = near.z_range(board_top)[1]
            sites.append(s)
    return sites


# ---------------------------------------------------------------- feature solids

TOUCH_MIN_MM = 9.0


def _cyl(r: float, z0: float, z1: float, x: float, y: float, seg: int = 48) -> mf.Manifold:
    return mf.Manifold.cylinder(max(z1 - z0, 1e-3), r, r, seg).translate((x, y, z0))


def _revolve(profile: list[tuple[float, float]], x: float, y: float, seg: int = 48) -> mf.Manifold:
    """Revolve an (r, z) profile polygon about the vertical axis through (x, y)."""
    cs = mf.CrossSection([[list(p) for p in profile]])
    return mf.Manifold.revolve(cs, seg).translate((x, y, 0))


def _arc(
    c: tuple[float, float], r: float, a0: float, a1: float, n: int
) -> list[tuple[float, float]]:
    return [
        (c[0] + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
         c[1] + r * math.sin(math.radians(a0 + (a1 - a0) * i / n)))
        for i in range(n + 1)
    ]  # fmt: skip


def _rrect(cx: float, cy: float, w: float, d: float, rot: float, r: float) -> mf.CrossSection:
    a = math.radians(rot)
    rm = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
    pts = np.array([[-w / 2, -d / 2], [w / 2, -d / 2], [w / 2, d / 2], [-w / 2, d / 2]])
    cs = mf.CrossSection([(pts @ rm.T + [cx, cy]).tolist()])
    r = min(r, 0.49 * min(w, d))
    if r > 0.05:
        cs = cs.offset(-r, mf.JoinType.Round).offset(r, mf.JoinType.Round)
    return cs


def _prism(cs: mf.CrossSection, z0: float, z1: float) -> mf.Manifold:
    return mf.Manifold.extrude(cs, max(z1 - z0, 1e-3)).translate((0, 0, z0))


def snap_axis(deg: float, tol: float) -> float:
    """The nearest axis direction when within tol degrees, else the angle itself."""
    near = round(deg / 90.0) * 90.0
    return near % 360 if abs(deg - near) <= tol else deg


def _flare(cs: mf.CrossSection, z0: float, z1: float, grow: float) -> mf.Manifold:
    """cs extruded from z0 to z1 widening by `grow` on every side at the top (a bevel)."""
    x0, y0, x1, y1 = cs.bounds()
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    w, h = max(x1 - x0, 1e-3), max(y1 - y0, 1e-3)
    scale = ((w + 2 * grow) / w, (h + 2 * grow) / h)
    m = mf.Manifold.extrude(cs.translate((-cx, -cy)), z1 - z0, 0, 0.0, scale)
    return m.translate((cx, cy, z0))


def connect_pieces(m: mf.Manifold, bound: mf.Manifold, z_cap: float) -> mf.Manifold:
    """Tie every loose piece of m to the biggest one with a rib, so the part prints and holds as
    one body. Ribs run between the pieces' footprints, stay below z_cap (under the board) and
    inside `bound` (the sculpted shell)."""
    for _ in range(6):
        pieces = m.decompose()
        if len(pieces) <= 1:
            return m
        pieces.sort(key=lambda p: -p.volume())
        main = pieces[0]
        mb = main.bounding_box()
        for p in pieces[1:]:
            pb = p.bounding_box()
            z0 = max(mb[2], pb[2])
            z1 = min(mb[5], pb[5], z_cap)
            if z1 - z0 < 1.0:
                z0, z1 = min(mb[5], pb[5], z_cap) - 2.0, min(mb[5], pb[5], z_cap)
            a = ((mb[0] + mb[3]) / 2, (mb[1] + mb[4]) / 2)
            b = ((pb[0] + pb[3]) / 2, (pb[1] + pb[4]) / 2)
            rib = LineString([a, b]).buffer(1.4, cap_style="flat")
            cs = mf.CrossSection([list(rib.exterior.coords)[:-1]])
            m = m + (_prism(cs, z0, z1) ^ bound)
    return m


def _along(m: mf.Manifold, ang_deg: float, x: float, y: float, z: float) -> mf.Manifold:
    """A solid built along +Z, turned to run along horizontal direction ang_deg from (x, y, z)."""
    return m.rotate((0, 90, 0)).rotate((0, 0, ang_deg)).translate((x, y, z))


@dataclass
class Features:
    cuts: list[mf.Manifold] = field(default_factory=list)  # out of the bezel
    wall_cuts: list[mf.Manifold] = field(default_factory=list)  # out of tray and bezel
    adds: list[mf.Manifold] = field(default_factory=list)  # onto the bezel
    caps: list[mf.Manifold] = field(default_factory=list)  # separate coloured parts
    glass: list[mf.Manifold] = field(default_factory=list)
    cutouts: list[dict[str, Any]] = field(default_factory=list)
    ports: list[dict[str, Any]] = field(default_factory=list)  # axis-facing ports, for checks
    claimed: set[str] = field(default_factory=set)
    kinds: dict[str, int] = field(default_factory=dict)


def shoulder_lobes(sites: list[Site], plan: Polygon) -> list[Polygon]:
    """A bump on the outline where shoulder or trigger anchors face the edge."""
    by_group: dict[int, list[Site]] = {}
    for s in sites:
        if s.kind == "shoulder" and s.mount == "edge":
            by_group.setdefault(s.group, []).append(s)
    lobes: list[Polygon] = []
    for group in by_group.values():
        cx = sum(s.x for s in group) / len(group)
        cy = sum(s.y for s in group) / len(group)
        nx, ny = (
            math.cos(math.radians(group[0].normal_deg)),
            math.sin(math.radians(group[0].normal_deg)),
        )
        tx, ty = -ny, nx
        hit = _exit_distance(plan, cx, cy, nx, ny)
        if hit is None:
            continue
        span = max(abs((s.x - cx) * tx + (s.y - cy) * ty) for s in group)
        half_w = span + max(max(s.w, s.d) for s in group) / 2 + 6.0
        out, back = 3.5, 6.0
        c = [(-half_w, -back), (half_w, -back), (half_w, out), (-half_w, out)]
        p0 = (cx + nx * hit, cy + ny * hit)
        pts = [(p0[0] + tx * u + nx * v, p0[1] + ty * u + ny * v) for u, v in c]
        lobe = Polygon(pts).buffer(-2.0, join_style="round").buffer(2.0, join_style="round")
        lobes.append(lobe)
    return lobes


def _exit_distance(plan: Polygon, x: float, y: float, dx: float, dy: float) -> float | None:
    far = max(plan.bounds[2] - plan.bounds[0], plan.bounds[3] - plan.bounds[1]) * 2
    hit = plan.exterior.intersection(LineString([(x, y), (x + dx * far, y + dy * far)]))
    if hit.is_empty:
        return None
    pts = [hit] if isinstance(hit, Point) else list(getattr(hit, "geoms", [hit]))
    ds = [math.hypot(p.x - x, p.y - y) for p in pts if isinstance(p, Point)]
    return max(ds) if ds else None


def build_features(
    sites: list[Site],
    body: Body,
    seat: float,
    wall_mm: float,
    clear: float,
    port_w: float,
    port_h: float,
    z_port: dict[str, float],
) -> Features:
    """Cut and add the features at every site. Sizes come from the part footprint plus
    clearance; sites without a part use a finger-sized default."""
    out = Features()
    zmax = body.profile.z_top + body.profile.crown + 2.0
    done_groups: set[int] = set()
    knobs = [k for k in sites if k.kind in ("stick", "knob") and k.mount == "front"]
    for s in sites:
        if s.ref:
            out.claimed.add(s.ref)
        if s.w and s.d:  # a pocket the part's full footprint wide, hidden under the top surface;
            # every claimed part gets it, whatever the site builds (port, back, shoulder)
            pocket = _rrect(s.x, s.y, s.w + 2 * clear, s.d + 2 * clear, s.rot, 0.8)
            out.cuts.append(_prism(pocket, seat - 1.0, max(s.z_hi, seat) + clear))
        if s.kind == "shoulder" and s.mount == "edge":
            if s.group not in done_groups:
                done_groups.add(s.group)
                _shoulder(out, [t for t in sites if t.group == s.group], body, seat, clear)
            out.kinds[s.kind] = out.kinds.get(s.kind, 0) + 1
            continue
        if s.kind == "button" and s.mount == "front" and _under_knob(s, knobs, clear):
            continue  # pressed through the wheel or stick above it (a mouse's middle click)
        if s.kind == "port" or s.mount == "back":
            if s.kind == "port":
                _port(out, s, body, wall_mm, port_w, port_h, z_port)
            continue
        if s.mount == "edge":
            _edge_button(out, s, body, wall_mm, clear)
        elif s.kind == "screen":
            _screen(out, s, body, seat, zmax, clear)
        elif s.kind == "dpad":
            if s.group not in done_groups:
                done_groups.add(s.group)
                _dpad(out, [t for t in sites if t.group == s.group], body, seat, zmax, clear)
        elif s.kind in ("stick", "knob"):
            _stick(out, s, body, seat, zmax, clear)
        else:
            _button(out, s, body, seat, zmax, clear)
        out.kinds[s.kind] = out.kinds.get(s.kind, 0) + 1
    return out


def _local_top(body: Body, x: float, y: float, r: float) -> tuple[float, float]:
    zs = [
        body.top_at(x + r * math.cos(a), y + r * math.sin(a))
        for a in np.linspace(0, 2 * math.pi, 12, endpoint=False)
    ]
    zs.append(body.top_at(x, y))
    return min(zs), max(zs)


def _stick_radius(s: Site, clear: float) -> float:
    return max(max(s.w, s.d) / 2 + clear + 0.6, 7.0)


def _under_knob(s: Site, knobs: list[Site], clear: float) -> bool:
    return any(math.hypot(s.x - k.x, s.y - k.y) < _stick_radius(k, clear) for k in knobs)


def _stick(out: Features, s: Site, body: Body, seat: float, zmax: float, clear: float) -> None:
    r_h = _stick_radius(s, clear)
    r_w = r_h + 5.5
    z_lo, z_hi = _local_top(body, s.x, s.y, r_w)
    zc = body.top_at(s.x, s.y)
    depth = 1.7
    big = (r_w**2 + depth**2) / (2 * depth)
    dish = mf.Manifold.sphere(big, 96).translate((s.x, s.y, zc - depth + big))
    out.cuts.append(dish)
    out.cuts.append(_cyl(r_h, seat - 1.0, zmax + 6, s.x, s.y))
    top_arc = _arc((r_w + 0.5, z_hi + 0.5), 0.9, 180, 0, 8)
    rim = [(r_w - 0.4, z_lo - 2.0), (r_w - 0.4, z_hi + 0.5), *top_arc, (r_w + 1.4, z_lo - 2.0)]
    ring = _revolve(rim, s.x, s.y, 72)
    out.adds.append(ring)
    rc = r_h - 0.7
    z0 = max(seat + 0.3, zc - 3.0)
    prof = [(0.0, z0), (rc, z0), (rc, zc + 3.4),
            *_arc((rc - 1.2, zc + 3.4), 1.2, 0, 90, 5),
            (rc - 4.5, zc + 4.6), (0.0, zc + 3.7)]  # fmt: skip
    out.caps.append(_revolve(prof, s.x, s.y, 72))
    out.cutouts.append(_cut("stick", s.x, s.y, zc, 2 * r_h, "circle"))


def _button(out: Features, s: Site, body: Body, seat: float, zmax: float, clear: float) -> None:
    r_h = max(max(s.w, s.d) / 2 + clear, TOUCH_MIN_MM / 2)
    zc = body.top_at(s.x, s.y)
    cham = 0.7
    out.cuts.append(_cyl(r_h, seat - 1.0, zmax + 4, s.x, s.y))
    cone = mf.Manifold.cylinder(cham, r_h, r_h + cham, 48).translate((s.x, s.y, zc - cham))
    out.cuts.append(cone)
    out.cuts.append(_cyl(r_h + cham, zc, zmax + 4, s.x, s.y))
    rc = r_h - 0.5
    z0 = max(seat + 0.3, zc - 1.4)
    prof = [(0.0, z0), (rc, z0), (rc, zc + 0.5), *_arc((rc - 0.8, zc + 0.5), 0.8, 0, 90, 4),
            (0.0, zc + 1.3)]  # fmt: skip
    out.caps.append(_revolve(prof, s.x, s.y, 48))
    out.cutouts.append(_cut("button", s.x, s.y, zc, 2 * r_h, "circle"))


def _dpad(
    out: Features, group: list[Site], body: Body, seat: float, zmax: float, clear: float
) -> None:
    cx = sum(s.x for s in group) / len(group)
    cy = sum(s.y for s in group) / len(group)
    foot = max(max(s.w, s.d) for s in group) or 8.0
    reach = max((max(abs(s.x - cx), abs(s.y - cy)) for s in group), default=0.0)
    if len(group) > 1:  # separate buttons laid out as a cross: arms as wide as one button
        half = reach + foot / 2 + clear + 1.5
        arm = max(foot + 2 * clear, 7.5)
    else:  # one part: the cross fits its footprint, arms a third of the span
        half = max(foot / 2 + clear + 1.0, 8.0)
        arm = max(0.36 * 2 * half, 7.0)
    rot = group[0].rot
    cross = _rrect(cx, cy, 2 * half, arm, rot, 1.6) + _rrect(cx, cy, arm, 2 * half, rot, 1.6)
    zc = body.top_at(cx, cy)
    for s in group:  # the part's whole footprint is hidden under the shell, not only the cross
        if s.w and s.d:
            c = 2 * clear
            pocket = _rrect(s.x, s.y, s.w + c, s.d + c, s.rot, 1.2)
            out.cuts.append(_prism(pocket, seat - 1.0, max(s.z_hi, seat) + clear + 0.2))
    out.cuts.append(_prism(cross, seat - 1.0, zmax + 4))
    out.cuts.append(_prism(cross.offset(1.8, mf.JoinType.Round), zc - 0.7, zmax + 4))
    inner = cross.offset(-0.7, mf.JoinType.Round)
    z0 = max(seat + 0.3, zc - 1.4)
    out.caps.append(_prism(inner, z0, zc + 2.4))
    out.caps.append(_prism(inner.offset(-0.5, mf.JoinType.Round), zc + 2.3, zc + 2.9))
    out.cutouts.append(_cut("dpad", cx, cy, zc, 2 * half, "unknown"))


def _shoulder(out: Features, group: list[Site], body: Body, seat: float, clear: float) -> None:
    """A bumper: a rounded bar riding the rim where the shoulder anchors face it, over a hidden
    pocket for each part under it."""
    ang = math.radians(group[0].normal_deg)
    nx, ny = math.cos(ang), math.sin(ang)
    tx, ty = -ny, nx
    cx = sum(s.x for s in group) / len(group)
    cy = sum(s.y for s in group) / len(group)
    hit = _exit_distance(body.plan, cx, cy, nx, ny)
    if hit is None:
        return
    span = max(abs((s.x - cx) * tx + (s.y - cy) * ty) for s in group)
    half = span + max(max(s.w, s.d) for s in group) / 2 + 3.0
    r = 3.3
    px, py = cx + nx * (hit - 2.2), cy + ny * (hit - 2.2)
    zt = body.top_at(px - nx * 2.0, py - ny * 2.0)
    ends = [
        mf.Manifold.sphere(r, 28).translate((px + tx * u, py + ty * u, 0.0))
        for u in (-(half - r), half - r)
    ]
    bar = mf.Manifold.batch_hull(ends).scale((1.0, 1.0, 0.72)).translate((0, 0, zt - 0.2))
    out.caps.append(bar)
    for s in group:
        if s.w and s.d:
            c = 2 * clear
            pocket = _rrect(s.x, s.y, s.w + c, s.d + c, s.rot, 1.2)
            out.cuts.append(_prism(pocket, seat - 1.0, max(s.z_hi, seat) + clear + 0.2))
    out.cutouts.append(_cut("shoulder", px, py, zt, 2 * half, "rect", 2 * r))


def _screen(out: Features, s: Site, body: Body, seat: float, zmax: float, clear: float) -> None:
    w, d = (s.w or 30.0), (s.d or 20.0)
    zc = body.top_at(s.x, s.y)
    if s.round_window:
        rr = 0.6 * min(w, d)  # a round active area sits inside a square module: open a bit past it
        win = _rrect(s.x, s.y, 2 * rr, 2 * rr, 0.0, rr)
    else:
        win = _rrect(s.x, s.y, w, d, s.rot, 2.0)
    ledge = win.offset(2.2, mf.JoinType.Round)
    out.cuts.append(_flare(win, seat - 1.0, zmax + 4, 0.55 * (zmax + 5 - seat)))
    out.cuts.append(_prism(ledge, zc - 1.0, zmax + 4))
    lip = ledge.offset(1.4, mf.JoinType.Round) - ledge.offset(0.2, mf.JoinType.Round)
    out.adds.append(_prism(lip, zc - 1.6, zc + 0.5))
    out.glass.append(_prism(ledge.offset(-0.4, mf.JoinType.Round), zc - 1.0, zc - 0.3))
    out.cutouts.append(_cut("screen_window", s.x, s.y, zc, w, "rect", d))


def _port(
    out: Features,
    s: Site,
    body: Body,
    wall_mm: float,
    port_w: float,
    port_h: float,
    z_port: dict[str, float],
) -> None:
    ang = math.radians(s.normal_deg)
    nx, ny = math.cos(ang), math.sin(ang)
    hit = _exit_distance(body.plan, s.x, s.y, nx, ny)
    if hit is None:
        return
    lo, hi = body.land()
    zc = z_port.get(s.ref, 0.5 * (lo + hi))
    reach = hit + 1.5
    sol = mf.Manifold.extrude(_rrect(0, 0, port_h, port_w, 0.0, port_h / 2 - 0.01), reach)
    sol = sol.rotate((0, 90, 0))  # extrusion now along +X; profile x(port_h) -> z, y(port_w) -> y
    sol = sol.rotate((0, 0, s.normal_deg)).translate((s.x, s.y, zc))
    out.wall_cuts.append(sol)
    px, py = s.x + nx * hit, s.y + ny * hit
    face = _face(s.normal_deg)
    out.cutouts.append(
        {
            "cutout_id": f"cut_port_{len(out.cutouts)}",
            "feature": "usb_c",
            "face": face,
            "shape": "slot",
            "center_mm": [round(px, 3), round(py, 3), round(zc, 3)],
            "size_mm": [port_w, port_h],
        }
    )
    if s.ref:
        out.claimed.add(s.ref)
        if abs(s.normal_deg % 90) < 1e-6:
            center = [round(px, 3), round(py, 3), round(zc, 3)]
            out.ports.append({"ref": s.ref, "face": face, "center": center, "z": zc})
    out.kinds["port"] = out.kinds.get("port", 0) + 1


def _edge_button(out: Features, s: Site, body: Body, wall_mm: float, clear: float) -> None:
    ang = math.radians(s.normal_deg)
    nx, ny = math.cos(ang), math.sin(ang)
    hit = _exit_distance(body.plan, s.x, s.y, nx, ny)
    if hit is None:
        return
    lo, hi = body.land()
    zc = 0.5 * (lo + hi)
    r_c = max(max(s.w, s.d) / 2, 2.6)
    px, py = s.x + nx * hit, s.y + ny * hit
    hole = mf.Manifold.cylinder(wall_mm + 2.0, r_c + 0.5, r_c + 0.5, 32)
    out.wall_cuts.append(
        _along(hole, s.normal_deg, px - nx * (wall_mm + 1.0), py - ny * (wall_mm + 1.0), zc)
    )
    prof = [
        (0.0, -1.2),
        (r_c, -1.2),
        (r_c, 1.6),
        *_arc((r_c - 0.7, 1.6), 0.7, 0, 90, 4),
        (0.0, 2.3),
    ]
    cap = mf.Manifold.revolve(mf.CrossSection([[list(p) for p in prof]]), 32)
    out.caps.append(_along(cap, s.normal_deg, px, py, zc))
    out.cutouts.append(
        {
            "cutout_id": f"cut_edge_{len(out.cutouts)}",
            "feature": "edge_button",
            "face": _face(s.normal_deg),
            "shape": "circle",
            "center_mm": [round(px, 3), round(py, 3), round(zc, 3)],
            "size_mm": [round(2 * r_c + 1.0, 3)] * 2,
        }
    )
    out.kinds["edge_button"] = out.kinds.get("edge_button", 0) + 1


def _face(normal_deg: float) -> str:
    a = normal_deg % 360
    if a < 45 or a >= 315:
        return "pos_x"
    if a < 135:
        return "pos_y"
    if a < 225:
        return "neg_x"
    return "neg_y"


def _cut(
    feature: str, x: float, y: float, z: float, size: float, shape: str, size2: float | None = None
) -> dict[str, Any]:
    return {
        "cutout_id": f"cut_{feature}_{round(x)}_{round(y)}",
        "feature": feature,
        "face": "pos_z",
        "shape": shape,
        "center_mm": [round(x, 3), round(y, 3), round(z, 3)],
        "size_mm": [round(size, 3), round(size2 if size2 is not None else size, 3)],
    }
