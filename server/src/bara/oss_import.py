"""Open-source boards as builds: a board from the Library's open-source shelf becomes a build.

The board's own KiCad files (a local copy when there is one, else the repo at the pinned commit)
are read for what they really hold: every footprint with its reference, value, library footprint
and pads, the nets those pads sit on, the Edge.Cuts outline, and the schematic symbol behind each
reference. That becomes the same event stream a generated build writes (spec, design credit,
slots, parts, connections, board, scene, checks, done), recorded in the build library, so the
engine revives it like any other build: ask, edit, swap, add, simulate and export all work on it.

Nothing is invented. A field the files do not give stays empty; the checks are kicad-cli's own
DRC and ERC run on the board's files. The licence and the source (repo, commit, path) stay on
the record and on the design credit.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import posixpath
import re
import shutil
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from bara import naming
from bara.board import kicad as K
from bara.board.evaluate import evaluate
from bara.board.libs import _child, _children, _floats, _shape_points, parse_sexpr
from bara.library import BUILD_ID_RE
from bara.reducer import apply_event, new_build
from bara.util import envelope, now_ts

log = logging.getLogger(__name__)

REPO_DIR = Path(__file__).resolve().parents[3]
EXPLORE_DIR = Path(os.environ.get("BARA_EXPLORE_DIR", REPO_DIR / "web" / "public" / "explore"))
_HOME = Path.home() / "helloworld"
# Where the board library keeps each board's meta.json and board.glb, in order of preference
WORLD_DIRS = [
    Path(p)
    for p in os.environ.get(
        "BARA_ETCH_WORLD",
        os.pathsep.join(
            str(p)
            for p in (
                _HOME / "etch-prod/deploy/etch-app/world/boards",
                _HOME / "pcb-loop/deploy/etch-app/world/boards",
            )
        ),
    ).split(os.pathsep)
    if p
]
# The board library's local copies of the KiCad sources it rendered from
LOCAL_SRC = Path(os.environ.get("BARA_ETCH_SRC", _HOME / "pcb-loop/library/cache/src"))
REMOTE_WORLD = "https://etch.chat/world/boards"
RAW = "https://raw.githubusercontent.com"
MAX_FILE_BYTES = 80 * 1024 * 1024
MAX_SHEETS = 64
SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,160}$")

MAKERS = re.compile(
    r"\b(cherry|kailh|gateron|alps|panasonic|jst|molex|amphenol|te connectivity|w[uü]rth|murata|"
    r"texas instruments|nordic|espressif|stmicroelectronics|microchip|atmel|infineon|nxp|"
    r"analog devices|maxim|diodes inc|vishay|yageo|samsung|tdk|omron|e-switch|apem|nichicon|"
    r"wiznet|silicon labs|raspberry pi|adafruit|sparkfun|seeed|xiao|arduino|pimoroni|ebyte|"
    r"ai-thinker|hoperf|semtech|lite-on|everlight|worldsemi|cree|osram|bourns|littelfuse|"
    r"knowles|invensense|bosch|sensirion|lattice|xilinx|altera|rohm|toshiba|onsemi|fairchild|"
    r"linear technology|wch|winbond|macronix|gigadevice|ftdi|kicad)\b[\s_-]*",
    re.I,
)

CATEGORY_CLASS = {
    "keyboards": "input_device",
    "iot": "sensor_station",
    "dev-boards": "computer",
    "audio": "audio",
    "robotics": "robot",
    "tools": "tool",
    "retro": "handheld",
    "lighting": "lighting",
    "wearables": "wearable",
    "rf": "radio",
    "displays": "display_device",
    "computing": "computer",
}
MASK_COLOURS = {
    "green": "#1E5A32",
    "black": "#14171A",
    "blue": "#1C3A6E",
    "red": "#7E1F1F",
    "white": "#E6E6E2",
    "purple": "#45285F",
    "yellow": "#C6A519",
    "matte black": "#14171A",
}
COMMERCIAL_NO = re.compile(r"\bNC\b|non-?commercial", re.I)
POWER_NET = re.compile(
    r"^(gnd|agnd|dgnd|pgnd|vss|vcc|vdd|vbus|vbat|vin|vsys|v?\+?\d+v\d*|\+\d.*|3v3|5v|1v8)$", re.I
)


def scrub(text: str) -> str:
    """Text for the screen: no maker names, no links, no em-dashes."""
    out = re.sub(r"https?://\S+", "", str(text or ""))
    out = MAKERS.sub("", out).replace("—", ", ").replace("–", "-")
    out = re.sub(r"\s{2,}", " ", out)
    return re.sub(r"^[\s_\-·,;:]+|[\s_\-·,;:]+$", "", out).strip()


def first_sentence(text: str, limit: int = 160) -> str:
    clean = scrub(str(text or "").replace("`", ""))
    m = re.match(r"^.*?[.!?](?=\s|$)", clean)
    out = (m.group(0) if m else clean)[:limit]
    return out[:1].upper() + out[1:]


def oss_build_id(slug: str) -> str:
    return "b_os" + hashlib.sha1(slug.encode()).hexdigest()[:24]


def board_key(slug: str) -> str:
    return hashlib.sha1(f"oss:{slug}".encode()).hexdigest()[:24]


# ---------------------------------------------------------------- board index and source files


def index_row(slug: str) -> dict[str, Any] | None:
    try:
        data = json.loads((EXPLORE_DIR / "index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return next((b for b in data.get("boards") or [] if b.get("slug") == slug), None)


def _get(url: str, limit: int = MAX_FILE_BYTES) -> bytes:
    host = urllib.parse.urlparse(url).hostname or ""
    if host not in ("raw.githubusercontent.com", "etch.chat"):
        raise ValueError(f"not a board source host: {host}")
    req = urllib.request.Request(url, headers={"User-Agent": "bara-oss-import"})
    with urllib.request.urlopen(req, timeout=45) as resp:  # noqa: S310 (host checked above)
        data = resp.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"{url} is larger than {limit} bytes")
    return data


def board_meta(slug: str) -> dict[str, Any]:
    """The board library's meta.json for a board: pcb path, commit, mask, GLB bounds."""
    for root in WORLD_DIRS:
        path = root / slug / "meta.json"
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    return json.loads(_get(f"{REMOTE_WORLD}/{urllib.parse.quote(slug)}/meta.json", 2 * 1024 * 1024))


def board_glb(slug: str, dest: Path) -> Path:
    """The board's rendered GLB (every footprint's real model in place), copied next to the
    engine's other board GLBs."""
    if dest.is_file() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    for src in [EXPLORE_DIR / "glb" / f"{slug}.glb", *[r / slug / "board.glb" for r in WORLD_DIRS]]:
        if src.is_file():
            shutil.copyfile(src, dest)
            return dest
    data = _get(f"{REMOTE_WORLD}/{urllib.parse.quote(slug)}/board.glb")
    if data[:4] != b"glTF":
        raise ValueError("the board model is not a GLB")
    dest.write_bytes(data)
    return dest


_SHEETFILE = re.compile(r'\(property\s+"Sheet\s?[Ff]ile"\s+"([^"]+)"')


def _sheet_refs(text: str) -> list[str]:
    return list(dict.fromkeys(_SHEETFILE.findall(text)))


def _safe_rel(base: str, ref: str) -> str | None:
    """A sheet path relative to the root sheet's folder, or None when it leaves the repo folder."""
    if ref.startswith(("/", "\\")) or ":" in ref or "\\" in ref:
        return None
    joined = posixpath.normpath(posixpath.join(base, ref)) if base else posixpath.normpath(ref)
    if joined.startswith("..") or joined.startswith("/"):
        return None
    return joined


def fetch_sources(
    slug: str, meta: dict[str, Any], download_dir: Path, out_dir: Path
) -> dict[str, Any]:
    """Put the board's KiCad files in out_dir as main.kicad_pcb / main.kicad_pro / main.kicad_sch
    (sub-sheets keep their names and folders next to it), so the engine's DRC, ERC and sim
    checks find them through routing.cache_key. Returns what was used and from where."""
    pcb_path = str(meta.get("pcb_path") or "")
    stem = Path(pcb_path).stem
    sheet_dir = posixpath.dirname(pcb_path)
    got: dict[str, Any] = {
        "from": None,
        "pcb": pcb_path,
        "schematic": None,
        "sheets": [],
        "project": False,
    }
    if (out_dir / "main.kicad_pcb").is_file():
        prior = out_dir / "sources.json"
        if prior.is_file():
            return json.loads(prior.read_text(encoding="utf-8"))
    out_dir.mkdir(parents=True, exist_ok=True)
    local = LOCAL_SRC / slug
    if (local / "orig.kicad_pcb").is_file() or (local / "board.kicad_pcb").is_file():
        got["from"] = "local copy"
        pcb = local / "orig.kicad_pcb"
        shutil.copyfile(
            pcb if pcb.is_file() else local / "board.kicad_pcb", out_dir / "main.kicad_pcb"
        )
        if (local / "board.kicad_pro").is_file():
            shutil.copyfile(local / "board.kicad_pro", out_dir / "main.kicad_pro")
            got["project"] = True
        sch_dir = local / "sch"
        sheets = sorted(sch_dir.rglob("*.kicad_sch")) if sch_dir.is_dir() else []
        root = next((s for s in sheets if s.stem == stem), sheets[0] if len(sheets) == 1 else None)
        if root is not None:
            shutil.copyfile(root, out_dir / "main.kicad_sch")
            got["schematic"] = root.name
            for s in sheets:
                if s != root:
                    rel = s.relative_to(sch_dir)
                    (out_dir / rel).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(s, out_dir / rel)
                    got["sheets"].append(str(rel))
    else:
        owner, repo, commit = meta.get("owner"), meta.get("repo"), meta.get("commit")
        if not (owner and repo and commit and pcb_path):
            raise ValueError("the board record names no repo, commit or board file")
        got["from"] = f"github.com/{owner}/{repo} at {str(commit)[:7]}"
        base = f"{RAW}/{urllib.parse.quote(str(owner))}/{urllib.parse.quote(str(repo))}/{commit}/"
        download_dir.mkdir(parents=True, exist_ok=True)

        def pull(rel: str, required: bool) -> bytes | None:
            try:
                data = _get(base + urllib.parse.quote(rel))
            except Exception:
                if required:
                    raise
                return None
            dest = download_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            return data

        pcb = pull(pcb_path, True) or b""
        if not pcb.lstrip().startswith(b"(kicad_pcb"):
            raise ValueError("the board file is not a KiCad board")
        (out_dir / "main.kicad_pcb").write_bytes(pcb)
        pro = pull(posixpath.join(sheet_dir, stem + ".kicad_pro"), False)
        if pro:
            (out_dir / "main.kicad_pro").write_bytes(pro)
            got["project"] = True
        root_rel = posixpath.join(sheet_dir, stem + ".kicad_sch")
        root = pull(root_rel, False)
        if root and root.lstrip().startswith(b"(kicad_sch"):
            (out_dir / "main.kicad_sch").write_bytes(root)
            got["schematic"] = posixpath.basename(root_rel)
            queue = [(sheet_dir, r) for r in _sheet_refs(root.decode("utf-8", "replace"))]
            seen: set[str] = set()
            while queue and len(seen) < MAX_SHEETS:
                cur, ref = queue.pop(0)
                rel = _safe_rel(cur, ref)
                if rel is None or rel in seen:
                    continue
                seen.add(rel)
                data = pull(rel, False)
                if not data or not data.lstrip().startswith(b"(kicad_sch"):
                    continue
                # placed where the root sheet's own relative reference expects it
                local_rel = posixpath.relpath(rel, sheet_dir) if sheet_dir else rel
                if local_rel.startswith(".."):
                    continue
                dest = out_dir / local_rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
                got["sheets"].append(local_rel)
                queue += [
                    (posixpath.dirname(rel), r)
                    for r in _sheet_refs(data.decode("utf-8", "replace"))
                ]
    (out_dir / "sources.json").write_text(json.dumps(got), encoding="utf-8")
    return got


# ---------------------------------------------------------------- reading the KiCad files


def _strs(node: list | None) -> list[str]:
    return [x for x in (node or [])[1:] if isinstance(x, str)]


def _prop(node: list, name: str) -> str | None:
    for p in _children(node, "property"):
        if len(p) > 2 and p[1] == name and isinstance(p[2], str):
            return p[2]
    return None


def _fp_text(node: list, kind: str) -> str | None:
    for t in _children(node, "fp_text"):
        if len(t) > 2 and t[1] == kind and isinstance(t[2], str):
            return t[2]
    return None


def read_pcb(text: str) -> dict[str, Any]:
    tree = parse_sexpr(text)
    general = _child(tree, "general")
    thickness = _floats(_child(general, "thickness"), 1)[0] if general else 0.0
    layers = _child(tree, "layers") or []
    copper = [
        item for item in layers[1:]
        if isinstance(item, list) and len(item) > 2 and str(item[1]).endswith(".Cu")
    ]  # fmt: skip
    footprints = []
    for fp in [*_children(tree, "footprint"), *_children(tree, "module")]:
        at = _floats(_child(fp, "at"), 3)
        layer_node = _child(fp, "layer")
        layer = str(layer_node[1]) if layer_node and len(layer_node) > 1 else "F.Cu"
        attrs = set(_strs(_child(fp, "attr")))
        pads = []
        for pad in _children(fp, "pad"):
            net = _child(pad, "net")
            name = (
                next(
                    (
                        x
                        for x in reversed(net[1:])
                        if isinstance(x, str) and not re.fullmatch(r"\d+", x)
                    ),
                    None,
                )
                if net
                else None
            )
            pos = _floats(_child(pad, "at"), 2)
            size = _floats(_child(pad, "size"), 2)
            pads.append(
                {
                    "number": str(pad[1]) if len(pad) > 1 else "",
                    "net": name,
                    "at": pos,
                    "size": size,
                }
            )
        court = [
            pt
            for item in fp
            if isinstance(item, list)
            and item
            and item[0] in ("fp_line", "fp_rect", "fp_circle", "fp_arc", "fp_poly")
            and str((_child(item, "layer") or ["", ""])[1]).endswith("CrtYd")
            for pt in _shape_points(item)
        ]
        if not court:
            court = [
                (p["at"][0] + sx * p["size"][0] / 2, p["at"][1] + sy * p["size"][1] / 2)
                for p in pads for sx in (-1, 1) for sy in (-1, 1)
            ]  # fmt: skip
        footprints.append(
            {
                "lib_id": str(fp[1]) if len(fp) > 1 and isinstance(fp[1], str) else "",
                "ref": _prop(fp, "Reference") or _fp_text(fp, "reference") or "",
                "value": _prop(fp, "Value") or _fp_text(fp, "value") or "",
                "descr": _prop(fp, "Description") or " ".join(_strs(_child(fp, "descr"))),
                "at": at,
                "side": "bottom" if layer.startswith("B.") else "top",
                "attrs": sorted(attrs),
                "has_model": bool(_children(fp, "model")),
                "pads": pads,
                "court": court,
            }
        )
    edges = []
    for item in tree[1:] if tree else []:
        if not (
            isinstance(item, list)
            and item
            and item[0] in ("gr_line", "gr_arc", "gr_rect", "gr_circle", "gr_poly")
        ):
            continue
        if str((_child(item, "layer") or ["", ""])[1]) != "Edge.Cuts":
            continue
        edges.append(_edge_points(item))
    return {
        "thickness_mm": thickness or None,
        "copper_layers": len(copper) or None,
        "footprints": footprints,
        "edges": [e for e in edges if len(e) >= 2],
    }


def _edge_points(item: list) -> list[tuple[float, float]]:
    head = item[0]
    if head == "gr_line":
        a, b = _floats(_child(item, "start"), 2), _floats(_child(item, "end"), 2)
        return [(a[0], a[1]), (b[0], b[1])]
    if head == "gr_rect":
        a, b = _floats(_child(item, "start"), 2), _floats(_child(item, "end"), 2)
        return [(a[0], a[1]), (b[0], a[1]), (b[0], b[1]), (a[0], b[1]), (a[0], a[1])]
    if head == "gr_circle":
        c, e = _floats(_child(item, "center"), 2), _floats(_child(item, "end"), 2)
        r = math.hypot(e[0] - c[0], e[1] - c[1])
        return [
            (c[0] + r * math.cos(t * math.pi / 24), c[1] + r * math.sin(t * math.pi / 24))
            for t in range(49)
        ]
    if head == "gr_poly":
        return [tuple(_floats(p, 2)) for p in _children(_child(item, "pts") or [], "xy")]  # type: ignore[misc]
    # gr_arc: KiCad 6+ start/mid/end; KiCad 5 start = centre, end = a point, angle
    if _child(item, "mid") is not None:
        s, m, e = (_floats(_child(item, k), 2) for k in ("start", "mid", "end"))
        return _arc3(s, m, e)
    c, s = _floats(_child(item, "start"), 2), _floats(_child(item, "end"), 2)
    ang = _floats(_child(item, "angle"), 1)[0]
    r = math.hypot(s[0] - c[0], s[1] - c[1])
    a0 = math.atan2(s[1] - c[1], s[0] - c[0])
    n = max(2, int(abs(ang) / 7.5))
    return [
        (
            c[0] + r * math.cos(a0 + math.radians(ang) * i / n),
            c[1] + r * math.sin(a0 + math.radians(ang) * i / n),
        )
        for i in range(n + 1)
    ]


def _arc3(s: list[float], m: list[float], e: list[float]) -> list[tuple[float, float]]:
    ax, ay, bx, by, cx, cy = s[0], s[1], m[0], m[1], e[0], e[1]
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-9:
        return [(ax, ay), (cx, cy)]
    ux = (
        (ax**2 + ay**2) * (by - cy) + (bx**2 + by**2) * (cy - ay) + (cx**2 + cy**2) * (ay - by)
    ) / d
    uy = (
        (ax**2 + ay**2) * (cx - bx) + (bx**2 + by**2) * (ax - cx) + (cx**2 + cy**2) * (bx - ax)
    ) / d
    r = math.hypot(ax - ux, ay - uy)
    a0, a1, am = (math.atan2(p[1] - uy, p[0] - ux) for p in (s, e, m))

    def norm(a: float) -> float:
        return a % (2 * math.pi)

    sweep = norm(a1 - a0)
    if norm(am - a0) > sweep:  # the mid point is on the other way round
        sweep -= 2 * math.pi
    n = max(2, int(abs(math.degrees(sweep)) / 7.5))
    return [
        (ux + r * math.cos(a0 + sweep * i / n), uy + r * math.sin(a0 + sweep * i / n))
        for i in range(n + 1)
    ]


def chain_outline(
    edges: list[list[tuple[float, float]]], tol: float = 0.02
) -> list[tuple[float, float]]:
    """The Edge.Cuts pieces joined end to end; the closed loop with the largest area (the board's
    outer edge). Empty when the pieces never close."""
    pieces = [list(e) for e in edges]
    loops: list[list[tuple[float, float]]] = []

    def near(a: tuple[float, float], b: tuple[float, float]) -> bool:
        return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol

    while pieces:
        cur = pieces.pop(0)
        grown = True
        while grown and not (len(cur) > 2 and near(cur[0], cur[-1])):
            grown = False
            for i, p in enumerate(pieces):
                if near(cur[-1], p[0]):
                    cur += p[1:]
                elif near(cur[-1], p[-1]):
                    cur += list(reversed(p))[1:]
                elif near(cur[0], p[-1]):
                    cur = p[:-1] + cur
                elif near(cur[0], p[0]):
                    cur = list(reversed(p))[:-1] + cur
                else:
                    continue
                pieces.pop(i)
                grown = True
                break
        if len(cur) > 3 and near(cur[0], cur[-1]):
            loops.append(cur[:-1])

    def area(poly: list[tuple[float, float]]) -> float:
        return (
            abs(
                sum(
                    poly[i][0] * poly[i - 1][1] - poly[i - 1][0] * poly[i][1]
                    for i in range(len(poly))
                )
            )
            / 2
        )

    return max(loops, key=area) if loops else []


def read_schematics(folder: Path) -> dict[str, dict[str, str]]:
    """ref -> {lib_id, description} from every sheet of the board's schematic."""
    out: dict[str, dict[str, str]] = {}
    for sch in sorted(folder.rglob("*.kicad_sch")):
        try:
            tree = parse_sexpr(sch.read_text(encoding="utf-8", errors="replace"))
        except (OSError, RecursionError):
            continue
        descs: dict[str, str] = {}
        for lib in _children(tree, "lib_symbols"):
            for sym in _children(lib, "symbol"):
                if len(sym) > 1 and isinstance(sym[1], str):
                    d = _prop(sym, "ki_description") or _prop(sym, "Description")
                    if d:
                        descs[sym[1]] = d
        for sym in _children(tree, "symbol"):
            lib_id = next((str(x[1]) for x in _children(sym, "lib_id") if len(x) > 1), "")
            if not lib_id or lib_id.startswith("power:"):
                continue
            refs = {_prop(sym, "Reference") or ""}
            for inst in _children(sym, "instances"):
                for proj in _children(inst, "project"):
                    for path in _children(proj, "path"):
                        refs |= {str(r[1]) for r in _children(path, "reference") if len(r) > 1}
            desc = _prop(sym, "Description") or descs.get(lib_id, "")
            for ref in refs:
                if ref and not ref.startswith("#") and "?" not in ref:
                    out.setdefault(ref, {"lib_id": lib_id, "description": desc})
    return out


# ---------------------------------------------------------------- what each footprint is

_SKIP_PREFIX = {
    "H",
    "MH",
    "HOLE",
    "FID",
    "TP",
    "G",
    "LOGO",
    "NT",
    "REF",
    "KIBUZZARD",
    "GRAPHIC",
    "IMG",
    "ART",
}
_SKIP_LIB = re.compile(r"^(MountingHole|Fiducial|TestPoint|Symbol|NetTie|kibuzzard|logo)", re.I)
_MCU = re.compile(
    r"rp2040|rp2350|esp32|esp8266|esp-wroom|stm32|atmega|attiny|atsam|samd\d|nrf5[0-9]|ch32v|ch55\d|gd32|"
    r"pic1[0-9]|pic32|mcu_|nice.?nano|pro.?micro|promicro|xiao|pi.?pico|\bpico\b|teensy|elite.?c|\bblackpill|"
    r"efm32|lpc\d{3,4}|mk20|kl2\d|imxrt|ice40|ecp5|ttgo|micro32|wroom|wrover",
    re.I,
)
_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"ssd13|sh110|oled", re.I), "display.oled"),
    (re.compile(r"e-?paper|\bepd\b|e-?ink", re.I), "display.epaper"),
    (re.compile(r"1602|hd44780|lcd.?char", re.I), "display.lcd_char"),
    (re.compile(r"ili9|st77[0-9]{2}|\btft\b|\blcd\b|gc9a01", re.I), "display.tft"),
    (re.compile(r"7.?seg|seven.?seg", re.I), "display.seven_segment"),
    (re.compile(r"sx12[67]|rfm9|\blora\b", re.I), "comms.lora"),
    (re.compile(r"bme68|ccs811|sgp[34]|ens160", re.I), "sense.gas"),
    (re.compile(r"scd[34]\d|\bco2\b", re.I), "sense.co2"),
    (re.compile(r"bm[ep]\d{3}|lps\d|ms56|dps310|pressure", re.I), "sense.pressure"),
    (re.compile(r"\bsht\d|hdc\d|htu\d|aht\d|si70\d|dht\d|humidity", re.I), "sense.humidity"),
    (
        re.compile(r"tmp1\d\d|ds18b|lm75|mcp9808|thermistor|\bntc\b|temperature", re.I),
        "sense.temperature",
    ),
    (
        re.compile(r"mpu.?[69]|icm.?\d|lsm\d|lis[23]|bmi\d|adxl|\bimu\b|acceler|gyro", re.I),
        "sense.imu",
    ),
    (
        re.compile(
            r"veml|tsl25|bh1750|apds|ltr.?\d|photo.?(diode|transistor|resistor)"
            r"|light sensor|\bldr\b",
            re.I,
        ),
        "sense.light",
    ),
    (re.compile(r"vl53|vl6180|proximity|time.?of.?flight", re.I), "sense.proximity"),
    (re.compile(r"\bhall\b|ah49|drv50|tmag", re.I), "sense.magnetic"),
    (re.compile(r"ina[12]\d\d|acs7\d|current.?sens|shunt.?monitor", re.I), "sense.current"),
    (re.compile(r"microphone|\bmic\b|ics4|sph06|spm14", re.I), "sense.sound"),
    (re.compile(r"\bgps\b|gnss|neo-\d|max-m", re.I), "sense.gnss"),
    (re.compile(r"moisture", re.I), "sense.soil_moisture"),
    (re.compile(r"max1704|fuel.?gauge", re.I), "power.fuel_gauge"),
    (re.compile(r"tp4056|mcp738|bq24|bq25|charger|ltc40", re.I), "power.charger"),
    (
        re.compile(
            r"ldo|regulator|ams1117|ap2112|xc6206|mcp1700|lm1117|tps6|tlv7|ap7\d|me6211|rt9\d|buck|boost|lm78|lm317|ncp1",
            re.I,
        ),
        "power.regulator",
    ),
    (re.compile(r"\besd\b|\btvs\b|usblc|prtr|tpd\d|sp05|polyfuse|ptc", re.I), "power.protection"),
    (re.compile(r"w25q|spi.?flash|is25|gd25|\bflash\b|qspi", re.I), "storage.flash"),
    (re.compile(r"24c\d|eeprom|at24", re.I), "storage.eeprom"),
    (re.compile(r"micro.?sd|sd.?card|tf.?card", re.I), "storage.sd_card"),
    (re.compile(r"ch34\d|cp210|ft232|usb.?uart|usb.?serial", re.I), "comms.usb_device"),
]


def classify(fp: dict[str, Any], sym: dict[str, str] | None) -> str | None:
    """The function a footprint serves, from its reference prefix, symbol, footprint, value and
    descriptions. None for board-only items (holes, fiducials, logos, test points)."""
    ref = str(fp.get("ref") or "")
    prefix = (re.match(r"[A-Za-z_]+", ref) or [""])[0].upper().rstrip("_")
    lib_id = str(fp.get("lib_id") or "")
    if not ref or ref.startswith("#") or "board_only" in fp.get("attrs", []):
        return None
    if "exclude_from_bom" in fp.get("attrs", []) and not fp.get("pads"):
        return None
    if (
        prefix in _SKIP_PREFIX
        or _SKIP_LIB.match(lib_id)
        or re.search(r"solderjumper|solder_jumper", lib_id, re.I)
    ):
        return None
    if not fp.get("pads"):
        return None
    sym_id = (sym or {}).get("lib_id", "")
    text = " ".join(
        [
            sym_id,
            lib_id,
            str(fp.get("value") or ""),
            (sym or {}).get("description", ""),
            str(fp.get("descr") or ""),
        ]
    )
    low = text.lower()
    if re.search(r"micromod|processor.?module|cpu.?module", low):
        return "compute.mcu"  # the socket the plug-in controller board sits in
    # a library nickname ("RP2040:W25Q16") names the project, not the part
    bare = " ".join(
        [
            sym_id.split(":")[-1],
            lib_id.split(":")[-1],
            str(fp.get("value") or ""),
            (sym or {}).get("description", ""),
            str(fp.get("descr") or ""),
        ]
    ).lower()
    if _MCU.search(bare) and prefix not in (
        "R",
        "C",
        "L",
        "D",
        "J",
        "P",
        "CN",
        "SW",
        "LED",
        "Y",
        "X",
    ):
        return "compute.mcu"
    if prefix in ("SW", "K", "KEY", "S", "MX", "KS") or sym_id.lower().startswith("switch:"):
        if re.search(r"rotary|encoder|ec1[12]", low):
            return "input.rotary_encoder"
        if re.search(
            r"switch_keyboard|keyswitch|key_?switch|\bmx\b|mx[-_]|choc|kailh|gateron|hotswap|hot_swap|alps|keyboard|\bkey\b",
            low,
        ) or prefix in ("K", "KEY", "MX", "KS"):
            return "input.key"
        if re.search(r"slide|spdt|dpdt|toggle", low):
            return "input.toggle_switch"
        if re.search(r"joystick|thumbstick", low):
            return "input.joystick"
        return "input.button"
    if prefix in ("ENC", "RE", "ROT") or re.search(r"rotary.?encoder|\bec11\b|\bec12\b", low):
        return "input.rotary_encoder"
    if prefix in ("RV", "VR", "POT") or "potentiometer" in low:
        return "input.potentiometer"
    if re.search(r"joystick|thumbstick", low):
        return "input.joystick"
    if prefix in ("LED", "D", "DL") and re.search(
        r"\bled\b|led_|_led|ws28|sk68|apa10|neopixel|rgb", low
    ):
        return (
            "output.rgb_led"
            if re.search(r"ws28|sk68|apa10|neopixel|rgb|ws2812|sk9822", low)
            else "display.indicator_led"
        )
    if prefix in ("BZ", "BUZ", "LS", "SP", "SPK"):
        return (
            "output.speaker"
            if "speaker" in low or prefix in ("LS", "SP", "SPK")
            else "output.buzzer"
        )
    if prefix in ("M", "MOT", "VIB"):
        return "output.haptic" if re.search(r"vibr|haptic|erm|lra", low) else "output.motor_dc"
    if prefix in ("RL", "RLY", "K") and "relay" in low:
        return "output.relay"
    if (
        prefix in ("BT", "BAT", "BATT")
        or re.search(r"battery|coin.?cell|cr20\d\d|cr12\d\d", low)
        and prefix not in ("J", "P", "CN")
    ):
        return "power.coin_cell" if re.search(r"coin|cr20|cr12|cr16", low) else "power.battery"
    if prefix in ("J", "P", "CN", "CON", "USB", "JP", "X") and not re.search(
        r"crystal|xtal|osc", low
    ):
        if re.search(r"micro.?sd|sd.?card|tf.?card", low):
            return "storage.sd_card"
        if re.search(r"usb", low):
            return "power.usb_in"
        if re.search(r"jack|audio|trrs|\btrs\b|3\.5mm|phone", low):
            return "interconnect.jack"
        if re.search(
            r"header|pin_?header|pinheader|conn_\d+x|pin_?socket|pinsocket|1x\d+|2x\d+", low
        ):
            return "interconnect.header"
        return "interconnect.connector"
    if prefix in ("Y", "X", "XTAL", "OSC") or re.search(r"crystal|xtal|oscillator", low):
        return "component.crystal"
    if prefix in ("R", "RN", "RA"):
        return "component.resistor"
    if prefix in ("C", "CP"):
        return "component.capacitor"
    if prefix in ("L", "FB"):
        return "component.inductor"
    if prefix == "F":
        return "power.protection"
    if prefix in ("Q", "T"):
        return "component.transistor"
    if prefix in ("D", "ZD", "TVS"):
        return "power.protection" if re.search(r"\btvs\b|esd", low) else "component.diode"
    for pat, fn in _RULES:
        if pat.search(low):
            return fn
    if prefix in ("U", "IC", "A", "MOD", "MK"):
        return "component.ic"
    return "component.other"


_PASSIVE = ("component.resistor", "component.capacitor", "component.inductor", "component.crystal")
_KIND_MODULE = re.compile(r"module|nice.?nano|pro.?micro|xiao|pico|teensy|wroom|devkit", re.I)


def _package(lib_id: str) -> str:
    tail = lib_id.split(":")[-1]
    return scrub(tail.replace("_", " ")) or "custom footprint"


def _commercial(spdx: str) -> str:
    if not spdx or spdx.upper() in ("NOASSERTION", "OTHER", "UNKNOWN"):
        return "unknown"
    return "no" if COMMERCIAL_NO.search(spdx) else "yes"


# ---------------------------------------------------------------- the build


def _stem(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40] or "part"


def build_record(
    slug: str,
    row: dict[str, Any],
    meta: dict[str, Any],
    pcb: dict[str, Any],
    symbols: dict[str, dict[str, str]],
    glb_url: str,
    glb_bytes: int,
    glb_sha: str,
    key: str,
    sources: dict[str, Any],
) -> dict[str, Any]:
    """Everything the event stream says, from the parsed files: spec, credit, slots, parts,
    part records (for the catalog), connections, board, scene."""
    licence = str(row.get("license") or meta.get("license") or "NOASSERTION")
    commit = str(row.get("commit") or meta.get("commit") or "")
    repo_url = str(row.get("url") or meta.get("url") or "")
    pcb_path = str(meta.get("pcb_path") or "")
    source_url = (
        f"{repo_url}/blob/{commit}/{pcb_path}"
        if repo_url and commit and pcb_path
        else repo_url or None
    )
    commercial = _commercial(licence)
    title = scrub(str(row.get("title") or slug)) or "Open-source board"
    summary = first_sentence(str(row.get("description") or meta.get("description") or ""))
    category = str(row.get("category") or meta.get("category") or "")
    device_class = CATEGORY_CLASS.get(category, "other")

    # footprints in the board's own frame (KiCad mm, y down)
    outline_k = chain_outline(pcb["edges"])
    if outline_k:
        xs, ys = [p[0] for p in outline_k], [p[1] for p in outline_k]
    else:
        bounds = meta.get("glb_bounds_m") or {}
        lo, hi = bounds.get("min") or [], bounds.get("max") or []
        xs = [lo[0] * 1000, hi[0] * 1000] if len(lo) == 3 and len(hi) == 3 else []
        ys = [lo[2] * 1000, hi[2] * 1000] if len(lo) == 3 and len(hi) == 3 else []
        if not xs:
            pts = [fp["at"] for fp in pcb["footprints"]]
            xs, ys = [p[0] for p in pts] or [0.0], [p[1] for p in pts] or [0.0]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    size = [round(max(xs) - min(xs), 2), round(max(ys) - min(ys), 2)]
    thickness = float(
        pcb.get("thickness_mm") or (meta.get("board") or {}).get("thickness_mm") or 1.6
    )
    board_pos = [round(-cx, 3), round(cy, 3), 0.0]

    def local(x: float, y: float) -> list[float]:
        return [round(x, 3), round(-y, 3)]

    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    fp_rows: list[dict[str, Any]] = []
    for fp in sorted(pcb["footprints"], key=lambda f: _ref_key(f["ref"])):
        sym = symbols.get(fp["ref"])
        fn = classify(fp, sym)
        x, y, rot = fp["at"]
        court = fp["court"]
        if court:
            bx0, by0 = min(p[0] for p in court), min(p[1] for p in court)
            bx1, by1 = max(p[0] for p in court), max(p[1] for p in court)
            ox, oy = (bx0 + bx1) / 2, (by0 + by1) / 2
            # footprint-local offsets turn with the footprint (KiCad angles run anticlockwise)
            r = math.radians(rot)
            dx, dy = ox * math.cos(r) + oy * math.sin(r), -ox * math.sin(r) + oy * math.cos(r)
            fsize = [round(bx1 - bx0, 2), round(by1 - by0, 2)]
        else:
            dx = dy = 0.0
            fsize = [0.0, 0.0]
        row_fp = {
            "ref": fp["ref"],
            "label": None,
            "role": fn.split(".")[-1] if fn else "board",
            "lib_id": fp["lib_id"],
            "instance_id": None,
            "center_mm": local(x + dx, y + dy),
            "size_mm": fsize,
            "rot_deg": round(rot, 2),
        }
        fp_rows.append(row_fp)
        if fn is None:
            continue
        value = str(fp.get("value") or "")
        gkey = (
            fn,
            fp["lib_id"],
            "" if fn in ("input.key", "output.rgb_led") else value.strip().lower(),
        )
        g = groups.get(gkey)
        if g is None:
            g = groups[gkey] = {
                "function": fn,
                "lib_id": fp["lib_id"],
                "value": value,
                "refs": [],
                "fps": [],
                "sym": sym,
                "descr": fp.get("descr") or "",
            }
        g["refs"].append(fp["ref"])
        g["fps"].append((fp, row_fp))

    parts: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    slots: list[dict[str, Any]] = []
    ref_owner: dict[str, str] = {}
    used: set[str] = set()
    order = sorted(
        groups.values(),
        key=lambda g: (
            _FN_ORDER.get(g["function"].split(".")[0], 9),
            g["function"],
            _ref_key(g["refs"][0]),
        ),
    )
    for n, g in enumerate(order):
        iid = "u_" + _stem(g["refs"][0])
        while iid in used:
            iid += "_"
        used.add(iid)
        fn = g["function"]
        value = g["value"]
        lib_id = g["lib_id"]
        sym = g["sym"] or {}
        desc_src = sym.get("description") or g["descr"]
        what = first_sentence(desc_src) if desc_src else ""
        pkg = _package(lib_id)
        tail = "" if fn in ("input.key", "output.rgb_led") else _stem(value)
        part_id = f"oss:{slug}:{sym.get('lib_id') or lib_id}:{tail}".rstrip(":")
        is_module = bool(_KIND_MODULE.search(" ".join([lib_id, value, sym.get("lib_id", "")])))
        kind = "module" if is_module else "mechanical" if fn == "input.key" else "component"
        specs: list[dict[str, Any]] = []
        if fn in _PASSIVE and value:
            specs.append({"label": "Value", "value": scrub(value)[:24], "unit": None})
        specs.append({"label": "Package", "value": pkg[:40], "unit": None})
        if len(g["refs"]) > 1:
            specs.append({"label": "On the board", "value": len(g["refs"]), "unit": None})
        bits = [what] if what else []
        bits.append(f"Footprint {pkg}.")
        record = {
            "part_id": part_id,
            "kind": kind,
            "display_name": scrub(value) or pkg,
            "summary": " ".join(bits)[:240],
            "functions": [{"function_id": fn, "primary": True}],
            "interfaces": [],
            "facets": {"kind": kind, "footprint": lib_id},
            "footprint": lib_id,
            "symbol": sym.get("lib_id") or None,
            "value": value or None,
            "refs": g["refs"],
            "assets": [],
            "licence": {"spdx": licence, "commercial_ok": commercial},
            "provenance": {
                "route": "open_source_board",
                "verified": "third_party",
                "source_url": source_url,
                "repo_url": repo_url or None,
                "commit": commit or None,
                "board": slug,
            },
        }
        card = {
            "part_id": part_id,
            "display_name": "",
            "kind": kind,
            "summary": record["summary"],
            "key_specs": specs,
            "thumbnail_url": None,
            "licence_spdx": licence,
            "commercial_ok": commercial,
            "verified": "third_party",
            "source_url": source_url,
            "primary_function": fn,
        }
        naming.neutral(card, record)
        if fn in _PASSIVE and value:
            card["display_name"] = f"{card['display_name']} {scrub(value)[:16]}".strip()
        records.append(record)
        first_fp, first_row = g["fps"][0]
        x, y, rot = first_fp["at"]
        top = first_fp["side"] == "top"
        lx, ly = local(x, y)
        for fp, rowf in g["fps"]:
            rowf["instance_id"] = iid
            rowf["label"] = card["display_name"]
            ref_owner[fp["ref"]] = iid
        slot_id = "s_" + iid[2:]
        label = card["display_name"]
        parts.append(
            {
                "instance_id": iid,
                "part_id": part_id,
                "slot_id": slot_id,
                "label": label[:60],
                "quantity": len(g["refs"]),
                "side": "none",
                "color": None,
                "placement": {
                    "mode": "single" if len(g["refs"]) == 1 else "layout",
                    "position_mm": [
                        round(board_pos[0] + lx, 3),
                        round(board_pos[1] + ly, 3),
                        round(thickness if top else 0.0, 3),
                    ],
                    "rotation_deg": [0.0 if top else 180.0, 0.0, round(rot, 2)],
                    "explode_offset_mm": [0.0, 0.0, 18.0 if top else -18.0],
                    "source": "kicad",
                    "locked": True,
                    "layout_id": None,
                    "refs": g["refs"],
                },
                "card": card,
                "assets": [],
                "origin": "design",
                "status": "ok",
                "finish": None,
            }
        )
        slots.append(
            {
                "slot_id": slot_id,
                "label": label[:60],
                "function_id": fn,
                "criticality": "critical" if fn == "compute.mcu" else "optional",
                "quantity": len(g["refs"]),
                "side": "none",
                "order": n,
                "state": "decided",
                "candidates_total": None,
                "candidates_left": None,
                "chosen_part_id": part_id,
                "instance_ids": [iid],
                "from_design": True,
            }
        )

    # nets: every pad of a part on the board, by net name
    nets: dict[str, list[dict[str, Any]]] = {}
    for fp in pcb["footprints"]:
        owner = ref_owner.get(fp["ref"])
        if owner is None:
            continue
        for pad in fp["pads"]:
            name = pad.get("net")
            if not name or name.lower().startswith("unconnected-"):
                continue
            nets.setdefault(name, []).append(
                {"instance_id": owner, "pin": pad["number"], "index": None}
            )
    pads_on_board: dict[str, int] = {}
    for fp in pcb["footprints"]:
        for pad in fp["pads"]:
            if pad.get("net"):
                pads_on_board[pad["net"]] = pads_on_board.get(pad["net"], 0) + 1
    # a net whose other pads are on board-only items (holes, test points) is not dangling
    nets = {n: m for n, m in nets.items() if len(m) >= 2 or pads_on_board.get(n, 0) < 2}
    net_rows = [
        {
            "name": name,
            "kind": "ground"
            if re.match(r"^(a|d|p)?gnd|^vss", name.lstrip("/"), re.I)
            else "power"
            if POWER_NET.match(name.lstrip("/"))
            else "signal",
            "members": members,
        }
        for name, members in sorted(nets.items())
    ]
    pairs: dict[tuple[str, str], list[str]] = {}
    for net in net_rows:
        if net["kind"] != "signal":
            continue
        owners = list(dict.fromkeys(m["instance_id"] for m in net["members"]))
        for a in owners:
            for b in owners:
                if a < b:
                    pairs.setdefault((a, b), []).append(net["name"])
    connections = []
    for (a, b), names in sorted(pairs.items(), key=lambda kv: -len(kv[1]))[:80]:
        connections.append(
            {
                "connection_id": f"c_{a[2:]}__{b[2:]}"[:64],
                "type": "net",
                "kind": "electrical",
                "from": {"instance_id": a, "interface_id": "pads", "index": None},
                "to": {"instance_id": b, "interface_id": "pads", "index": None},
                "via_instance_id": None,
                "nets": names[:12],
                "resolved": {},
                "origin": "design",
                "status": "ok",
                "label": f"{len(names)} shared net{'s' if len(names) != 1 else ''}",
            }
        )

    board = {
        "board_id": "pcb_main",
        "source": "open_source",
        "side": "none",
        "part_instance_id": None,
        "for_instance_ids": [p["instance_id"] for p in parts],
        "outline_mm": [local(px, py) for px, py in outline_k],
        "size_mm": size,
        "thickness_mm": thickness,
        "layers": pcb.get("copper_layers") or row.get("layers"),
        "position_mm": board_pos,
        "rotation_deg": [0.0, 0.0, 0.0],
        "nets": net_rows,
        "footprints": fp_rows,
        "routing": {
            "status": "routed",
            "unrouted_nets": [],
            "duration_ms": None,
            "method": "original",
            "cache_key": key,
            "cache_hit": True,
            "router": None,
        },
        "drc": None,
        "assets": [
            {
                "asset_id": f"board_{key}",
                "kind": "glb",
                "role": "model",
                "url": glb_url,
                "content_type": "model/gltf-binary",
                "bytes": glb_bytes,
                "sha256": glb_sha,
                "status": "ready",
                "origin": "design",
            }
        ],
        "status": "ok",
        "revision": 1,
        "evaluation": None,
        "finish": {
            "role": "pcb",
            "name": "solder mask",
            "color": MASK_COLOURS.get(
                str((meta.get("board") or {}).get("mask") or "").lower(), "#1E5A32"
            ),
            "opacity": 1.0,
            "roughness": 0.55,
            "metalness": 0.0,
            "transmission": 0.0,
            "ior": 1.45,
            "emissive": None,
            "emissive_intensity": 0.0,
        },
        "source_files": {
            "folder_key": key,
            "pcb": pcb_path or None,
            "schematic": sources.get("schematic"),
            "sheets": sources.get("sheets") or [],
            "from": sources.get("from"),
        },
    }
    span = max(size[0], size[1], 40.0)
    scene = {
        "camera": {
            "position_mm": [0.0, round(-span * 1.0, 1), round(span * 0.8, 1)],
            "target_mm": [0.0, 0.0, 2.0],
            "fov_deg": 35,
        },
        "assembly_bbox_mm": {
            "min": [round(-size[0] / 2, 2), round(-size[1] / 2, 2), -3.0],
            "max": [round(size[0] / 2, 2), round(size[1] / 2, 2), 15.0],
        },
        "render": None,
        "preload": [glb_url],
    }
    functions = sorted({p["card"]["primary_function"] for p in parts})
    prompt = title
    spec = {
        "spec_id": "sp_os" + key[:16],
        "prompt": prompt,
        "normalized_prompt": prompt.lower(),
        "device_class": device_class,
        "taxonomy_path": [device_class, category or "open_source"],
        "functions": [
            {"function_id": f, "required": True, "count": 1, "source": "design"} for f in functions
        ],
        "hard_requirements": [],
        "soft_requirements": [],
        "leftover_text": None,
        "classifier": {
            "stage": "design",
            "confidence": 1.0,
            "margin": None,
            "model": None,
            "latency_ms": 0,
            "provider": "kicad",
            "fallback": False,
        },
        "scope": "in_scope",
        "scope_reason": None,
        "assumptions": [],
        "ambiguity": {"needs_clarify": False, "missing_facets": []},
        "main_purpose": summary or None,
    }
    short_commit = commit[:7]
    reuse = {
        "tier": "exact",
        "design_id": slug,
        "design": {
            "design_id": slug,
            "name": title,
            "summary": summary or None,
            "device_class": device_class,
            "thumbnail_url": None,
            "repo_url": f"{repo_url}/tree/{commit}" if repo_url and commit else repo_url or None,
            "licence_spdx": licence,
            "commercial_ok": commercial,
            "key_specs": [],
        },
        "considered": [],
        "unmet_hard": [],
        "reason": (
            "Opened from an open-source board: its own KiCad files"
            + (f" at commit {short_commit}" if short_commit else "")
            + f", licensed {licence}. Every part, net and footprint here comes from those files."
        ),
    }
    return {
        "spec": spec,
        "reuse": reuse,
        "slots": slots,
        "parts": parts,
        "records": records,
        "connections": connections,
        "board": board,
        "scene": scene,
        "title": title,
        "device_class": device_class,
    }


_FN_ORDER = {
    "compute": 0,
    "input": 1,
    "display": 2,
    "sense": 3,
    "output": 4,
    "comms": 5,
    "power": 6,
    "storage": 7,
    "interconnect": 8,
}


def _ref_key(ref: str) -> tuple[str, int, str]:
    m = re.match(r"([A-Za-z_#]*)(\d*)(.*)", ref or "")
    if not m:
        return (ref, 0, "")
    return (m.group(1), int(m.group(2) or 0), m.group(3))


# ---------------------------------------------------------------- checks


def run_checks(
    folder: Path, board: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, dict[str, Any] | None]:
    """kicad-cli DRC on the board and ERC on its schematic, as check rows plus the evaluation."""
    from bara.firmware_sim.kicad_checks import run_erc

    bid = board["board_id"]
    results: list[dict[str, Any]] = []
    summary = None
    drc: dict[str, Any] | None = None
    try:
        t0 = time.monotonic()
        drc = K.run_drc(folder / "main.kicad_pcb", timeout=240)
        drc_s = round(time.monotonic() - t0, 2)
        routing = {
            **K.count_routing(folder / "main.kicad_pcb"),
            "unrouted_nets": drc.get("unconnected_nets") or [],
        }
        ev = evaluate(bid, board["nets"], drc, routing, {"drc_s": drc_s})
        summary = ev["summary"]
        errors, unconnected = int(drc.get("errors", 0)), int(drc.get("unconnected", 0))
        results.append(
            {
                "check_key": f"board.drc:{bid}",
                "rule_id": "board.drc",
                "status": "pass" if errors == 0 else "fail",
                "severity": "error",
                "message": f"PCB: {errors} errors, {unconnected} unconnected"
                " (kicad-cli DRC on the original board)",
                "subjects": [{"board_id": bid}],
                "measured": errors,
                "limit": 0,
                "unit": "count",
                "stage": "board",
            }
        )
        results += ev["checks"]
    except Exception as exc:  # a board kicad-cli cannot read still opens; the check says so
        log.warning("oss import: DRC did not run on %s: %s", folder, exc)
        results.append(
            {
                "check_key": f"board.drc:{bid}",
                "rule_id": "board.drc",
                "status": "unknown",
                "severity": "info",
                "message": f"KiCad DRC did not run on this board: {str(exc)[:160]}",
                "subjects": [{"board_id": bid}],
                "measured": None,
                "limit": 0,
                "unit": "count",
                "stage": "board",
            }
        )
    sch = folder / "main.kicad_sch"
    if sch.is_file():
        erc = run_erc([(bid, sch)])
        nums = erc.get("numbers") or {}
        status = {"pass": "pass", "fail": "fail"}.get(str(erc.get("status")), "unknown")
        results.append(
            {
                "check_key": f"board.erc:{bid}",
                "rule_id": "board.erc",
                "status": status,
                "severity": "warning",
                "message": f"Schematic: {erc.get('summary') or 'ERC did not run'} (kicad-cli ERC)",
                "subjects": [{"board_id": bid}],
                "measured": nums.get("errors"),
                "limit": 0,
                "unit": "count",
                "stage": "board",
            }
        )
    return results, summary, drc


# ---------------------------------------------------------------- import


class ImportError_(Exception):
    pass


_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def import_board(
    slug: str, *, data_dir: Path, assets_dir: Path, library: Any, catalog: Any = None
) -> dict[str, Any]:
    """The build id for an open-source board, importing it the first time. Idempotent."""
    if not SLUG_RE.fullmatch(slug):
        raise ImportError_("Not a board id.")
    row = index_row(slug)
    if row is None:
        raise ImportError_(f"No open-source board {slug}.")
    build_id = oss_build_id(slug)
    assert BUILD_ID_RE.fullmatch(build_id)
    with _locks_guard:
        lock = _locks.setdefault(slug, threading.Lock())
    with lock:
        existing = library.get(build_id)
        if existing is not None and existing.get("status") == "done":
            if catalog is not None:
                load_records(catalog, data_dir, [slug])
            return {"build_id": build_id, "imported": False}
        key = board_key(slug)
        meta = board_meta(slug)
        meta = {**row, **meta}
        folder = data_dir / "cache" / "boards" / key
        sources = fetch_sources(slug, meta, data_dir / "cache" / "oss_downloads" / slug, folder)
        glb = board_glb(slug, assets_dir / "cache" / "boards" / f"oss_{key}.glb")
        blob = glb.read_bytes()
        sha = hashlib.sha256(blob).hexdigest()
        pcb = read_pcb((folder / "main.kicad_pcb").read_text(encoding="utf-8", errors="replace"))
        symbols = read_schematics(folder) if (folder / "main.kicad_sch").is_file() else {}
        rec = build_record(
            slug, row, meta, pcb, symbols,
            f"/assets/cache/boards/oss_{key}.glb?v={sha[:16]}", len(blob), sha, key, sources,
        )  # fmt: skip
        checks, evaluation, drc = run_checks(folder, rec["board"])
        rec["board"]["evaluation"] = evaluation
        if drc is not None:
            rec["board"]["drc"] = "pass" if int(drc.get("errors", 0)) == 0 else "fail"
            rec["board"]["routing"]["unrouted_nets"] = drc.get("unconnected_nets") or []
        (folder / "parts.json").write_text(json.dumps(rec["records"]), encoding="utf-8")
        write_build(library, build_id, slug, row, meta, rec, checks, sources)
        if catalog is not None:
            load_records(catalog, data_dir, [slug])
        return {"build_id": build_id, "imported": True}


def write_build(
    library: Any,
    build_id: str,
    slug: str,
    row: dict[str, Any],
    meta: dict[str, Any],
    rec: dict[str, Any],
    checks: list[dict[str, Any]],
    sources: dict[str, Any],
) -> None:
    events: list[dict[str, Any]] = []
    t0 = time.monotonic()

    def emit(kind: str, payload: dict[str, Any], stage: str | None = None) -> None:
        events.append(envelope(kind, payload, seq=len(events) + 1, build_id=build_id, stage=stage))

    emit(
        "stage.started",
        {"stage": "classify", "label": "Reading the open-source board", "budget_ms": 1000},
        "classify",
    )
    emit("spec.ready", {"spec": rec["spec"]}, "classify")
    emit("stage.completed", {"stage": "classify", "status": "ok", "duration_ms": 0}, "classify")
    emit(
        "stage.started",
        {"stage": "reuse", "label": "Using the open design as is", "budget_ms": 1000},
        "reuse",
    )
    emit("reuse.decided", rec["reuse"], "reuse")
    emit("stage.completed", {"stage": "reuse", "status": "ok", "duration_ms": 0}, "reuse")
    emit(
        "stage.started",
        {"stage": "compose", "label": "Parts from the board's own files", "budget_ms": 1000},
        "compose",
    )
    emit("slots.ready", {"slots": rec["slots"]}, "compose")
    for part in rec["parts"]:
        emit("part.added", {"part": part}, "compose")
    for conn in rec["connections"]:
        emit("connection.added", {"connection": conn}, "compose")
    emit("stage.completed", {"stage": "compose", "status": "ok", "duration_ms": 0}, "compose")
    emit(
        "stage.started",
        {"stage": "board", "label": "Checking the KiCad board", "budget_ms": 240000},
        "board",
    )
    emit("board.updated", {"board": rec["board"]}, "board")
    emit("check.result", {"results": checks}, "board")
    emit(
        "stage.completed",
        {
            "stage": "board",
            "status": "ok",
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "message": "kicad-cli DRC and ERC on the original files",
        },
        "board",
    )
    emit(
        "stage.started",
        {"stage": "render", "label": "Preparing the 3D scene", "budget_ms": 1000},
        "render",
    )
    emit("scene.ready", {"scene": rec["scene"]}, "render")
    emit("stage.completed", {"stage": "render", "status": "ok", "duration_ms": 0}, "render")
    state = new_build(build_id, rec["title"], now_ts())
    for e in events:
        state = apply_event(state, e) or state
    counts = {"pass": 0, "fail": 0, "unknown": 0}
    for check in state["checks"]:
        s = check.get("status")
        counts[s if s in counts else "unknown"] += 1
    emit(
        "build.done",
        {
            "summary": {
                "part_count": sum(int(p.get("quantity", 1) or 1) for p in state["parts"]),
                "instance_count": len(state["parts"]),
                "connection_count": len(state["connections"]),
                "warning_count": 0,
                "checks": counts,
            },
            "timings_ms": dict(state["timings_ms"]),
            "total_ms": int((time.monotonic() - t0) * 1000),
        },
    )

    class _Run:  # what Library.record reads from a run
        pass

    run = _Run()
    run.build_id = build_id  # type: ignore[attr-defined]
    run.prompt = rec["title"]  # type: ignore[attr-defined]
    run.device = rec["title"]  # type: ignore[attr-defined]
    run.state = {"created_at": events[0]["ts"]}  # type: ignore[attr-defined]
    events_path, meta_path = library._paths(build_id)
    if (
        events_path.exists()
    ):  # a half-written earlier attempt: start the log over, keeping the old one aside
        events_path.replace(events_path.with_suffix(f".jsonl.partial-{int(time.time())}"))
    for e in events:
        library.record(run, e)
    row_meta = json.loads(meta_path.read_text(encoding="utf-8"))
    row_meta["origin"] = "open_source"
    row_meta["source"] = {
        "slug": slug,
        "repo_url": row.get("url") or meta.get("url"),
        "commit": row.get("commit") or meta.get("commit"),
        "pcb_path": meta.get("pcb_path"),
        "licence": row.get("license") or meta.get("license"),
        "licence_url": row.get("license_url") or meta.get("license_url"),
        "files_from": sources.get("from"),
        "schematic": sources.get("schematic"),
    }
    tmp = meta_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(row_meta), encoding="utf-8")
    tmp.replace(meta_path)


def load_records(catalog: Any, data_dir: Path, slugs: list[str] | None = None) -> int:
    """Put imported boards' part records in the catalog, so asking about, swapping and checking
    those parts works like on any build. Returns how many were added."""
    from bara.live.catalog_source import merge_into_catalog

    root = data_dir / "cache" / "boards"
    keys = [board_key(s) for s in slugs] if slugs is not None else None
    added = 0
    folders = (
        [root / k for k in keys]
        if keys is not None
        else (sorted(root.iterdir()) if root.is_dir() else [])
    )
    for folder in folders:
        path = folder / "parts.json"
        if not path.is_file():
            continue
        try:
            records = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        fresh = [r for r in records if r.get("part_id") not in catalog.parts]
        merge_into_catalog(catalog, fresh)
        for r in fresh:  # the card keeps the function the board's files gave the part
            catalog.cards[r["part_id"]]["primary_function"] = r["functions"][0]["function_id"]
        added += len(fresh)
    return added
