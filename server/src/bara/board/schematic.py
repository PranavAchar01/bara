"""A readable KiCad schematic of a planned board, written from the same pad-to-net map the
board is routed from.

Every part takes the symbol its own library ships (the .kicad_sym fetched beside an LCSC
footprint, the symbol of the footprint's KiCad library, or the stock KiCad symbol of its
reference-designator class), checked against the pads it wires; only a part with none of
those gets a plain pin box. Parts are grouped into one framed block per function, power
nets end in power symbols, every other wired pin carries a net label, unwired pins a
no-connect flag, and the sheet has a title block. kicad-cli exports the SVG and PDF, and
the schematic's own netlist is compared with the board's so the drawing never disagrees
with the copper.
"""

from __future__ import annotations

import datetime as dt
import re
import subprocess
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from bara.board.layout import Item
from bara.board.libs import KICAD_SHARE, LIBRARIES

STOCK = KICAD_SHARE / "symbols"
GRID = 1.27
FONT = 1.27
CHAR_MM = 1.0  # rough width of one label character at FONT
PAGES = [("A4", 297.0, 210.0), ("A3", 420.0, 297.0), ("A2", 594.0, 420.0), ("A1", 841.0, 594.0)]
MARGIN = 15.0
TITLE_H = 40.0  # the title block's strip along the bottom
BLOCK_PAD = 6.0
BLOCK_GAP = 8.0
BLOCK_MAX_W = 200.0

# Stock symbols by reference-designator class (IEEE 315 letters, not device kinds); each is
# used only when its pin numbers cover the pads the part wires.
BY_PREFIX: dict[str, list[tuple[str, str]]] = {
    "R": [("Device", "R")],
    "C": [("Device", "C")],
    "L": [("Device", "L")],
    "D": [("Device", "LED"), ("Device", "D")],
    "SW": [("Switch", "SW_Push"), ("Switch", "SW_SPST")],
    "BT": [("Device", "Battery_Cell")],
    "Y": [("Device", "Crystal")],
    "F": [("Device", "Fuse")],
    "LS": [("Device", "Speaker")],
    "BZ": [("Device", "Buzzer")],
}
# canonical power nets (generic.power_net) -> stock power symbol and its drawn direction
POWER = {"GND": ("GND", 270), "3V3": ("+3V3", 90), "VBUS": ("VBUS", 90), "VBAT": ("+BATT", 90)}
KEEP_PROPS = {'"Reference"', '"Value"', '"Footprint"'}


# ---------------------------------------------------------------- raw s-expressions

_TOKEN = re.compile(r'\s*(\(|\)|"(?:[^"\\]|\\.)*"|[^\s()"]+)')
Node = list  # a list of raw tokens (quoted strings keep their quotes) and sub-lists


def _parse(text: str) -> Node:
    stack: list[Node] = [[]]
    for m in _TOKEN.finditer(text):
        tok = m.group(1)
        if tok == "(":
            stack.append([])
        elif tok == ")":
            done = stack.pop()
            stack[-1].append(done)
        else:
            stack[-1].append(tok)
    return stack[0][0]


def _emit(node: Node | str) -> str:
    if isinstance(node, str):
        return node
    return "(" + " ".join(_emit(c) for c in node) + ")"


def _q(text: str) -> str:
    return '"' + str(text).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _uq(tok: str) -> str:
    return tok[1:-1].replace('\\"', '"') if tok.startswith('"') else tok


def _kids(node: Node, head: str) -> list[Node]:
    return [c for c in node if isinstance(c, list) and c and c[0] == head]


def _kid(node: Node, head: str) -> Node | None:
    found = _kids(node, head)
    return found[0] if found else None


@lru_cache(maxsize=32)
@lru_cache(maxsize=16)
def _text(path: Path) -> str:
    return path.read_text(errors="replace")


def _top_names(path: Path) -> list[str]:
    """Symbol names at the library's top level (sub-units sit one level deeper)."""
    return re.findall(r'^\s{1,2}\(symbol "([^"]+)"', _text(path), re.M)


@lru_cache(maxsize=256)
def _named(path: Path, name: str) -> Node | None:
    """One symbol cut out of a library by balanced parentheses: the stock libraries run to
    megabytes, so they are never parsed whole."""
    text = _text(path)
    m = re.search(r"^\s{1,2}\(symbol " + re.escape(_q(name)) + r"\s", text, re.M)
    if m is None:
        return None
    start = text.index("(", m.start())
    depth, i, in_str = 0, start, False
    while i < len(text):
        ch = text[i]
        if in_str:
            if ch == "\\":
                i += 1
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return _parse(text[start : i + 1])
        i += 1
    return None


# ---------------------------------------------------------------- symbols


@dataclass
class Pin:
    number: str
    x: float  # connection point, library frame (y up)
    y: float
    angle: int  # direction from the connection point into the body
    unit: int
    kind: str = ""  # electrical type, e.g. power_out


@dataclass
class Symbol:
    lib_id: str
    node: Node | None  # the embedded definition (None: a power symbol shares one)
    pins: list[Pin]
    units: list[int]
    bbox: dict[int, tuple[float, float, float, float]] = field(default_factory=dict)
    source: str = ""


def _unit_of(name: str, base: str) -> tuple[int, int]:
    m = re.fullmatch(re.escape(base) + r"_(\d+)_(\d+)", name)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 1)


def _points(node: Node) -> list[tuple[float, float]]:
    out = []
    for c in node:
        if isinstance(c, list) and c:
            if c[0] in ("start", "end", "center", "xy", "mid") and len(c) >= 3:
                try:
                    out.append((float(c[1]), float(c[2])))
                except ValueError:
                    pass
            else:
                out += _points(c)
    return out


def _flatten(node: Node, path: Path) -> Node | None:
    """A derived symbol (extends) drawn with its parent's body and its own fields."""
    ext = _kid(node, "extends")
    if ext is None:
        return node
    parent = _named(path, _uq(ext[1]))
    if parent is None or _kid(parent, "extends") is not None:
        return None
    pbase, base = _uq(parent[1]), _uq(node[1])
    own = [c for c in node[2:] if isinstance(c, list) and c and c[0] == "property"]
    names = {c[1] for c in own}
    out: Node = ["symbol", node[1]]
    for c in parent[2:]:
        if isinstance(c, list) and c and c[0] == "property" and c[1] in names:
            continue
        if isinstance(c, list) and c and c[0] == "symbol":
            c = ["symbol", _q(base + _uq(c[1])[len(pbase) :]), *c[2:]]
        out.append(c)
    return out[:2] + own + out[2:]


def _symbol_from(node: Node, lib: str, source: str) -> Symbol | None:
    base = _uq(node[1])
    pins: list[Pin] = []
    shapes: dict[int, list[tuple[float, float]]] = {}
    units: set[int] = set()
    for sub in [node, *_kids(node, "symbol")]:
        unit, style = _unit_of(_uq(sub[1]), base) if sub is not node else (0, 1)
        if style not in (0, 1):
            continue  # the alternate (De Morgan) body; style 0 is shared by both
        if unit:
            units.add(unit)
        for c in sub:
            if not (isinstance(c, list) and c):
                continue
            if c[0] == "pin":
                at, num = _kid(c, "at"), _kid(c, "number")
                if at is None or num is None:
                    continue
                pins.append(
                    Pin(
                        _uq(num[1]),
                        float(at[1]),
                        float(at[2]),
                        int(float(at[3]) if len(at) > 3 else 0),
                        unit,
                        c[1] if len(c) > 1 and isinstance(c[1], str) else "",
                    )
                )
                shapes.setdefault(unit, []).append((float(at[1]), float(at[2])))
            elif c[0] in ("rectangle", "polyline", "circle", "arc", "text"):
                shapes.setdefault(unit, []).extend(_points(c))
    if not pins:
        return None
    unit_list = sorted(units) or [1]
    sym = Symbol("", None, pins, unit_list, source=source)
    common = shapes.get(0, [])
    for u in unit_list:
        pts = shapes.get(u, []) + common
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        sym.bbox[u] = (min(xs), min(ys), max(xs), max(ys))
    name = f"{lib}:{base}"
    sym.lib_id = name
    embedded: Node = ["symbol", _q(name)]
    for c in node[2:]:
        if isinstance(c, list) and c and c[0] == "property" and c[1] not in KEEP_PROPS:
            continue  # vendor and datasheet fields stay out of the drawing
        embedded.append(c)
    sym.node = embedded
    return sym


def _covers(sym: Symbol, wired: set[str]) -> bool:
    return wired <= {p.number for p in sym.pins}


@lru_cache(maxsize=8)
def _symbol_index(lib: str) -> tuple[tuple[str, Path], ...]:
    sym_dir = LIBRARIES.get(lib, {}).get("symbols")
    if not sym_dir or not Path(sym_dir).is_dir():
        return ()
    return tuple(
        (name, path)
        for path in sorted(Path(sym_dir).glob("*.kicad_sym"))
        for name in _top_names(path)
    )


def _library_symbol(lib: str, footprint: str) -> tuple[Path, str] | None:
    """libs.library_symbol over a cached index: the longest symbol name that starts the
    footprint name (or does past a vendor prefix), at least six characters."""
    best: tuple[int, Path, str] | None = None
    low = footprint.lower()
    for name, path in _symbol_index(lib):
        stems = [name, *name.split("_", 1)[1:]]
        hit = max((len(t) for t in stems if low.startswith(t.lower())), default=0)
        if hit >= 6 and (best is None or hit > best[0]):
            best = (hit, path, name)
    return (best[1], best[2]) if best else None


def _candidates(it: Item) -> list[tuple[Path, str | None, str]]:
    """(library file, symbol name or None for any, nickname) in order of preference."""
    out: list[tuple[Path, str | None, str]] = []
    fp = it.fp
    if fp is not None:
        for path in sorted(Path(fp.lib_dir).glob("*.kicad_sym")):  # fetched beside the footprint
            out.append((path, None, Path(fp.lib_dir).stem))
        named = str(it.meta.get("symbol") or "")
        if ":" in named:  # the catalog record's own KiCad symbol
            lib, name = named.split(":", 1)
            out.append((STOCK / f"{lib}.kicad_sym", name, lib))
        own = _library_symbol(fp.lib, fp.name)
        if own is not None:
            out.append((own[0], own[1], own[0].stem))
    prefix = re.match(r"[A-Z]+", it.ref)
    for lib, name in BY_PREFIX.get(prefix.group(0) if prefix else "", []):
        out.append((STOCK / f"{lib}.kicad_sym", name, lib))
    wired = [p for p in it.pads if p]
    if prefix and prefix.group(0) == "J" and wired:
        n = max(len(it.fp.pads) if it.fp else 0, len(wired))
        out.append((STOCK / "Connector_Generic.kicad_sym", f"Conn_01x{n:02d}", "Connector_Generic"))
    return out


def _box(it: Item) -> Symbol:
    """A pin box for a part no library ships a symbol for: one pin per pad, named by pin."""
    pads = sorted(
        {p.number for p in (it.fp.pads if it.fp else []) if p.number} | set(it.pads), key=_natural
    )
    names = it.meta.get("pins") or {}
    label = {n: str(names.get(n) or it.pads.get(n) or n) for n in pads}
    left, right = pads[: (len(pads) + 1) // 2], pads[(len(pads) + 1) // 2 :]
    half = max(len(left), len(right), 1)
    w = max(
        10.16,
        round((max((len(v) for v in label.values()), default=2) * 2 * CHAR_MM + 5.08) / 2.54)
        * 2.54,
    )
    top = (half - 1) * 2.54 / 2
    top = round(top / GRID) * GRID
    base = f"BOX_{re.sub(r'[^A-Za-z0-9]', '_', it.ref)}"
    body: Node = ["symbol", _q(f"{base}_1_1")]
    body.append(
        [
            "rectangle",
            ["start", f"{-w / 2:.2f}", f"{top + 2.54:.2f}"],
            ["end", f"{w / 2:.2f}", f"{top - half * 2.54:.2f}"],
            ["stroke", ["width", "0.254"], ["type", "default"]],
            ["fill", ["type", "background"]],
        ]
    )
    pins: list[Pin] = []
    for side, group in ((-1, left), (1, right)):
        for i, num in enumerate(group):
            x, y = side * (w / 2 + 2.54), top - i * 2.54
            angle = 0 if side < 0 else 180
            pins.append(Pin(num, x, y, angle, 1))
            body.append(
                [
                    "pin",
                    "passive",
                    "line",
                    ["at", f"{x:.2f}", f"{y:.2f}", str(angle)],
                    ["length", "2.54"],
                    ["name", _q(label[num]), ["effects", ["font", ["size", "1.27", "1.27"]]]],
                    ["number", _q(num), ["effects", ["font", ["size", "1.27", "1.27"]]]],
                ]
            )
    node: Node = [
        "symbol",
        _q(f"board_parts:{base}"),
        ["exclude_from_sim", "no"],
        ["in_bom", "yes"],
        ["on_board", "yes"],
    ]
    for key, val, y in (("Reference", "U", top + 5.08), ("Value", base, top - half * 2.54 - 2.54)):
        node.append(
            [
                "property",
                _q(key),
                _q(val),
                ["at", "0", f"{y:.2f}", "0"],
                ["effects", ["font", ["size", "1.27", "1.27"]]],
            ]
        )
    node.append(body)
    sym = Symbol(f"board_parts:{base}", node, pins, [1], source="pin box")
    sym.bbox[1] = (-w / 2 - 2.54, top - half * 2.54, w / 2 + 2.54, top + 2.54)
    return sym


def _natural(s: str) -> tuple:
    # Tagged so pin "1" and pin "A1" compare (digit runs before text) instead of raising.
    return tuple((0, int(t), "") if t.isdigit() else (1, 0, t) for t in re.findall(r"\d+|\D+", s))


def symbol_for(it: Item) -> Symbol:
    wired = {p for p, net in it.pads.items() if net}
    for path, name, nick in _candidates(it):
        if not path.exists():
            continue
        for sname in [name] if name else _top_names(path):
            node = _named(path, sname)
            node = _flatten(node, path) if node is not None else None
            if node is None:
                continue
            sym = _symbol_from(node, nick, str(path.name))
            if sym is not None and _covers(sym, wired):
                return sym
    return _box(it)


@lru_cache(maxsize=8)
def _power_symbol(name: str) -> Symbol:
    sym = _symbol_from(_named(STOCK / "power.kicad_sym", name), "power", "power.kicad_sym")
    assert sym is not None
    return sym


# ---------------------------------------------------------------- layout


def _snap(v: float) -> float:
    return round(v / GRID) * GRID


def _outward(angle: int) -> int:
    return (angle + 180) % 360


def _block_of(it: Item, by_id: dict[int, str]) -> str:
    host = it.meta.get("near")
    if isinstance(host, Item):
        return by_id.get(id(host)) or _block_of(host, by_id)
    return str(it.meta.get("slot_id") or it.role or "other")


def _title(key: str) -> str:
    return re.sub(r"[_\-.]+", " ", key).strip().capitalize() or "Other"


@dataclass
class Cell:
    it: Item
    sym: Symbol
    unit: int
    w: float
    h: float
    ox: float  # unit origin inside the cell
    oy: float


def _cell(it: Item, sym: Symbol, unit: int) -> Cell:
    x0, y0, x1, y1 = sym.bbox[unit]
    ext = {0: 0.0, 90: 0.0, 180: 0.0, 270: 0.0}
    for p in sym.pins:
        if p.unit not in (0, unit):
            continue
        net = it.pads.get(p.number) or ""
        d = _outward(p.angle)
        if net in POWER:
            need = 9.0 if d in (0, 180) else 6.0
        else:
            need = len(net) * CHAR_MM + 2.0 if net else 2.0
        ext[d] = max(ext[d], need)
    left, right = ext[180] + 2, ext[0] + 2
    top, bottom = ext[90] + 5, ext[270] + 5  # reference above, value below
    w = (x1 - x0) + left + right
    text = max(len(it.label or ""), len(it.ref)) * CHAR_MM + 2  # value centred under the body
    if text > w:
        left, w = left + (text - w) / 2, text
    h = (y1 - y0) + top + bottom
    return Cell(it, sym, unit, w, h, left - x0, top + y1)


def _pack(
    sizes: list[tuple[float, float]], width: float, gap: float
) -> tuple[list[tuple[float, float]], float, float]:
    """Shelf-pack boxes left to right into rows of the given width."""
    out, x, y, row, used = [], 0.0, 0.0, 0.0, 0.0
    for w, h in sizes:
        if x > 0 and x + w > width:
            x, y, row = 0.0, y + row + gap, 0.0
        out.append((x, y))
        x += w + gap
        row = max(row, h)
        used = max(used, x - gap)
    return out, used, y + row


# ---------------------------------------------------------------- writer


@dataclass
class Sheet:
    text: str
    page: str
    symbols: dict[str, str]  # ref -> symbol source
    blocks: list[str]


def write(items: list[Item], path: Path, *, title: str, project: str = "main") -> Sheet:
    parts = [it for it in items if it.on_pcb and it.fp is not None]
    by_id: dict[int, str] = {}
    for it in parts:
        if not isinstance(it.meta.get("near"), Item):
            by_id[id(it)] = _block_of(it, by_id)
    groups: dict[str, list[Cell]] = {}
    syms: dict[str, Symbol] = {}
    for it in parts:
        sym = symbol_for(it)
        syms[it.ref] = sym
        key = _block_of(it, by_id)
        for u in sym.units:
            groups.setdefault(key, []).append(_cell(it, sym, u))

    def rank(key: str) -> tuple:
        roles = {c.it.role for c in groups[key]}
        return ("mcu" not in roles, bool(roles & {"regulator", "battery"}), -len(groups[key]), key)

    order = sorted(groups, key=rank)
    blocks = []
    for key in order:
        cells = sorted(
            groups[key], key=lambda c: (c.it.role == "passive", _natural(c.it.ref), c.unit)
        )
        groups[key] = cells
        pos, w, h = _pack([(c.w, c.h) for c in cells], BLOCK_MAX_W, 4.0)
        heading = len(_title(key)) * 1.6 + 4  # bold 2 mm heading
        blocks.append((key, cells, pos, max(w + 2 * BLOCK_PAD, heading), h + 2 * BLOCK_PAD + 6.0))

    page = PAGES[-1]
    for cand in PAGES:
        usable = cand[1] - 2 * MARGIN
        bpos, bw, bh = _pack([(b[3], b[4]) for b in blocks], usable, BLOCK_GAP)
        if bw <= usable and bh <= cand[2] - 2 * MARGIN - TITLE_H:
            page = cand
            break
    usable = page[1] - 2 * MARGIN
    bpos, bw, bh = _pack([(b[3], b[4]) for b in blocks], usable, BLOCK_GAP)
    pw, ph = page[1], page[2]
    paper = ["paper", _q(page[0])]
    if bh > page[2] - 2 * MARGIN - TITLE_H:  # bigger than the largest sheet: a custom one
        pw, ph = max(pw, bw + 2 * MARGIN), bh + 2 * MARGIN + TITLE_H
        paper = ["paper", '"User"', f"{pw:.1f}", f"{ph:.1f}"]

    root = str(uuid.uuid4())
    body: list[Node] = []
    lib_nodes: dict[str, Node] = {}
    pwr_n = 0
    nets: set[str] = set()

    def uid() -> Node:
        return ["uuid", _q(str(uuid.uuid4()))]

    def font(size: float = FONT, bold: bool = False) -> Node:
        f: Node = ["font", ["size", f"{size}", f"{size}"]]
        if bold:
            f.append(["bold", "yes"])
        return f

    def instance(
        lib_id: str,
        ref: str,
        value: str,
        x: float,
        y: float,
        rot: int,
        unit: int,
        pins: list[str],
        footprint: str = "",
        ref_at: tuple[float, float] | None = None,
        val_at: tuple[float, float] | None = None,
        hidden_ref: bool = False,
    ) -> Node:
        rx, ry = ref_at or (x, y - 3)
        vx, vy = val_at or (x, y + 3)
        ref_fx: Node = ["effects", font()]
        if hidden_ref:
            ref_fx.append(["hide", "yes"])
        node: Node = [
            "symbol",
            ["lib_id", _q(lib_id)],
            ["at", f"{x:.2f}", f"{y:.2f}", str(rot)],
            ["unit", str(unit)],
            ["exclude_from_sim", "no"],
            ["in_bom", "no" if hidden_ref else "yes"],
            ["on_board", "no" if hidden_ref else "yes"],
            ["dnp", "no"],
            uid(),
            ["property", '"Reference"', _q(ref), ["at", f"{rx:.2f}", f"{ry:.2f}", "0"], ref_fx],
            [
                "property",
                '"Value"',
                _q(value),
                ["at", f"{vx:.2f}", f"{vy:.2f}", "0"],
                ["effects", font()],
            ],
            [
                "property",
                '"Footprint"',
                _q(footprint),
                ["at", f"{x:.2f}", f"{y:.2f}", "0"],
                ["effects", font(), ["hide", "yes"]],
            ],
        ]
        for p in pins:
            node.append(["pin", _q(p), uid()])
        node.append(
            [
                "instances",
                [
                    "project",
                    _q(project),
                    ["path", _q("/" + root), ["reference", _q(ref)], ["unit", str(unit)]],
                ],
            ]
        )
        return node

    for (key, cells, pos, w, h), (bx, by) in zip(blocks, bpos, strict=True):
        x0, y0 = MARGIN + bx, MARGIN + by
        body.append(
            [
                "rectangle",
                ["start", f"{x0:.2f}", f"{y0:.2f}"],
                ["end", f"{x0 + w:.2f}", f"{y0 + h:.2f}"],
                ["stroke", ["width", "0.2"], ["type", "dash"]],
                ["fill", ["type", "none"]],
                uid(),
            ]
        )
        body.append(
            [
                "text",
                _q(_title(key)),
                ["exclude_from_sim", "no"],
                ["at", f"{x0 + 2:.2f}", f"{y0 + 4.5:.2f}", "0"],
                ["effects", font(2.0, bold=True), ["justify", "left", "bottom"]],
                uid(),
            ]
        )
        for c, (cx, cy) in zip(cells, pos, strict=True):
            sx = _snap(x0 + BLOCK_PAD + cx + c.ox)
            sy = _snap(y0 + BLOCK_PAD + 6.0 + cy + c.oy)
            sym, it = c.sym, c.it
            lib_nodes.setdefault(sym.lib_id, sym.node)
            ux0, uy0, ux1, uy1 = sym.bbox[c.unit]
            mine = [p for p in sym.pins if p.unit in (0, c.unit)]
            body.append(
                instance(
                    sym.lib_id,
                    it.ref,
                    it.label or it.fp.name,
                    sx,
                    sy,
                    0,
                    c.unit,
                    sorted({p.number for p in mine}, key=_natural),
                    footprint=it.fp.lib_id,
                    ref_at=(sx, _snap(sy - uy1 - 2.54)),
                    val_at=(sx, _snap(sy - uy0 + 2.54)),
                )
            )
            for p in mine:
                px, py = sx + p.x, sy - p.y
                net = it.pads.get(p.number) or ""
                out = _outward(p.angle)
                if not net or net.startswith("unconnected-"):
                    body.append(["no_connect", ["at", f"{px:.2f}", f"{py:.2f}"], uid()])
                    continue
                nets.add(net)
                if net in POWER:
                    lib_name, default = POWER[net]
                    pwr = _power_symbol(lib_name)
                    lib_nodes.setdefault(pwr.lib_id, pwr.node)
                    pwr_n += 1
                    sx_, sy_, rot = px, py, (out - default) % 360
                    if out in (0, 180):
                        # a side pin: a short stub, then the symbol upright as drawn
                        sx_ = px + (5.08 if out == 0 else -5.08)
                        rot = 0
                        body.append(
                            [
                                "wire",
                                [
                                    "pts",
                                    ["xy", f"{px:.2f}", f"{py:.2f}"],
                                    ["xy", f"{sx_:.2f}", f"{sy_:.2f}"],
                                ],
                                ["stroke", ["width", "0"], ["type", "default"]],
                                uid(),
                            ]
                        )
                    down = (default + rot) % 360 == 270
                    body.append(
                        instance(
                            pwr.lib_id,
                            f"#PWR{pwr_n:03d}",
                            net,
                            sx_,
                            sy_,
                            rot,
                            1,
                            [pwr.pins[0].number],
                            ref_at=(sx_, sy_),
                            val_at=(sx_, sy_ + (3.81 if down else -3.81)),
                            hidden_ref=True,
                        )
                    )
                    continue
                justify = ["justify", "left" if out in (0, 90) else "right", "bottom"]
                body.append(
                    [
                        "label",
                        _q(net),
                        ["at", f"{px:.2f}", f"{py:.2f}", str(out)],
                        ["effects", font(), justify],
                        uid(),
                    ]
                )

    # a power net no part drives fails KiCad's ERC; a PWR_FLAG on it says the supply comes from
    # off the sheet (a USB port, a battery). Nets a pin already drives get none: two drivers clash.
    driven = {
        it.pads.get(p.number) for it in parts for p in syms[it.ref].pins if p.kind == "power_out"
    }
    flag = _power_symbol("PWR_FLAG")
    fx, fy = MARGIN + 5.08, _snap(ph - MARGIN - TITLE_H + 10.16)
    for net in sorted(n for n in nets if n in POWER and n not in driven):
        lib_name, default = POWER[net]
        pwr = _power_symbol(lib_name)
        lib_nodes.setdefault(pwr.lib_id, pwr.node)
        lib_nodes.setdefault(flag.lib_id, flag.node)
        x, top, low = _snap(fx), fy, fy + 5.08
        pts = ["pts", ["xy", f"{x:.2f}", f"{top:.2f}"], ["xy", f"{x:.2f}", f"{low:.2f}"]]
        body.append(["wire", pts, ["stroke", ["width", "0"], ["type", "default"]], uid()])
        pwr_n += 1
        body.append(
            instance(
                flag.lib_id,
                f"#FLG{pwr_n:03d}",
                "PWR_FLAG",
                x,
                top,
                0,
                1,
                [flag.pins[0].number],
                ref_at=(x, top),
                val_at=(x, top - 5.08),
                hidden_ref=True,
            )
        )
        rot = 0 if default == 270 else 180  # the supply symbol hangs below the flag either way
        body.append(
            instance(
                pwr.lib_id,
                f"#PWR{pwr_n:03d}",
                net,
                x,
                low,
                rot,
                1,
                [pwr.pins[0].number],
                ref_at=(x, low),
                val_at=(x, low + 6.35),
                hidden_ref=True,
            )
        )
        fx += 12.7

    today = dt.date.today().isoformat()
    tb: Node = [
        "title_block",
        ["title", _q(title or "Board")],
        ["date", _q(today)],
        ["rev", '"1"'],
        [
            "comment",
            "1",
            _q(f"{len(parts)} parts, {len(nets)} nets, {len(blocks)} function blocks"),
        ],
        [
            "comment",
            "2",
            _q("Symbols from the parts' own KiCad libraries; nets match the routed board"),
        ],
    ]
    doc: Node = [
        "kicad_sch",
        ["version", "20250114"],
        ["generator", '"eeschema"'],
        ["generator_version", '"9.0"'],
        ["uuid", _q(root)],
        paper,
        tb,
        ["lib_symbols", *lib_nodes.values()],
        *body,
        ["sheet_instances", ["path", '"/"', ["page", '"1"']]],
        ["embedded_fonts", "no"],
    ]
    text = _pretty(doc)
    path.write_text(text)
    return Sheet(
        text, page[0], {ref: s.source for ref, s in syms.items()}, [_title(b[0]) for b in blocks]
    )


def _pretty(node: Node, depth: int = 0) -> str:
    """One list per line for the big containers; KiCad re-formats on save anyway."""
    if isinstance(node, str):
        return node
    if depth >= 1 and not any(isinstance(c, list) and len(c) > 3 for c in node):
        return _emit(node)
    inner = "\n".join("\t" * (depth + 1) + _pretty(c, depth + 1) for c in node[1:])
    return f"({node[0]}\n{inner}\n" + "\t" * depth + ")"


# ---------------------------------------------------------------- export and check


def export(sch: Path, out_dir: Path, cli: str) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    done: dict[str, Path] = {}
    svg_dir = out_dir / "svg"
    subprocess.run(
        [cli, "sch", "export", "svg", "-o", str(svg_dir), str(sch)],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    svgs = sorted(svg_dir.glob("*.svg"))
    if svgs:
        done["svg"] = svgs[0]
    pdf = out_dir / f"{sch.stem}.pdf"
    subprocess.run(
        [cli, "sch", "export", "pdf", "-o", str(pdf), str(sch)],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    done["pdf"] = pdf
    return done


def netlist(sch: Path, cli: str) -> dict[tuple[str, str], str]:
    """(ref, pin) -> net name from the schematic itself (kicad-cli's own netlist)."""
    out = sch.with_suffix(".net")
    subprocess.run(
        [cli, "sch", "export", "netlist", "--format", "kicadsexpr", "-o", str(out), str(sch)],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    tree = _parse(out.read_text())
    nets = _kid(tree, "nets") or []
    pins: dict[tuple[str, str], str] = {}
    for net in _kids(nets, "net"):
        name = _uq((_kid(net, "name") or ["", '""'])[1]).lstrip("/")
        for node in _kids(net, "node"):
            ref, pin = _uq(_kid(node, "ref")[1]), _uq(_kid(node, "pin")[1])
            pins[(ref, pin)] = name
    return pins


def mismatches(items: list[Item], drawn: dict[tuple[str, str], str]) -> list[str]:
    """Pads whose net on the board differs from the schematic's, as 'R1.2: GND != 3V3'.
    Nets are compared as groups of pads, since KiCad names an unlabelled net itself."""
    board: dict[str, set[tuple[str, str]]] = {}
    for it in items:
        if not (it.on_pcb and it.fp is not None):
            continue
        for pad, net in it.pads.items():
            if net and not net.startswith("unconnected-"):
                board.setdefault(net, set()).add((it.ref, pad))
    sch: dict[str, set[tuple[str, str]]] = {}
    for key, net in drawn.items():
        sch.setdefault(net, set()).add(key)
    out = []
    for net, members in board.items():
        if len(members) < 2:
            continue
        names = {drawn.get(m) for m in members}
        if len(names) != 1 or None in names or not members <= sch.get(names.pop() or "", set()):
            out.append(
                f"{net}: "
                + ", ".join(f"{r}.{p}={drawn.get((r, p))}" for r, p in sorted(members)[:6])
            )
    return out
