"""Isometric line drawings of a keyboard build, as SVG strings, for the landing concepts."""
import math

C, S = math.cos(math.radians(30)), math.sin(math.radians(30))


def P(x, y, z, k, ox, oy):
    return (ox + (x - y) * C * k, oy + (x + y) * S * k - z * k)


def box(x, y, z, w, d, h, k, ox, oy, top, left, right, stroke, sw=1.0):
    p = lambda a, b, c: P(a, b, c, k, ox, oy)
    t = [p(x, y, z + h), p(x + w, y, z + h), p(x + w, y + d, z + h), p(x, y + d, z + h)]
    r = [p(x + w, y, z), p(x + w, y + d, z), p(x + w, y + d, z + h), p(x + w, y, z + h)]
    l = [p(x, y + d, z), p(x + w, y + d, z), p(x + w, y + d, z + h), p(x, y + d, z + h)]
    f = lambda pts: " ".join(f"{a:.1f},{b:.1f}" for a, b in pts)
    out = ""
    for pts, fill in ((r, right), (l, left), (t, top)):
        out += f'<polygon points="{f(pts)}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" stroke-linejoin="round"/>'
    return out


def frame(x, y, z, w, d, h, wall, k, ox, oy, cols, stroke, sw=1.0):
    """A rectangular ring (case top / tray rim) as four boxes."""
    top, left, right = cols
    parts = [
        (x, y, w, wall), (x, y + d - wall, w, wall),
        (x, y + wall, wall, d - 2 * wall), (x + w - wall, y + wall, wall, d - 2 * wall),
    ]
    parts.sort(key=lambda b: b[0] + b[1])
    return "".join(box(a, b, z, c, e, h, k, ox, oy, top, left, right, stroke, sw) for a, b, c, e in parts)


def keyboard(k=1.0, ox=0, oy=0, gap=34, accent=None, stroke="#161616", sw=0.9, style="line", keys=(14, 5)):
    """Exploded 60% keyboard. Returns (svg_body, anchors) where anchors name a point on each layer."""
    W, D = 290, 100
    if style == "line":
        paper, side1, side2 = "#ffffff", "#f1f1f0", "#e4e4e2"
        case = ("#5b5f66", "#3f4248", "#30333a")
        pcb = ("#e9ecef", "#d5d9dd", "#c6cbd0")
    else:
        paper, side1, side2 = "#ffffff", "#ececea", "#dcdcd9"
        case = ("#4a4e55", "#36393f", "#2b2e33")
        pcb = ("#dfe7e1", "#c7d1c9", "#b7c2ba")
    out, anchors = "", {}
    z = 0
    # case bottom tray
    out += box(0, 0, z, W, D, 4, k, ox, oy, *case, stroke, sw)
    out += frame(0, 0, z + 4, W, D, 8, 4, k, ox, oy, case, stroke, sw)
    anchors["case"] = P(W, D * 0.5, z + 6, k, ox, oy)
    z += gap * 1.2
    # pcb
    out += box(6, 6, z, W - 12, D - 12, 2, k, ox, oy, *pcb, stroke, sw)
    out += box(W - 40, 8, z + 2, 18, 32, 4, k, ox, oy, "#2d2f33", "#1d1f22", "#141517", stroke, sw)  # mcu
    anchors["pcb"] = P(W - 6, D * 0.55, z + 1, k, ox, oy)
    anchors["mcu"] = P(W - 31, 24, z + 6, k, ox, oy)
    z += gap
    # switches
    cols, rows = keys
    pitch = (W - 20) / cols
    sws = []
    for r in range(rows):
        for c in range(cols):
            sws.append((10 + c * pitch + pitch * 0.2, 10 + r * (D - 20) / rows + 3, pitch * 0.6, (D - 20) / rows * 0.6))
    sws.sort(key=lambda b: b[0] + b[1])
    sc = ("#ffffff", "#e9e9e7", "#d9d9d6") if not accent else ("#ffffff", "#e9e9e7", "#d9d9d6")
    for a, b, c, e in sws:
        out += box(a, b, z, c, e, 5, k, ox, oy, *sc, stroke, sw * 0.8)
        out += box(a + c * 0.3, b + e * 0.3, z + 5, c * 0.4, e * 0.4, 2, k, ox, oy, accent or "#b98a5a", accent or "#a07448", accent or "#8a643d", stroke, sw * 0.6)
    anchors["switches"] = P(W - 10, D - 12, z + 4, k, ox, oy)
    z += gap
    # keycaps
    caps = []
    for r in range(rows):
        for c in range(cols):
            caps.append((10 + c * pitch + 1, 10 + r * (D - 20) / rows + 1, pitch - 2, (D - 20) / rows - 2))
    caps.sort(key=lambda b: b[0] + b[1])
    for a, b, c, e in caps:
        out += box(a, b, z, c, e, 6, k, ox, oy, paper, side1, side2, stroke, sw * 0.8)
    anchors["keycaps"] = P(W - 10, D - 12, z + 4, k, ox, oy)
    z += gap * 1.1
    # case top
    out += frame(0, 0, z, W, D, 5, 8, k, ox, oy, case, stroke, sw)
    anchors["top"] = P(W, D * 0.5, z + 3, k, ox, oy)
    return out, anchors


def part(kind, k=1.0, ox=0, oy=0, stroke="#161616", sw=1.0):
    """Single small parts for inventories."""
    if kind == "switch":
        return box(0, 0, 0, 14, 14, 9, k, ox, oy, "#fff", "#eee", "#ddd", stroke, sw) + box(4.5, 4.5, 9, 5, 5, 4, k, ox, oy, "#b98a5a", "#a07448", "#8a643d", stroke, sw * 0.8)
    if kind == "keycap":
        return box(0, 0, 0, 18, 18, 9, k, ox, oy, "#fff", "#f1f1f0", "#e4e4e2", stroke, sw)
    if kind == "mcu":
        return box(0, 0, 0, 18, 33, 3, k, ox, oy, "#2d2f33", "#1d1f22", "#141517", stroke, sw) + box(5, 0, 3, 8, 6, 3, k, ox, oy, "#c9ccd1", "#b0b4ba", "#9da2a9", stroke, sw * 0.8)
    if kind == "pcb":
        return box(0, 0, 0, 70, 26, 2, k, ox, oy, "#e9ecef", "#d5d9dd", "#c6cbd0", stroke, sw)
    if kind == "case":
        return box(0, 0, 0, 70, 26, 3, k, ox, oy, "#5b5f66", "#3f4248", "#30333a", stroke, sw) + frame(0, 0, 3, 70, 26, 6, 2.5, k, ox, oy, ("#5b5f66", "#3f4248", "#30333a"), stroke, sw)
    if kind == "oled":
        return box(0, 0, 0, 38, 12, 3, k, ox, oy, "#2d2f33", "#1d1f22", "#141517", stroke, sw) + box(3, 2, 3, 28, 8, 0.5, k, ox, oy, "#0a6cff", "#0a6cff", "#0a6cff", stroke, sw * 0.6)
    if kind == "stab":
        return box(0, 0, 0, 40, 4, 4, k, ox, oy, "#fff", "#eee", "#ddd", stroke, sw) + box(0, -2, 0, 6, 8, 8, k, ox, oy, "#fff", "#eee", "#ddd", stroke, sw) + box(34, -2, 0, 6, 8, 8, k, ox, oy, "#fff", "#eee", "#ddd", stroke, sw)
    raise ValueError(kind)


def svg(body, w, h, extra=""):
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">{body}{extra}</svg>'


def fitted(body, w, h, pad=6):
    """Wraps drawn polygons so they fill a w×h box (scaled and centred), whatever their coordinates."""
    import re
    nums = [float(n) for pts in re.findall(r'points="([^"]+)"', body) for n in re.split(r"[ ,]+", pts.strip()) if n]
    xs, ys = nums[0::2], nums[1::2]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    s = min((w - 2 * pad) / max(x1 - x0, 1), (h - 2 * pad) / max(y1 - y0, 1))
    tx = (w - (x1 - x0) * s) / 2 - x0 * s
    ty = (h - (y1 - y0) * s) / 2 - y0 * s
    return svg(f'<g transform="translate({tx:.1f},{ty:.1f}) scale({s:.3f})">{body}</g>', w, h)
