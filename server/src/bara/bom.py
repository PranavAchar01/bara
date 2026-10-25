"""Shopping BOM: every part of a finished build with where to buy it.

One row per distinct part (catalog part, board-only footprint such as a resistor, the custom
PCB and the printed case), with quantity, manufacturer and MPN from the part record, purchase
links (the LCSC product page when the record carries an LCSC id, else LCSC / Digi-Key / Mouser
searches by MPN), a unit price only when a record states one (never estimated), and the case as
a 3D-print file. Served as bom.csv and as JSON by GET /v1/builds/{id}/export.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import quote_plus

from bara.geometry import exports

Lookup = Callable[[str], dict[str, Any] | None]

COLUMNS = [
    "part_id",
    "kind",
    "name",
    "manufacturer",
    "mpn",
    "quantity",
    "unit_price_usd",
    "line_total_usd",
    "lcsc_url",
    "digikey_url",
    "mouser_url",
    "source_url",
    "file_url",
    "instances",
    "lib_id",
    "licence",
    "commercial_ok",
    "stock",
    "sourced_via",
]

_LCSC_ID = re.compile(r"(?:^|[_:])(c\d{3,})$", re.I)
_PAREN_NON_ASCII = re.compile(r"\s*[(（][^)）]*[^\x00-\x7f][^)）]*[)）]")


def lcsc_id(part_id: str, record: dict[str, Any] | None) -> str:
    prov = (record or {}).get("provenance") or {}
    cid = str(prov.get("lcsc_id") or "")
    if not cid:
        m = _LCSC_ID.search(part_id)
        cid = m.group(1) if m else ""
    return cid.upper()


def links(mpn: str, cid: str = "", name: str = "") -> dict[str, str]:
    """Purchase links: the exact LCSC page for an LCSC id, else searches by MPN (or name)."""
    term = mpn or name
    q = quote_plus(term) if term else ""
    return {
        "lcsc_url": (
            f"https://www.lcsc.com/product-detail/{cid}.html"
            if cid
            else f"https://www.lcsc.com/search?q={q}"
            if q
            else ""
        ),
        "digikey_url": f"https://www.digikey.com/en/products/result?keywords={q}" if q else "",
        "mouser_url": f"https://www.mouser.com/c/?q={q}" if q else "",
    }


def _price(record: dict[str, Any] | None) -> float | None:
    """A unit price the record states (USD), or None. Nothing is estimated."""
    if not record:
        return None
    for src in (record, record.get("facets") or {}, record.get("provenance") or {}):
        for key in ("unit_price_usd", "price_usd"):
            v = src.get(key)
            if isinstance(v, int | float) and v >= 0:
                return float(v)
    return None


def _maker(record: dict[str, Any] | None) -> str:
    return _PAREN_NON_ASCII.sub("", str((record or {}).get("manufacturer") or "")).strip()


def _row_lcsc(row: dict[str, Any]) -> str:
    m = re.search(r"/product-detail/(C\d+)\.html$", str(row.get("lcsc_url") or ""))
    return m.group(1).upper() if m else ""


def _row(**kw: Any) -> dict[str, Any]:
    row: dict[str, Any] = dict.fromkeys(COLUMNS, "")
    row.update(quantity=0, instances=[], unit_price_usd=None, line_total_usd=None)
    row.update(kw)
    return row


def bom(
    build: dict[str, Any],
    lookup: Lookup | None = None,
    quotes: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The shopping list of a build: {"rows": [...], "case_files": [...], "totals": {...}}.

    `quotes` maps LCSC ids to Apify scout part listings (price, stock, buy links); it defaults to
    the quotes the scout already cached. A price the part record states wins; a scouted price
    fills the rest and the row says so in `sourced_via`."""
    lookup = lookup or (lambda _pid: None)
    rows: dict[str, dict[str, Any]] = {}
    records: dict[str, dict[str, Any] | None] = {}
    for part in build.get("parts") or []:
        pid = part["part_id"]
        if pid not in records:
            try:
                records[pid] = lookup(pid)
            except KeyError:
                records[pid] = None
        rec = records[pid]
        card = part.get("card") or {}
        if pid not in rows:
            mpn = str((rec or {}).get("mpn") or "")
            name = str(card.get("display_name") or (rec or {}).get("display_name") or pid)
            cid = lcsc_id(pid, rec)
            prov = (rec or {}).get("provenance") or {}
            rows[pid] = _row(
                part_id=pid,
                kind="part",
                name=name,
                manufacturer=_maker(rec),
                mpn=mpn,
                unit_price_usd=_price(rec),
                source_url=card.get("source_url") or prov.get("source_url") or "",
                licence=card.get("licence_spdx", ""),
                commercial_ok=card.get("commercial_ok", ""),
                **links(mpn, cid, "" if mpn else name),
            )
        rows[pid]["quantity"] += int(part.get("quantity", 1) or 1)
        rows[pid]["instances"].append(part["instance_id"])

    if quotes is None:
        from bara.live import apify_scout

        quotes = apify_scout.cached_quotes(list(filter(None, map(_row_lcsc, rows.values()))))
    for row in rows.values():
        q = quotes.get(_row_lcsc(row))
        if not q:
            continue
        row["stock"] = q.get("stock", "")
        row["sourced_via"] = "Apify scout"
        if row["unit_price_usd"] is None and q.get("unit_price_usd") is not None:
            row["unit_price_usd"] = q["unit_price_usd"]
        row["mpn"] = row["mpn"] or q.get("mpn", "")

    boards = build.get("boards") or []
    loose: list[tuple[str, dict[str, Any]]] = []
    if any(b.get("footprints") for b in boards):
        for b in boards:
            for fp in b.get("footprints") or []:
                if not fp.get("instance_id"):  # mounted parts are already rows above
                    loose.append((str(b.get("board_id")), fp))
    else:
        for board_name, fp in exports._board_footprints(build):
            loose.append(
                (board_name, {"ref": fp["ref"], "lib_id": fp["lib_id"], "label": fp["value"]})
            )
    for board_id, fp in loose:
        lib_id, label = str(fp.get("lib_id") or ""), str(fp.get("label") or "")
        key = f"kicad:{lib_id}@{label}"
        if key not in rows:
            pkg = lib_id.split(":", 1)[-1]
            term = " ".join(x for x in (label, pkg) if x)
            rows[key] = _row(part_id=key, kind="board_part", name=label or pkg or key,
                             lib_id=lib_id, **links("", "", term))  # fmt: skip
        rows[key]["quantity"] += 1
        rows[key]["instances"].append(f"{board_id}:{fp.get('ref')}")

    build_id = build.get("build_id", "")
    for b in boards:
        if b.get("source") in ("generated", "custom", None) and b.get("board_id"):
            size = b.get("size_mm") or []
            dims = f" {size[0]:.0f} x {size[1]:.0f} mm" if len(size) >= 2 else ""
            rows[f"pcb:{b['board_id']}"] = _row(
                part_id=f"pcb:{b['board_id']}",
                kind="pcb",
                name=f"Custom PCB{dims}, {b.get('layers') or 2} layers (order from any PCB fab)",
                quantity=1,
                instances=[b["board_id"]],
                file_url=f"/v1/builds/{build_id}/export?format=kicad",
            )

    case_files = []
    for enc in build.get("enclosures") or []:
        if enc.get("kind") != "generated":
            continue
        assets = {a.get("kind"): a.get("url") for a in enc.get("assets") or []}
        files = {
            "stl": f"/v1/builds/{build_id}/export?format=stl",
            "3mf": f"/v1/builds/{build_id}/export?format=3mf",
        }
        mat = (enc.get("finish") or {}).get("name") or enc.get("material") or "plastic"
        rows[enc["enclosure_id"]] = _row(
            part_id=enc["enclosure_id"],
            kind="3d_print",
            name=f"Printed case (tray + bezel), {mat}",
            quantity=1,
            instances=[enc["enclosure_id"]],
            file_url=files["stl"],
        )
        printable = {k: v for k, v in assets.items() if k in ("stl", "3mf", "step")}
        case_files.append({"enclosure_id": enc["enclosure_id"], **files, "assets": printable})

    priced = 0
    total = 0.0
    for row in rows.values():
        if row["unit_price_usd"] is not None:
            row["line_total_usd"] = round(row["unit_price_usd"] * row["quantity"], 4)
            total += row["line_total_usd"]
            priced += 1
    return {
        "build_id": build_id,
        "columns": COLUMNS,
        "rows": list(rows.values()),
        "case_files": case_files,
        "totals": {
            "lines": len(rows),
            "sourced_via_apify": sum(r["sourced_via"] == "Apify scout" for r in rows.values()),
            "priced_lines": priced,
            "known_total_usd": round(total, 2) if priced else None,
        },
    }


def bom_csv(build: dict[str, Any], lookup: Lookup | None = None) -> str:
    data = bom(build, lookup)
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMNS)
    for row in data["rows"]:
        cells = []
        for col in COLUMNS:
            v = row[col]
            cells.append(";".join(v) if isinstance(v, list) else "" if v is None else v)
        writer.writerow(cells)
    return out.getvalue()
