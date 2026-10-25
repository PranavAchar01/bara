"""KiCad library access: footprint geometry, 3D model resolution, symbol pin names.

Every footprint and model comes from an installed KiCad library or a licenced open
KiCad-format library cloned under ~/helloworld/bara-sources/kicad-libs (see LIBRARIES).
"""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

KICAD_APP = Path(os.environ.get("BARA_KICAD_APP", "/Applications/KiCad/KiCad.app"))
KICAD_SHARE = KICAD_APP / "Contents/SharedSupport"
KICAD_PYTHON = KICAD_APP / "Contents/Frameworks/Python.framework/Versions/Current/bin/python3"
SOURCES = Path(os.environ.get("BARA_SOURCES", Path.home() / "helloworld/bara-sources"))
LIBS = SOURCES / "kicad-libs"
# Parts fetched from LCSC: easyeda2kicad writes each one's footprint, symbol and model
# under its own folder, <C number>/<C number>.kicad_mod (live/fetch.py).
FETCHED_SRC = Path(
    os.environ.get(
        "BARA_FETCHED_SRC", Path(__file__).resolve().parents[3] / "data/catalog/fetched/src"
    )
)

# Library roots: name -> (footprint dir, 3D model dirs, source url, licence, commit file or None).
LIBRARIES: dict[str, dict] = {
    "kicad": {
        "footprints": KICAD_SHARE / "footprints",
        "models": [KICAD_SHARE / "3dmodels"],
        "symbols": KICAD_SHARE / "symbols",
        "url": "https://gitlab.com/kicad/libraries",
        "licence": "CC-BY-SA-4.0 with KiCad libraries exception",
    },
    "kiswitch": {
        "footprints": LIBS / "keyswitch-kicad-library/library/footprints",
        "models": [LIBS / "keyswitch-kicad-library/library/3dmodels/3d-library.3dshapes"],
        "url": "https://github.com/kiswitch/keyswitch-kicad-library",
        "licence": "MIT OR CC-BY-SA-4.0",
        "repo": LIBS / "keyswitch-kicad-library",
    },
    "marbastlib": {
        "footprints": LIBS / "marbastlib/footprints",
        "models": [LIBS / "marbastlib/3dmodels"],
        "symbols": LIBS / "marbastlib/symbols",
        "url": "https://github.com/ebastler/marbastlib",
        "licence": "CERN-OHL-P-2.0",
        "repo": LIBS / "marbastlib",
    },
    "fingerpunch": {
        "footprints": LIBS / "fingerpunch/kicad",
        "models": [],
        "url": "https://github.com/sadekbaroudi/fingerpunch",
        "licence": "MIT",
    },
    "easyeda": {
        "footprints": None,  # one folder per part, see find_footprint
        "models": [FETCHED_SRC],
        "url": "https://www.lcsc.com",
        "licence": "LCSC/EasyEDA part library (via easyeda2kicad)",
    },
    "garden36": {
        "footprints": None,
        "models": [LIBS / "garden36/lib/3d"],
        "url": "https://github.com/shnaps/garden36",
        "licence": "MIT",
    },
}


@dataclass
class Pad:
    number: str
    kind: str  # thru_hole | smd | np_thru_hole | connect
    x: float
    y: float
    w: float
    h: float
    layers: list[str]


@dataclass
class FootprintInfo:
    lib: str
    lib_dir: Path
    name: str
    pads: list[Pad]
    courtyard: tuple[float, float, float, float]  # minx, miny, maxx, maxy (footprint frame)
    courtyard_back: tuple[float, float, float, float] | None
    models: list[str]
    descr: str = ""
    source_url: str = ""
    licence: str = ""
    cutout: tuple[float, float, float, float] | None = None  # bbox of footprint Edge.Cuts
    extra: dict = field(default_factory=dict)
    # rule areas over both copper faces that no other footprint may enter (an RF module's
    # antenna clearance), as polygons in the footprint frame
    keepouts: list[list[tuple[float, float]]] = field(default_factory=list)

    @property
    def lib_id(self) -> str:
        return f"{self.lib_dir.stem}:{self.name}"

    @property
    def size_mm(self) -> tuple[float, float]:
        x0, y0, x1, y1 = self.courtyard
        return (x1 - x0, y1 - y0)


# ---------------------------------------------------------------- s-expressions

_TOKEN = re.compile(r'\s*(\(|\)|"(?:[^"\\]|\\.)*"|[^\s()"]+)')


def parse_sexpr(text: str) -> list:
    stack: list[list] = [[]]
    for m in _TOKEN.finditer(text):
        tok = m.group(1)
        if tok == "(":
            stack.append([])
        elif tok == ")":
            done = stack.pop()
            stack[-1].append(done)
        elif tok.startswith('"'):
            stack[-1].append(tok[1:-1].replace('\\"', '"'))
        else:
            stack[-1].append(tok)
    return stack[0][0] if stack[0] else []


def _children(node: list, head: str) -> list[list]:
    return [c for c in node if isinstance(c, list) and c and c[0] == head]


def _child(node: list, head: str) -> list | None:
    found = _children(node, head)
    return found[0] if found else None


def _floats(node: list | None, n: int) -> list[float]:
    if not node:
        return [0.0] * n
    vals = [float(v) for v in node[1 : 1 + n] if _is_num(v)]
    return vals + [0.0] * (n - len(vals))


def _is_num(v: object) -> bool:
    return isinstance(v, str) and re.fullmatch(r"-?\d+(\.\d+)?(e-?\d+)?", v) is not None


def _shape_points(item: list) -> list[tuple[float, float]]:
    head = item[0]
    if head in ("fp_line", "fp_rect"):
        a = _floats(_child(item, "start"), 2)
        b = _floats(_child(item, "end"), 2)
        if head == "fp_rect":
            return [(a[0], a[1]), (b[0], b[1]), (a[0], b[1]), (b[0], a[1])]
        return [(a[0], a[1]), (b[0], b[1])]
    if head == "fp_circle":
        c = _floats(_child(item, "center"), 2)
        e = _floats(_child(item, "end"), 2)
        r = math.hypot(e[0] - c[0], e[1] - c[1])
        return [(c[0] - r, c[1] - r), (c[0] + r, c[1] + r)]
    if head == "fp_arc":
        return [tuple(_floats(_child(item, k), 2)) for k in ("start", "mid", "end")]  # type: ignore[misc]
    if head == "fp_poly":
        pts = _child(item, "pts") or []
        return [tuple(_floats(p, 2)) for p in _children(pts, "xy")]  # type: ignore[misc]
    return []


def _edges_close(items: list[list]) -> bool:
    """True when a footprint's Edge.Cuts shapes close: every line and arc end meets another.

    A connector drawn to sit in the board edge (a 3.5 mm jack's notch) ships an open
    chain meant to splice into the outline; it is no cutout, and on our own outline it
    leaves Edge.Cuts that never close."""
    ends: dict[tuple[int, int], int] = {}
    for item in items:
        if item[0] not in ("fp_line", "fp_arc"):
            continue
        for key in ("start", "end"):
            x, y = _floats(_child(item, key), 2)
            k = (round(x * 100), round(y * 100))
            ends[k] = ends.get(k, 0) + 1
    return all(n % 2 == 0 for n in ends.values())


def _bbox(points: list[tuple[float, float]]) -> tuple[float, float, float, float] | None:
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _layer_of(item: list) -> str:
    node = _child(item, "layer")
    return str(node[1]) if node and len(node) > 1 else ""


@lru_cache(maxsize=256)
def load_footprint(lib: str, pretty: str, name: str) -> FootprintInfo:
    meta = LIBRARIES[lib]
    lib_dir = (
        FETCHED_SRC / name if lib == "easyeda" else Path(meta["footprints"]) / f"{pretty}.pretty"
    )
    path = lib_dir / f"{name}.kicad_mod"
    tree = parse_sexpr(path.read_text())
    pads: list[Pad] = []
    for p in _children(tree, "pad"):
        at = _floats(_child(p, "at"), 3)
        size = _floats(_child(p, "size"), 2)
        layers_node = _child(p, "layers") or ["layers"]
        rot = at[2]
        w, h = size
        if abs(round(rot / 90) % 2) == 1:
            w, h = h, w
        pads.append(
            Pad(str(p[1]), str(p[2]), at[0], at[1], w, h, [str(v) for v in layers_node[1:]])
        )
    crt_f: list[tuple[float, float]] = []
    crt_b: list[tuple[float, float]] = []
    fab: list[tuple[float, float]] = []
    cuts: list[tuple[float, float]] = []
    cut_items: list[list] = []
    for item in tree:
        if not isinstance(item, list) or not item or not str(item[0]).startswith("fp_"):
            continue
        layer = _layer_of(item)
        pts = _shape_points(item)
        if layer == "F.CrtYd":
            crt_f += pts
        elif layer == "B.CrtYd":
            crt_b += pts
        elif layer == "F.Fab":
            fab += pts
        elif layer == "Edge.Cuts":
            cuts += pts
            cut_items.append(item)
    pad_pts = [(p.x - p.w / 2, p.y - p.h / 2) for p in pads] + [
        (p.x + p.w / 2, p.y + p.h / 2) for p in pads
    ]
    court = _bbox(crt_f) or _bbox(fab) or _bbox(pad_pts) or (-1.0, -1.0, 1.0, 1.0)
    models = [str(m[1]) for m in _children(tree, "model")]
    xforms: dict[str, dict[str, list[float]]] = {}
    for m in _children(tree, "model"):
        xf: dict[str, list[float]] = {}
        for key in ("offset", "rotate", "scale"):
            node = _child(m, key)
            xyz = _child(node, "xyz") if node else None
            if xyz:
                xf[key] = _floats(xyz, 3)
        xforms[str(m[1])] = xf
    step = sorted(lib_dir.glob(f"{name}.st*p")) if lib == "easyeda" else []
    if step and models:  # fetch.py keeps the part's model beside it as <C number>.step
        xforms[str(step[0])] = xforms.get(models[0], {})
        models = [str(step[0])]
    descr_node = _child(tree, "descr")
    keepouts = []
    for z in _children(tree, "zone"):
        rule = _child(z, "keepout")
        layers = set((_child(z, "layers") or [])[1:]) | {str((_child(z, "layer") or ["", ""])[1])}
        # only an area over both faces matters to placement: the courtyard covers its own face
        both = {"F.Cu", "B.Cu"} <= layers or bool(layers & {"*.Cu", "F&B.Cu"})
        if rule is None or ["footprints", "not_allowed"] not in rule or not both:
            continue
        pts = _child(_child(z, "polygon") or [], "pts") or []
        ring = [(xy[0], xy[1]) for xy in (_floats(n, 2) for n in _children(pts, "xy"))]
        if len(ring) >= 3:
            keepouts.append(ring)
    return FootprintInfo(
        lib=lib,
        lib_dir=lib_dir,
        name=name,
        pads=pads,
        courtyard=court,
        courtyard_back=_bbox(crt_b),
        models=models,
        descr=str(descr_node[1]) if descr_node else "",
        source_url=str(meta["url"]),
        licence=str(meta["licence"]),
        cutout=_bbox(cuts) if _edges_close(cut_items) else None,
        extra={"model_xforms": xforms},
        keepouts=keepouts,
    )


def footprint_ref(ref: str) -> FootprintInfo:
    """'lib/Pretty:Name' -> FootprintInfo, e.g. 'kicad/Diode_SMD:D_SOD-123'."""
    lib, rest = ref.split("/", 1)
    pretty, name = rest.split(":", 1)
    return load_footprint(lib, pretty, name)


def find_footprint(lib_id: str) -> FootprintInfo | None:
    """Resolve a plain KiCad lib id 'Pretty:Name' against every known library."""
    if ":" not in lib_id:
        return None
    pretty, name = lib_id.split(":", 1)
    if pretty == "easyeda":
        found = (FETCHED_SRC / name / f"{name}.kicad_mod").exists()
        return load_footprint("easyeda", pretty, name) if found else None
    for lib, meta in LIBRARIES.items():
        root = meta.get("footprints")
        if root and (Path(root) / f"{pretty}.pretty" / f"{name}.kicad_mod").exists():
            return load_footprint(lib, pretty, name)
    return None


# ---------------------------------------------------------------- 3D models


@lru_cache(maxsize=512)
def resolve_model(model_ref: str, prefer: str = "") -> Path | None:
    """Map a footprint's model reference (with ${VARS}) to a file on disk.

    Matches by file stem across all library model roots; STEP preferred over WRL so
    kicad-cli exports the exact solid.
    """
    stem = Path(model_ref.replace("\\", "/")).stem
    roots: list[Path] = []
    if prefer and prefer in LIBRARIES:
        roots += [Path(r) for r in LIBRARIES[prefer]["models"]]
    for meta in LIBRARIES.values():
        roots += [Path(r) for r in meta["models"]]
    sub = Path(model_ref.replace("\\", "/")).parent.name  # e.g. Diode_SMD.3dshapes
    for ext in (".step", ".stp", ".STEP", ".wrl"):
        for root in roots:
            for cand in (root / sub / f"{stem}{ext}", root / f"{stem}{ext}"):
                if cand.exists():
                    return cand
    return None


# ---------------------------------------------------------------- symbols


@lru_cache(maxsize=64)
@lru_cache(maxsize=256)
def library_symbol(lib: str, footprint: str) -> tuple[str, str, str] | None:
    """The symbol a footprint's own library ships for it: the longest symbol name that starts
    the footprint name (SuperMini_nRF52840 for SuperMini_nRF52840_H_USBup)."""
    sym_dir = LIBRARIES.get(lib, {}).get("symbols")
    if not sym_dir or not Path(sym_dir).is_dir():
        return None
    best: tuple[str, str, str] | None = None
    for path in sorted(Path(sym_dir).glob("*.kicad_sym")):
        for name in re.findall(r'^\s*\(symbol "([^"]+)"', path.read_text(), re.M):
            if len(name) >= 6 and footprint.lower().startswith(name.lower()):
                if best is None or len(name) > len(best[2]):
                    best = (lib, path.name, name)
    return best


def symbol_pins(lib: str, sym_file: str, symbol: str) -> dict[str, str]:
    """Pin number -> pin name from a .kicad_sym symbol (incl. its sub-units)."""
    path = Path(LIBRARIES[lib]["symbols"]) / sym_file
    tree = parse_sexpr(path.read_text())
    out: dict[str, str] = {}
    for sym in _children(tree, "symbol"):
        if sym[1] != symbol:
            continue
        stack = [sym]
        while stack:
            node = stack.pop()
            for c in node:
                if isinstance(c, list) and c:
                    if c[0] == "pin":
                        name = _child(c, "name")
                        num = _child(c, "number")
                        if name and num:
                            out[str(num[1])] = str(name[1])
                    elif c[0] == "symbol":
                        stack.append(c)
    return out


def repo_commit(lib: str) -> str | None:
    meta = LIBRARIES.get(lib, {})
    repo = meta.get("repo")
    if repo:
        head = Path(repo) / ".git/HEAD"
        if head.exists():
            ref = head.read_text().strip()
            if ref.startswith("ref:"):
                target = Path(repo) / ".git" / ref.split(" ", 1)[1]
                if target.exists():
                    return target.read_text().strip()
                packed = Path(repo) / ".git/packed-refs"
                if packed.exists():
                    for line in packed.read_text().splitlines():
                        if line.endswith(ref.split(" ", 1)[1]):
                            return line.split(" ")[0]
            return ref
    commit = LIBS / lib / "COMMIT"
    return commit.read_text().strip() if commit.exists() else None
