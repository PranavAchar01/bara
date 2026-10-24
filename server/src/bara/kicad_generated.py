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
import re
import sqlite3
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

SERVER = Path(__file__).resolve().parents[2]
DEFAULT_PATH = SERVER / "data" / "catalog" / "kicad_index.sqlite"
GLB_DIR = SERVER / "data" / "assets" / "parts" / "kicad_gen"
GLB_URL = "/assets/parts/kicad_gen"
TIER = "kicad_generated"

_WORD = re.compile(r"[A-Za-z0-9]+")
_STEM_BAD = re.compile(r"[^A-Za-z0-9._-]")
_glb_lock = threading.Lock()


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
        return part_from_record(self.record(part_id), self.footprint_record(part_id))

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
        return {
            "footprint": {"path": str(_abs(fp["source"], fp["fp_path"]))},
            "models": (
                [{"path": str(_abs(fp["model_source"], fp["model_path"]))}]
                if fp.get("model_path")
                else []
            ),
        }

    def glb_file(self, part_id: str) -> Path | None:
        fp = self.footprint_record(part_id)
        return self.glb_dir / f"{glb_stem(fp['part_id'])}.glb" if fp else None

    def ensure_glb(self, part_id: str) -> Path | None:
        """The part's GLB, converting its footprint on first use. None when the footprint has
        no 3D model or the conversion fails."""
        fp = self.footprint_record(part_id)
        if fp is None or not fp.get("model_path"):
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
        },
        "fp_ok": fp is not None,
        "pads_ok": bool(fp and fp.get("pads")),
        "status": "active",
    }
