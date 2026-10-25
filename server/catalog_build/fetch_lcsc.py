"""On-demand part fetcher: LCSC id -> symbol, footprint, 3D model -> GLB -> catalog record.

    uv run --with easyeda2kicad --with trimesh --with numpy \
        python -m catalog_build.fetch_lcsc C2848306 --function sense.humidity
    ... python -m catalog_build.fetch_lcsc --search "SHT40"
    ... python -m catalog_build.fetch_lcsc --mpn "SHT40-AD1B-R2" --function sense.humidity

The EasyEDA/LCSC library is reached through the easyeda2kicad package (no account). Everything
it returns is untrusted data: ids are validated, text fields are stripped of control characters
and capped, and every file name is derived from the validated LCSC id, never from fetched text.

The 3D model is exported with the same pipeline the catalog build uses (meshes.export_glb, which
runs kicad-cli, then bara.geometry.glbopt.compress). Output:
  data/catalog/fetched/fetched.jsonl        one catalog row per part (same shape as catalog.jsonl)
  data/catalog/fetched/src/<lcsc id>/       kicad_mod, kicad_sym, step as downloaded
  data/assets/parts/fetched/<lcsc id>.glb   served at /assets/parts/fetched/<lcsc id>.glb
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

SERVER = Path(__file__).resolve().parent.parent
FETCHED_DIR = SERVER / "data/catalog/fetched"
FETCHED_JSONL = FETCHED_DIR / "fetched.jsonl"
ASSET_DIR = SERVER / "data/assets/parts/fetched"

LCSC_RE = re.compile(r"^C\d{2,10}$")
DEFAULT_FUNCTION = "component.ic"
FUNCTION_RE = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")


class RateLimited(RuntimeError):
    """EasyEDA refused the request (HTTP 403 for every id): retrying soon only extends the block."""


def _refused(api: Any, lcsc_id: str) -> bool:
    """easyeda2kicad turns every failure into {}; ask once more to tell a block from a miss."""
    import urllib.error
    import urllib.request

    from easyeda2kicad.easyeda.easyeda_api import API_ENDPOINT

    req = urllib.request.Request(API_ENDPOINT.format(lcsc_id=lcsc_id), headers=api.headers)
    try:
        urllib.request.urlopen(req, timeout=30, context=api.ssl_context).close()  # noqa: S310
    except urllib.error.HTTPError as exc:
        return exc.code in (403, 429)
    except urllib.error.URLError:
        return False
    return False


LICENCE = {
    "spdx": "NOASSERTION",
    "name": "EasyEDA / LCSC community library (no licence stated)",
    "url": "https://www.lcsc.com/",
    "commercial_ok": "unknown",
    "attribution_required": "unknown",
    "copyleft": "unknown",
    "notes": (
        "Footprints and 3D models come from the EasyEDA/LCSC component library, contributed by "
        "users or manufacturers, with no open licence. Treat as restricted for redistribution "
        "until reviewed; do not ship the GLB in a public bundle without clearing the terms."
    ),
}


def clean(text: Any, limit: int = 200) -> str:
    """Untrusted text: drop control characters, collapse whitespace, cap length."""
    s = re.sub(r"[\x00-\x1f\x7f]+", " ", str(text or ""))
    return re.sub(r"\s+", " ", s).strip()[:limit]


def valid_lcsc(lcsc_id: str) -> str:
    if not LCSC_RE.match(lcsc_id or ""):
        raise ValueError(f"not an LCSC part number: {lcsc_id!r}")
    return lcsc_id


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:48] or "part"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------- search


def search(keyword: str, limit: int = 10) -> list[dict[str, Any]]:
    """JLCPCB parts search (anonymous, via easyeda2kicad). Returns cleaned candidate rows."""
    from easyeda2kicad.easyeda.easyeda_api import EasyedaApi

    raw = EasyedaApi().search_jlcpcb_components(clean(keyword, 80), page_size=limit)
    out = []
    for r in raw.get("results", []):
        if not LCSC_RE.match(str(r.get("lcsc", ""))):
            continue
        out.append(
            {
                "lcsc": r["lcsc"],
                "mpn": clean(r.get("model"), 80),
                "brand": clean(r.get("brand"), 80),
                "package": clean(r.get("package"), 80),
                "description": clean(r.get("description"), 160),
                "category": clean(r.get("category"), 80),
                "stock": int(r.get("stock") or 0),
                "datasheet": clean(r.get("datasheet"), 300),
            }
        )
    return out


def best_match(keyword: str, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Prefer an exact MPN hit with stock and a real manufacturer over JLCPCB house parts."""
    want = slug(keyword).replace("_", "")

    def score(r: dict[str, Any]) -> tuple[int, int, int, int]:
        mpn = slug(r["mpn"]).replace("_", "")
        return (
            mpn == want,
            mpn.startswith(want) or want in mpn,
            "jlcpcb" not in r["brand"].lower(),
            r["stock"] > 0,
        )

    ranked = sorted(rows, key=score, reverse=True)
    return ranked[0] if ranked and score(ranked[0])[1] else None


def best_stocked(rows: list[dict[str, Any]], function: str = "") -> dict[str, Any] | None:
    """For a description rather than an MPN: the most relevant hit that is in stock, preferring a
    real manufacturer over a house part (the search returns them in relevance order). Words for
    a panel or a cell also find its mating connector; only an interconnect block may take one."""
    connector_ok = function.split(".")[0] == "interconnect"
    live = [
        r
        for r in rows
        if r["stock"] > 0 and (connector_ok or "connector" not in r.get("category", "").lower())
    ]
    live.sort(key=lambda r: "jlcpcb" in r["brand"].lower())
    return live[0] if live else None


# --------------------------------------------------------------------------- record


def symbol_pins(symbol: Any) -> dict[str, str]:
    pins: dict[str, str] = {}
    for p in symbol.pins:
        num = clean(p.settings.spice_pin_number, 16)
        if num:
            pins[num] = clean(p.name.text, 40)
    return dict(sorted(pins.items(), key=lambda kv: (len(kv[0]), kv[0])))


def pad_features(fp: Any) -> list[dict[str, Any]]:
    feats = []
    for i, pad in enumerate(fp.pads):
        rec = pad.as_record()
        feats.append(
            {
                "id": f"pad{i}_{pad.number}" if pad.number else f"hole{i}",
                "kind": "pad" if pad.number else "hole",
                "subtype": pad.kind,
                "pos_mm": [rec["xy_mm"][0], rec["xy_mm"][1], 0.0],
            }
        )
    return feats


def _mount(footprint: Any) -> str:
    smd = footprint.pads and all(p.kind == "smd" for p in footprint.pads)
    return "smd" if smd else "tht"


def build_record(
    *,
    lcsc_id: str,
    info: dict[str, Any],
    function: str,
    footprint: Any,
    pins: dict[str, str],
    glb: dict[str, Any] | None,
    model_url: str | None = None,
) -> dict[str, Any]:
    """Pure conversion: cleaned LCSC info + parsed footprint + GLB facts -> catalog row.

    info keys: mpn, manufacturer, package, description, datasheet.
    glb: {"bytes", "sha256", "bbox_mm": {"min", "max"}, "nodes"} or None when no model.
    """
    valid_lcsc(lcsc_id)
    if not FUNCTION_RE.match(function):
        raise ValueError(f"bad function id: {function!r}")
    mpn = clean(info.get("mpn"), 80) or lcsc_id
    manufacturer = clean(info.get("manufacturer"), 80)
    package = clean(info.get("package"), 80)
    stem = f"{slug(mpn)}_{lcsc_id.lower()}"
    part_id = f"lcsc:{stem}"
    page = f"https://www.lcsc.com/product-detail/{lcsc_id}.html"
    api = f"https://easyeda.com/api/products/{lcsc_id}/components"

    facets: dict[str, Any] = {
        "has_mesh": glb is not None,
        "kind": "component",
        "licence_spdx": LICENCE["spdx"],
        "commercial_ok": LICENCE["commercial_ok"],
        "interface_types": [],
        "lcsc_id": lcsc_id,
        "pin_count": len(footprint.pin_numbers),
        "mount": "smd"
        if footprint.pads and all(p.kind == "smd" for p in footprint.pads)
        else "tht",
    }
    mech: dict[str, Any] = {"mating_features": pad_features(footprint)}
    if glb and glb.get("bbox_mm"):
        lo, hi = glb["bbox_mm"]["min"], glb["bbox_mm"]["max"]
        mech["bbox_mm"] = {"min": lo, "max": hi}
        facets["width_mm"] = round(hi[0] - lo[0], 3)
        facets["depth_mm"] = round(hi[1] - lo[1], 3)
        facets["height_mm"] = round(hi[2] - lo[2], 3)
    if package:
        facets["package"] = package

    asset: dict[str, Any] = {
        "asset_id": f"a_{stem}_glb",
        "kind": "glb",
        "role": "model",
        "url": f"/assets/parts/fetched/{lcsc_id}.glb",
        "content_type": "model/gltf-binary",
        "origin": "fetched",
        "status": "ready" if glb else "missing",
    }
    if glb:
        asset.update(bytes=glb["bytes"], sha256=glb["sha256"], nodes=glb.get("nodes", []))

    summary = clean(info.get("description"), 160) or None
    return {
        "part_id": part_id,
        "key": part_id,
        "family": "lcsc",
        "kind": "component",
        "display_name": f"{mpn} ({manufacturer})" if manufacturer else mpn,
        "name": mpn,
        "mpn": mpn,
        "manufacturer": manufacturer or None,
        "summary": summary,
        "descr": summary or "",
        "datasheet": clean(info.get("datasheet"), 300),
        "footprint": f"easyeda:{lcsc_id}",
        "fp_ok": True,
        "pads_ok": bool(footprint.pads),
        "pins": pins,
        "functions": [{"function_id": function, "primary": True}],
        "interfaces": [],
        "assets": [asset],
        "facets": facets,
        "mechanical": mech,
        "licence": dict(LICENCE),
        "provenance": {
            "route": "easyeda_lcsc",
            "extractor": "easyeda2kicad",
            "lcsc_id": lcsc_id,
            "source_url": page,
            "url": page,
            "api_url": api,
            "model_url": model_url,
            "licence": LICENCE["name"],
            "verified": "third_party" if glb else "none",
            "untrusted_source": True,
            "field_sources": {
                "/mechanical/bbox_mm": {
                    "extractor": "kicad_parse",
                    "source_url": model_url or page,
                    "verified": "geometry" if glb else "none",
                },
                "/functions": {"extractor": "human", "verified": "none"},
            },
        },
        "source": "easyeda-lcsc",
        "tags": [slug(function.split(".")[0])],
        "status": "active",
    }


def upsert(record: dict[str, Any], path: Path = FETCHED_JSONL) -> None:
    rows: dict[str, dict[str, Any]] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                rows[r["part_id"]] = r
    rows[record["part_id"]] = record
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows.values()))


# --------------------------------------------------------------------------- fetch


def fetch(lcsc_id: str, function: str = DEFAULT_FUNCTION) -> dict[str, Any]:
    """Download and convert one part. Returns the written record. Network + kicad-cli."""
    from easyeda2kicad.easyeda.easyeda_api import EasyedaApi
    from easyeda2kicad.easyeda.easyeda_importer import (
        Easyeda3dModelImporter,
        EasyedaFootprintImporter,
        EasyedaSymbolImporter,
    )
    from easyeda2kicad.kicad.export_kicad_3d_model import Exporter3dModelKicad
    from easyeda2kicad.kicad.export_kicad_footprint import ExporterFootprintKicad
    from easyeda2kicad.kicad.export_kicad_symbol import ExporterSymbolKicad

    from .kicad_lib import Model, read_footprint
    from .meshes import export_glb, glb_bounds, glb_node_names

    valid_lcsc(lcsc_id)
    api = EasyedaApi()
    cad = api.get_cad_data_of_component(lcsc_id=lcsc_id)
    if not cad:
        if _refused(api, lcsc_id):
            raise RateLimited(f"{lcsc_id}: EasyEDA is refusing requests (rate limit), retry later")
        raise RuntimeError(f"{lcsc_id}: EasyEDA returned no component")

    symbol = EasyedaSymbolImporter(easyeda_cp_cad_data=cad).get_symbol()
    ee_fp = EasyedaFootprintImporter(easyeda_cp_cad_data=cad).get_footprint()
    model3d = Easyeda3dModelImporter(
        easyeda_cp_cad_data=cad, download_raw_3d_model=True, api=api
    ).output
    wrl_exporter = Exporter3dModelKicad(model_3d=model3d)

    src = FETCHED_DIR / "src" / lcsc_id
    src.mkdir(parents=True, exist_ok=True)
    mod_path = src / f"{lcsc_id}.kicad_mod"
    ExporterFootprintKicad(footprint=ee_fp).export(
        footprint_full_path=str(mod_path), model_3d_path=str(src), model_3d_extension="wrl"
    )
    (src / f"{lcsc_id}.kicad_sym").write_text(
        ExporterSymbolKicad(symbol=symbol, version=20241209).export(footprint_lib_name=lcsc_id)
    )
    wrl = wrl_exporter.output.raw_wrl if wrl_exporter.output else None
    if wrl_exporter.output_step:
        (src / f"{lcsc_id}.step").write_bytes(wrl_exporter.output_step)

    fp = read_footprint(mod_path)
    glb_meta: dict[str, Any] | None = None
    note = "no 3D model in EasyEDA for this part"
    if wrl:
        # The WRL has the model offset baked in, so only the footprint's rotation/scale
        # entries must not be applied twice: use the identity placement.
        wrl_path = src / f"{lcsc_id}.wrl"
        wrl_path.write_text(wrl, encoding="utf-8")
        out = ASSET_DIR / f"{lcsc_id}.glb"
        with tempfile.TemporaryDirectory(prefix="bara_fetch_") as tmp:
            res = export_glb(Path(tmp), lcsc_id, None, [(wrl_path, Model(path=str(wrl_path)))], out)
            if res["ok"]:
                bounds = glb_bounds(res.get("plain") or out)
                names = glb_node_names(res.get("plain") or out)
                glb_meta = {
                    "bytes": out.stat().st_size,
                    "sha256": sha256(out),
                    "bbox_mm": bounds,
                    "nodes": names,
                }
            else:
                note = f"kicad-cli export failed: {res['log'][-200:]}"
        wrl_path.unlink(missing_ok=True)
    if glb_meta is None:
        sys.stderr.write(f"{lcsc_id}: no GLB ({note})\n")

    info = {
        "mpn": symbol.info.mpn or symbol.info.name,
        "manufacturer": symbol.info.manufacturer,
        "package": symbol.info.package,
        "description": symbol.info.description,
        "datasheet": symbol.info.datasheet,
    }
    uuid = getattr(model3d, "uuid", None)
    model_url = f"https://modules.easyeda.com/3dmodel/{clean(uuid, 64)}" if uuid else None
    record = build_record(
        lcsc_id=lcsc_id,
        info=info,
        function=function,
        footprint=fp,
        pins=symbol_pins(symbol),
        glb=glb_meta,
        model_url=model_url,
    )
    upsert(record)
    return record


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("lcsc_id", nargs="?", help="LCSC part number, e.g. C2848306")
    ap.add_argument("--function", default=DEFAULT_FUNCTION, help="catalog function id")
    ap.add_argument("--search", metavar="TEXT", help="list LCSC candidates for a part name or MPN")
    ap.add_argument("--mpn", metavar="TEXT", help="search, take the best match, fetch it")
    ap.add_argument(
        "--keyword", metavar="TEXT", help="a plain description: fetch the best stocked match"
    )
    args = ap.parse_args(argv)

    if args.search:
        for r in search(args.search):
            sys.stdout.write(
                f"{r['lcsc']:<12} {r['mpn']:<28} {r['brand'][:26]:<26} "
                f"{r['package'][:26]:<26} stock={r['stock']}\n"
            )
        return 0
    lcsc_id = args.lcsc_id
    if args.mpn:
        hit = best_match(args.mpn, search(args.mpn, 20))
        if hit is None:
            sys.stderr.write(f"no LCSC match for {args.mpn!r}\n")
            return 1
        lcsc_id = hit["lcsc"]
    if args.keyword:
        hit = best_stocked(search(args.keyword, 20), args.function)
        if hit is None:
            sys.stderr.write(f"no stocked LCSC part for {args.keyword!r}\n")
            return 1
        lcsc_id = hit["lcsc"]
    if not lcsc_id:
        ap.error("give an LCSC id, --search or --mpn")
    rec = fetch(lcsc_id, args.function)
    asset = rec["assets"][0]
    sys.stdout.write(
        f"{rec['part_id']} model={asset['status']} bbox={rec['mechanical'].get('bbox_mm')}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
