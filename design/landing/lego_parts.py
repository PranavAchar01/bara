"""Partial keyboard assemblies for manual steps (same geometry as iso.keyboard, flat, no explode)."""
from iso import box, frame, P

INK = "#161616"
CASE = ("#5b5f66", "#3f4248", "#30333a")
PCB = ("#e9ecef", "#d5d9dd", "#c6cbd0")
W, D = 290, 100


def tray(k, ox, oy, z=0):
    return box(0, 0, z, W, D, 4, k, ox, oy, *CASE, INK) + frame(0, 0, z + 4, W, D, 10, 4, k, ox, oy, CASE, INK)


def pcb(k, ox, oy, z=6):
    return box(6, 6, z, W - 12, D - 12, 2, k, ox, oy, *PCB, INK) + box(W - 40, 8, z + 2, 18, 32, 4, k, ox, oy, "#2d2f33", "#1d1f22", "#141517", INK)


def grid(cols=14, rows=5):
    pitch = (W - 20) / cols
    rh = (D - 20) / rows
    for r in range(rows):
        for c in range(cols):
            yield c, r, 10 + c * pitch, 10 + r * rh, pitch, rh


def switches(k, ox, oy, z=8, only=None, lift=0):
    out = []
    for c, r, x, y, pw, rh in grid():
        if only and not only(c, r):
            continue
        zz = z + lift
        out.append((x + y, box(x + pw * 0.2, y + rh * 0.2, zz, pw * 0.6, rh * 0.6, 5, k, ox, oy, "#ffffff", "#e9e9e7", "#d9d9d6", INK, 0.7)
                    + box(x + pw * 0.38, y + rh * 0.38, zz + 5, pw * 0.24, rh * 0.24, 2, k, ox, oy, "#b98a5a", "#a07448", "#8a643d", INK, 0.5)))
    return "".join(s for _, s in sorted(out))


def caps(k, ox, oy, z=15, only=None, lift=0, color=("#ffffff", "#f1f1f0", "#e4e4e2")):
    out = []
    for c, r, x, y, pw, rh in grid():
        if only and not only(c, r):
            continue
        out.append((x + y, box(x + 1, y + 1, z + lift, pw - 2, rh - 2, 6, k, ox, oy, *color, INK, 0.7)))
    return "".join(s for _, s in sorted(out))


def top(k, ox, oy, z=21):
    return frame(0, 0, z, W, D, 5, 8, k, ox, oy, CASE, INK)


def arrow_down(x, y, length=60, w=16, color="#ffffff"):
    """A manual-style fat arrow pointing down: white fill, dark outline."""
    h = length
    pts = f"{x-w/2},{y} {x+w/2},{y} {x+w/2},{y+h-18} {x+w},{y+h-18} {x},{y+h} {x-w},{y+h-18} {x-w/2},{y+h-18}"
    return f'<polygon points="{pts}" fill="{color}" stroke="{INK}" stroke-width="2" stroke-linejoin="round"/>'
