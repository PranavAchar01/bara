"""The "generated" tier: every symbol and footprint of the KiCad libraries.

Built by ``catalog_build.kicad_index`` into data/catalog/kicad_index.sqlite. This module only
reads it::

    idx = KicadIndex()                      # None-safe: KicadIndex.open() returns None if unbuilt
    idx.search("optical mouse sensor", kind="symbol", limit=10)   # Part-shaped dicts
    idx.get_part("kicadgen:kicad:sym:Sensor_Motion:ADNS-9800")
    idx.ensure_glb(part_id)                 # converts the one footprint on first call, cached

3D models are not converted up front. ``ensure_glb`` runs the one-footprint board through
kicad-cli (catalog_build.meshes.export_glb) and caches the result under
data/assets/parts/kicad_gen/, served at /assets/parts/kicad_gen/<stem>.glb.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import tempfile
import threading
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

SERVER = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("BARA_DATA_DIR", SERVER / "data"))  # the tree the engine serves
DEFAULT_PATH = DATA / "catalog" / "kicad_index.sqlite"
GLB_DIR = DATA / "assets" / "parts" / "kicad_gen"
GLB_URL = "/assets/parts/kicad_gen"
TIER = "kicad_generated"
SIBLING_SIMILARITY = 0.8  # how alike a sibling footprint's name must be to lend its model

_WORD = re.compile(r"[A-Za-z0-9]+")
_BODY = re.compile(r"\d+(?:\.\d+)?x\d+(?:\.\d+)?(?:x\d+(?:\.\d+)?)?mm")
_GRID = re.compile(r"(?<![\d.])(\d+x\d{2})(?![\d.]|mm)")  # pin rows x columns: 1x02, 2x20
# a two-terminal chip body by its EIA/metric size, Fuse_1812_4532Metric: every library's chip
# of that size is the same block, so a fuse or ferrite without a model borrows a resistor's
_CHIP = re.compile(r"^[A-Za-z]+_(\d{4}_\d{4}Metric)$")
CHIP_LENDERS = (("Resistor_SMD", "R"), ("Capacitor_SMD", "C"), ("Inductor_SMD", "L"))
_STEM_BAD = re.compile(r"[^A-Za-z0-9._-]")
_glb_lock = threading.Lock()


_PKG = re.compile(r"^([A-Z]+)-(\d+)")
_PKG_BODY = re.compile(r"(?<![A-Za-z])(\d+(?:\.\d+)?x\d+(?:\.\d+)?)mm")
_PITCH = re.compile(r"_P(\d+(?:\.\d+)?)mm")
# thin, very thin, ultra thin and heat-sink variants share the package's outline
_THIN = re.compile(r"^[VWUXH](?=(?:QFN|DFN|SON|TSSOP|SSOP|SOP|LGA|BGA))")


def package_sig(name: str) -> tuple[str, str, str, str] | None:
    """(family, pins, body, pitch) of a package footprint name, ignoring the exposed pad:
    "VQFN-16-1EP_3x3mm_P0.5mm_EP1.68x1.68mm" -> ("QFN", "16", "3x3", "0.5"). None when the
    name is not a sized package."""
    m = _PKG.match(name)
    body = _PKG_BODY.search(name)
    pitch = _PITCH.search(name)
    if not m or not body or not pitch:
        return None
    return (_THIN.sub("", m.group(1)), m.group(2), body.group(1), pitch.group(1))


# EasyEDA/LCSC package names: SOIC-16_L10.3-W7.5-P1.27-LS10.3-BL is a 16-pin gull-wing, 10.3 mm
# long, 7.5 mm wide, 1.27 mm pitch (body size, as KiCad names it: SOIC-16W_7.5x10.3mm_P1.27mm)
_EASYEDA_PKG = re.compile(r"^([A-Z]+)-(\d+)_L(\d+(?:\.\d+)?)-W(\d+(?:\.\d+)?)-P(\d+(?:\.\d+)?)")
_FAMILY_ALIAS = {"SOP": "SOIC", "SO": "SOIC"}  # the same gull-wing outline under another name


def _alias_sig(sig: tuple[str, str, str, str] | None) -> tuple[str, str, str, str] | None:
    return None if sig is None else (_FAMILY_ALIAS.get(sig[0], sig[0]), *sig[1:])


def easyeda_package_sig(package: str) -> tuple[str, str, str, str] | None:
    """package_sig of an EasyEDA package name, or None when it is not a sized package."""
    m = _EASYEDA_PKG.match(package or "")
    if not m:
        return None
    family = _THIN.sub("", m.group(1))
    return (_FAMILY_ALIAS.get(family, family), m.group(2), f"{m.group(4)}x{m.group(3)}", m.group(5))


def glb_stem(footprint_part_id: str) -> str:
    return _STEM_BAD.sub("_", footprint_part_id.removeprefix("kicadgen:"))


class KicadIndex:
    name = "kicad_generated"

    def __init__(self, path: Path | str | None = None, glb_dir: Path | None = None) -> None:
        self.path = Path(path) if path is not None else DEFAULT_PATH
        if not self.path.is_file():
            raise FileNotFoundError(f"kicad index not built: {self.path}")
        self.glb_dir = glb_dir or GLB_DIR

    @classmethod
    def open(cls, path: Path | str | None = None) -> KicadIndex | None:
        try:
            return cls(path)
        except FileNotFoundError:
            return None

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        return con

    def rows(self, sql: str, args: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self._connect() as con:
            return con.execute(sql, args).fetchall()

    def __len__(self) -> int:
        return int(self.rows("SELECT count(*) AS n FROM kicad_parts")[0]["n"])

    def record(self, part_id: str) -> dict[str, Any]:
        rows = self.rows("SELECT row_json FROM kicad_parts WHERE part_id = ?", (part_id,))
        if not rows:
            raise KeyError(part_id)
        return json.loads(rows[0]["row_json"])

    def is_generated(self, part_id: str) -> bool:
        return part_id.startswith("kicadgen:")

    def has_model(self, part_id: str) -> bool:
        return bool(self.record(part_id).get("has_model"))

    def search(self, text: str, kind: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """FTS5 search (prefix on every word, bm25 with the name weighted 4x; any-word
        fallback). kind = "symbol" | "footprint" | None. Symbols whose footprint has a 3D model
        rank ahead of equally relevant ones without."""
        words = _WORD.findall(text)
        if not words:
            return []
        ids: list[str] = []
        for joiner in (" AND ", " OR "):
            expr = joiner.join(f'"{w}"*' for w in words)
            sql = (
                "SELECT f.part_id FROM kicad_fts f JOIN kicad_parts p USING (part_id) "
                "WHERE kicad_fts MATCH ?" + (" AND p.kind = ?" if kind else "") + " "
                "ORDER BY bm25(kicad_fts, 0.0, 4.0, 1.0) - 0.5 * p.has_model, f.part_id LIMIT ?"
            )
            args: tuple[Any, ...] = (expr, kind, limit) if kind else (expr, limit)
            ids = [r[0] for r in self.rows(sql, args)]
            if ids or len(words) == 1:
                break
        return [self.get_part(pid) for pid in ids]

    def get_part(self, part_id: str) -> dict[str, Any]:
        return part_from_record(self.record(part_id), self.model_record(part_id))

    def model_record(self, part_id: str) -> dict[str, Any] | None:
        """The footprint record whose 3D model draws this part: its own footprint's, else the
        same-package sibling's (model_footprint). None when neither has a model."""
        fp = self.footprint_record(part_id)
        if fp is None or fp.get("model_path"):
            return fp
        lender = self.model_footprint(f"{fp['lib']}:{fp['name']}")
        return self.record(lender) if lender is not None else None

    def footprint_record(self, part_id: str) -> dict[str, Any] | None:
        rec = self.record(part_id)
        if rec["kind"] == "footprint":
            return rec
        fp = rec.get("footprint_part")
        return self.record(fp) if fp else None

    def kicad(self, part_id: str) -> dict[str, Any]:
        """Local files for the board stage: {"footprint": {"path"}, "models": [{"path"}]}."""
        fp = self.footprint_record(part_id)
        if fp is None:
            return {"footprint": None, "models": []}
        lent = self.model_record(part_id)  # the same body's model from a sibling, if needed
        if lent is not None:
            fp = {**fp, "model_source": lent["model_source"], "model_path": lent["model_path"]}
        return {
            "footprint": {"path": str(_abs(fp["source"], fp["fp_path"]))},
            "models": (
                [{"path": str(_abs(fp["model_source"], fp["model_path"]))}]
                if fp.get("model_path")
                else []
            ),
        }

    def model_footprint(self, footprint: str) -> str | None:
        """The footprint part id whose 3D model draws footprint "Lib:Name": its own when it has
        one, else the closest library sibling with the same package (VQFN-16 3x3 borrows the
        WQFN-16 3x3 body) or a near-identical name, whose courtyard is the same size. None when
        nothing close enough has a model."""
        lib, _, name = footprint.partition(":")
        if not name:
            return None
        rows = self.rows(
            "SELECT part_id, name, has_model, source, row_json FROM kicad_parts"
            " WHERE kind = 'footprint' AND lib = ?",
            (lib,),
        )
        own = next((r for r in rows if r["name"] == name), None)
        if own is not None and own["has_model"]:
            return str(own["part_id"])
        body = set(_BODY.findall(name))
        sig = package_sig(name)
        ranked: list[tuple[int, float, Any]] = []
        for r in rows:
            if not r["has_model"] or r["name"] == name:
                continue
            ratio = SequenceMatcher(None, r["name"], name).ratio()
            if sig is not None and package_sig(r["name"]) == sig:
                # same family, pins, body and pitch: the same outside, whatever its pad
                ranked.append((0, -ratio, r))
            elif (
                ratio > SIBLING_SIMILARITY
                and (not body or body <= set(_BODY.findall(r["name"])))
                and _GRID.findall(r["name"]) == _GRID.findall(name)
            ):
                ranked.append((1, -ratio, r))  # another body size or pin row is another part
        ranked.sort(key=lambda t: t[:2])
        for tier, _, r in ranked:
            # a name alone is weak evidence: the outline must agree too
            if tier == 0 or (own is not None and _same_size(own, r)):
                return str(r["part_id"])
        return self._chip_lender(lib, name)

    def package_lender(self, package: str) -> str | None:
        """The KiCad footprint part id whose 3D model draws an LCSC part of this package, found
        by family, pin count, body and pitch alone: an EasyEDA footprint names no KiCad one, so
        model_footprint cannot reach it. None when no library footprint has the same outline."""
        sig = easyeda_package_sig(package)
        if sig is None:
            return None
        family = sig[0]
        names = {family, *(k for k, v in _FAMILY_ALIAS.items() if v == family)}
        for fam in sorted(names):
            rows = self.rows(
                "SELECT part_id, name, lib FROM kicad_parts WHERE kind = 'footprint'"
                " AND has_model AND name LIKE ?",
                (f"{fam}-{sig[1]}%",),
            )
            same = [r for r in rows if _alias_sig(package_sig(r["name"])) == sig]
            same.sort(key=lambda r: (not str(r["lib"]).startswith("Package_"), len(r["name"])))
            if same:
                return str(same[0]["part_id"])
        return None

    def _chip_lender(self, lib: str, name: str) -> str | None:
        """Another library's chip of the same size, for a chip footprint whose own library
        has no model of that size."""
        m = _CHIP.match(name)
        if m is None:
            return None
        for other, prefix in CHIP_LENDERS:
            if other == lib:
                continue
            rows = self.rows(
                "SELECT part_id FROM kicad_parts WHERE kind = 'footprint' AND lib = ?"
                " AND name = ? AND has_model",
                (other, f"{prefix}_{m.group(1)}"),
            )
            if rows:
                return str(rows[0]["part_id"])
        return None

    def glb_file(self, part_id: str) -> Path | None:
        fp = self.model_record(part_id)
        return self.glb_dir / f"{glb_stem(fp['part_id'])}.glb" if fp else None

    def ensure_glb(self, part_id: str) -> Path | None:
        """The part's GLB, converting its footprint on first use. None when the footprint has
        no 3D model or the conversion fails."""
        fp = self.model_record(part_id)
        if fp is None:
            return None
        out = self.glb_dir / f"{glb_stem(fp['part_id'])}.glb"
        with _glb_lock:
            if out.is_file() and out.stat().st_size > 0:
                return out
            return out if _convert(fp, out) else None


def _ensure_path() -> None:
    if str(SERVER) not in sys.path:
        sys.path.insert(0, str(SERVER))


def _abs(source: str, rel: str) -> Path:
    _ensure_path()
    from catalog_build.sources import SOURCES

    return SOURCES[source].root / rel


LEND_SIZE_TOLERANCE = 1.2  # per courtyard side: a sibling this close in size has the same body


def _same_size(a: Any, b: Any) -> bool:
    """Both footprints' courtyards agree within LEND_SIZE_TOLERANCE per side: a name match
    alone let the 9.5 mm Bourns 3386P borrow the 8 mm 3339P."""
    _ensure_path()
    from catalog_build.kicad_lib import read_footprint

    sides = []
    for r in (a, b):
        try:
            yard = read_footprint(_abs(r["source"], json.loads(r["row_json"])["fp_path"])).courtyard
        except (OSError, KeyError, ValueError):
            return False
        if not yard:
            return False
        sides.append(sorted(yard["max"][i] - yard["min"][i] for i in (0, 1)))
    pairs = zip(*sides, strict=True)
    return all(min(x, y) > 0 and max(x, y) / min(x, y) <= LEND_SIZE_TOLERANCE for x, y in pairs)


def _convert(fp: dict[str, Any], out: Path) -> bool:
    """One-footprint board through kicad-cli (the catalog build's own helper)."""
    _ensure_path()
    from catalog_build.kicad_index import resolve_model_file
    from catalog_build.kicad_lib import read_footprint
    from catalog_build.meshes import export_glb

    fp_file = _abs(fp["source"], fp["fp_path"])
    foot = read_footprint(fp_file)
    models = []
    for m in foot.models:
        if m.hidden:
            continue
        got = resolve_model_file(m.path, fp_file)
        if got:
            models.append((_abs(got[0], got[1]), m))
    if not models:
        return False
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bara_kicadgen_") as tmp:
        res = export_glb(Path(tmp), glb_stem(fp["part_id"]), foot, models, out)
    return bool(res.get("ok"))


KICAD_FP_URL = "https://gitlab.com/kicad/libraries/kicad-footprints/-/blob/master"
KICAD_SYM_URL = "https://gitlab.com/kicad/libraries/kicad-symbols/-/blob/master"


def kicad_source_url(part_id: str, lib: str) -> str | None:
    """Where the part lives in the official KiCad library, from its id (kicad:fp:Lib:Name)."""
    bits = part_id.split(":", 3)
    if len(bits) != 4 or bits[0] != "kicad" or not lib:
        return None
    if bits[1] == "fp":
        return f"{KICAD_FP_URL}/{lib}.pretty/{bits[3]}.kicad_mod"
    if bits[1] == "sym":
        return f"{KICAD_SYM_URL}/{lib}.kicad_sym"
    return None


def part_from_record(rec: dict[str, Any], fp: dict[str, Any] | None) -> dict[str, Any]:
    """A SPEC Part-shaped dict for an index row (generated tier, unverified)."""
    pid = rec["part_id"]
    title = rec["name"]
    summary = rec.get("descr") or None
    has_model = bool(rec.get("has_model"))
    licence = {
        "spdx": "CC-BY-SA-4.0" if rec["source"] == "kicad" else rec["licence"],
        "name": rec["licence"],
        "url": "https://www.kicad.org/libraries/license/" if rec["source"] == "kicad" else None,
        "commercial_ok": "yes",
        "copyleft": "yes" if rec["source"] == "kicad" else "unknown",
        "attribution_required": "no" if rec["source"] == "kicad" else "yes",
    }
    facets: dict[str, Any] = {
        "kind": "component",
        "has_mesh": has_model,
        "tier": TIER,
        "pin_count": rec["pins"] or rec["pads"],
        "licence_spdx": licence["spdx"],
        "commercial_ok": "yes",
        "interface_types": [],
        "kicad_lib": rec["lib"],
    }
    if rec.get("mount"):
        facets["mount"] = "smd" if rec["mount"] == "smd" else rec["mount"]
    asset = None
    if fp is not None and fp.get("model_path"):
        asset = {
            "asset_id": f"a_{glb_stem(fp['part_id'])}_glb",
            "kind": "glb",
            "role": "model",
            "content_type": "model/gltf-binary",
            "origin": "generated",
            "status": "lazy",
            "url": f"{GLB_URL}/{glb_stem(fp['part_id'])}.glb",
        }
    return {
        "part_id": pid,
        "key": pid,
        "kind": "component",
        "tier": TIER,
        "source": "kicad-generated",
        "display_name": f"{title} ({rec['lib']})"[:120],
        "name": title,
        "summary": summary,
        "descr": rec.get("descr", ""),
        "kw": rec.get("keywords", ""),
        "datasheet": rec.get("datasheet", ""),
        "footprint": f"kicad:{rec['footprint']}" if rec.get("footprint") else None,
        "functions": [{"function_id": rec["function"], "primary": True}],
        "interfaces": [],
        "facets": facets,
        "pins": rec.get("pin_names", [])[:60],
        "assets": [asset] if asset else [],
        "licence": licence,
        "provenance": {
            "extractor": "kicad_index",
            "route": "kicad_library",
            "verified": "none",
            "source": rec["source"],
            "library": rec["lib"],
            "licence": rec["licence"],
            **(
                {"source_url": url}
                if rec["source"] == "kicad" and (url := kicad_source_url(pid, rec["lib"]))
                else {}
            ),
        },
        "fp_ok": fp is not None,
        "pads_ok": bool(fp and fp.get("pads")),
        "status": "active",
    }
