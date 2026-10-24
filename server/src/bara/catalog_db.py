"""Part catalog: SQLite + FTS5 over the SPEC 4.1 Parts built by server/catalog_build.

    db = CatalogDB()                       # server/data/catalog/catalog.sqlite
    db.get_part("mod:nice_nano_v2")        # full Part (KeyError when unknown)
    db.query(function="input.key", facets={"switch_family": "choc_v1"})
    db.search("oled 128x32")
    db.footprint_for(part_id), db.model_for(part_id)   # local KiCad files for the board stage

Facet matching (query): a list on either side matches on overlap; strings compare
case-insensitively; numbers within 1e-9. A facet value may also be a dict of operators,
{"gte": 3, "lte": 5} or {"ne": "mx"}. Parts without the facet never match.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "catalog" / "catalog.sqlite"

DDL = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE parts (
    part_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    display_name TEXT NOT NULL,
    primary_function TEXT,
    has_mesh INTEGER NOT NULL,
    part_json TEXT NOT NULL,
    kicad_json TEXT NOT NULL
);
CREATE TABLE part_functions (
    part_id TEXT NOT NULL, function_id TEXT NOT NULL, is_primary INTEGER NOT NULL
);
CREATE INDEX part_functions_fn ON part_functions (function_id);
CREATE TABLE part_interfaces (part_id TEXT NOT NULL, type TEXT NOT NULL, role TEXT NOT NULL);
CREATE INDEX part_interfaces_type ON part_interfaces (type);
CREATE TABLE part_facets (part_id TEXT NOT NULL, facet TEXT NOT NULL, value_json TEXT NOT NULL);
CREATE INDEX part_facets_key ON part_facets (facet);
CREATE TABLE designs (design_id TEXT PRIMARY KEY, design_json TEXT NOT NULL);
CREATE VIRTUAL TABLE parts_fts USING fts5(
    part_id UNINDEXED, name, body, tokenize = 'unicode61 remove_diacritics 2'
);
"""


def _search_text(part: dict[str, Any]) -> tuple[str, str]:
    name = " ".join(x for x in (part.get("display_name"), part.get("mpn"), part.get("name")) if x)
    bits: list[str] = [
        part["part_id"].replace(":", " ").replace("_", " "),
        part.get("summary") or "",
        part.get("descr") or "",
        part.get("kw") or "",
        part.get("manufacturer") or "",
        part.get("footprint") or "",
    ]
    for fn in part.get("functions", []):
        bits.append(fn["function_id"].replace(".", " ").replace("_", " "))
    for iface in part.get("interfaces", []):
        bits += [iface["type"].replace("_", " "), iface.get("label", "")]
    for key, value in (part.get("facets") or {}).items():
        vals = value if isinstance(value, list) else [value]
        bits += [str(v).replace("_", " ") for v in vals if isinstance(v, str)]
        if isinstance(value, bool) and value:
            bits.append(key.replace("_", " "))
    return name, " ".join(b for b in bits if b)


def write_catalog(
    path: Path,
    parts: Iterable[tuple[dict[str, Any], dict[str, Any]]],
    designs: Iterable[dict[str, Any]],
    meta: dict[str, Any],
) -> None:
    """Write a fresh catalog file (atomic replace). parts = (Part, kicad block) pairs."""
    tmp = path.with_suffix(".sqlite.tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    try:
        con.executescript(DDL)
        for part, kicad in parts:
            pid = part["part_id"]
            primary = next(
                (f["function_id"] for f in part["functions"] if f.get("primary")),
                part["functions"][0]["function_id"],
            )
            has_mesh = int(bool((part.get("facets") or {}).get("has_mesh")))
            con.execute(
                "INSERT INTO parts VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    pid,
                    part["kind"],
                    part["display_name"],
                    primary,
                    has_mesh,
                    json.dumps(part, sort_keys=True),
                    json.dumps(kicad, sort_keys=True),
                ),
            )
            con.executemany(
                "INSERT INTO part_functions VALUES (?, ?, ?)",
                [(pid, f["function_id"], int(bool(f.get("primary")))) for f in part["functions"]],
            )
            con.executemany(
                "INSERT INTO part_interfaces VALUES (?, ?, ?)",
                [(pid, i["type"], i["role"]) for i in part["interfaces"]],
            )
            con.executemany(
                "INSERT INTO part_facets VALUES (?, ?, ?)",
                [(pid, k, json.dumps(v)) for k, v in (part.get("facets") or {}).items()],
            )
            con.execute("INSERT INTO parts_fts VALUES (?, ?, ?)", (pid, *_search_text(part)))
        for design in designs:
            con.execute(
                "INSERT INTO designs VALUES (?, ?)",
                (design["design_id"], json.dumps(design, sort_keys=True)),
            )
        con.executemany(
            "INSERT INTO meta VALUES (?, ?)", [(k, json.dumps(v)) for k, v in meta.items()]
        )
        con.commit()
    finally:
        con.close()
    tmp.replace(path)


def _eq(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, int | float) and isinstance(b, int | float):
        return abs(float(a) - float(b)) < 1e-9
    return str(a).lower() == str(b).lower()


def _num(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def facet_matches(have: Any, want: Any) -> bool:
    if have is None:
        return False
    if isinstance(want, dict):
        for op, val in want.items():
            if op in ("gte", "lte", "gt", "lt"):
                h, w = _num(have), _num(val)
                if h is None or w is None:
                    return False
                ok = {"gte": h >= w, "lte": h <= w, "gt": h > w, "lt": h < w}[op]
                if not ok:
                    return False
            elif op == "ne":
                if facet_matches(have, val):
                    return False
            elif op in ("eq", "in"):
                if not facet_matches(have, val):
                    return False
            else:
                return False
        return True
    left = have if isinstance(have, list) else [have]
    right = want if isinstance(want, list) else [want]
    return any(_eq(a, b) for a in left for b in right)


_WORD = re.compile(r"[A-Za-z0-9]+")


class CatalogDB:
    """Read-only access to catalog.sqlite. Safe to share across threads (one connection
    per call)."""

    name = "catalog_db"

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else DEFAULT_PATH
        if not self.path.is_file():
            raise FileNotFoundError(f"catalog not built: {self.path}")
        self._parts: dict[str, dict[str, Any]] = {}
        self._kicad: dict[str, dict[str, Any]] = {}
        with self._connect() as con:
            for pid, pj, kj in con.execute(
                "SELECT part_id, part_json, kicad_json FROM parts ORDER BY has_mesh DESC, part_id"
            ):
                self._parts[pid] = json.loads(pj)
                self._kicad[pid] = json.loads(kj)
            self._designs = [
                json.loads(r[0])
                for r in con.execute("SELECT design_json FROM designs ORDER BY design_id")
            ]
            self.meta = {k: json.loads(v) for k, v in con.execute("SELECT key, value FROM meta")}

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)

    def __len__(self) -> int:
        return len(self._parts)

    def part_ids(self) -> list[str]:
        return list(self._parts)

    def get_part(self, part_id: str) -> dict[str, Any]:
        part = self._parts.get(part_id)
        if part is None:
            raise KeyError(part_id)
        return json.loads(json.dumps(part))

    def query(
        self,
        function: str | None = None,
        facets: dict[str, Any] | None = None,
        interfaces: list[str] | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Parts with this function (any, not only primary), every facet matching and every
        interface type present. Order: parts with a mesh first, then by part_id."""
        out: list[dict[str, Any]] = []
        want_ifaces = set(interfaces or [])
        for pid, part in self._parts.items():
            if function and function not in {f["function_id"] for f in part["functions"]}:
                continue
            if want_ifaces and not want_ifaces <= {i["type"] for i in part["interfaces"]}:
                continue
            have = part.get("facets") or {}
            if any(not facet_matches(have.get(k), v) for k, v in (facets or {}).items()):
                continue
            out.append(self.get_part(pid))
            if len(out) >= limit:
                break
        return out

    def search(self, text: str, limit: int = 20) -> list[dict[str, Any]]:
        """FTS5 full-text search (prefix match on every word, bm25 ranking with the name
        weighted 4x). Falls back to any-word matching when no part has every word."""
        words = _WORD.findall(text)
        if not words:
            return []
        ids: list[str] = []
        with self._connect() as con:
            for joiner in (" AND ", " OR "):
                expr = joiner.join(f'"{w}"*' for w in words)
                rows = con.execute(
                    "SELECT part_id FROM parts_fts WHERE parts_fts MATCH ? "
                    "ORDER BY bm25(parts_fts, 0.0, 4.0, 1.0), part_id LIMIT ?",
                    (expr, limit),
                ).fetchall()
                ids = [r[0] for r in rows]
                if ids or len(words) == 1:
                    break
        return [self.get_part(pid) for pid in ids]

    def designs(self) -> list[dict[str, Any]]:
        return json.loads(json.dumps(self._designs))

    def functions(self) -> list[str]:
        return sorted({f["function_id"] for p in self._parts.values() for f in p["functions"]})

    def facet_keys(self) -> list[str]:
        return sorted({k for p in self._parts.values() for k in (p.get("facets") or {})})

    def kicad(self, part_id: str) -> dict[str, Any]:
        """The part's KiCad block: footprint file, pads, courtyard, symbol, model files with
        KiCad offset/rotate/scale, and the mesh record."""
        if part_id not in self._kicad:
            raise KeyError(part_id)
        return json.loads(json.dumps(self._kicad[part_id]))

    def footprint_for(self, part_id: str) -> str | None:
        """Local .kicad_mod path of the part's footprint (None for model-only parts)."""
        fp = self.kicad(part_id).get("footprint")
        return fp["path"] if fp else None

    def model_for(self, part_id: str) -> str | None:
        """Local path of the part's first 3D model file (STEP/WRL), None when meshless."""
        models = self.kicad(part_id).get("models") or []
        return models[0]["path"] if models else None


_default: CatalogDB | None = None


def _db() -> CatalogDB:
    global _default
    if _default is None:
        _default = CatalogDB()
    return _default


def footprint_for(part_id: str) -> str | None:
    """Module-level helper on the default catalog (used by the board stage)."""
    return _db().footprint_for(part_id)


def model_for(part_id: str) -> str | None:
    return _db().model_for(part_id)
