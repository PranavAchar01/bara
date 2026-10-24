"""Find a real 3D model, by part number on LCSC/EasyEDA, for every catalog entry whose
footprint has no library model (and no same-package KiCad sibling to borrow one from).

    cd server
    uv run --with easyeda2kicad --with trimesh --with numpy \\
        python -m catalog_build.model_backfill [--only ID ...] [--dry-run]

Writes data/catalog/lcsc_models.json; `build meshes --only ID` then seats each model on its
footprint like any other. A part number only matches an LCSC row whose MPN contains it, so a
generic name never pulls in some other part's body. Network + kicad-cli: heavy lock.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from typing import Any

from bara.kicad_generated import KicadIndex

from . import fetch_lcsc
from .build import LCSC_MODELS_JSON, plan_entry
from .kicad_lib import read_footprint
from .manifest import ENTRIES, Entry

# how far the LCSC footprint's courtyard may differ from the catalog's, per side: a chip
# (SH1106) is not the module it drives (a 1.3 in OLED board)
SIZE_TOLERANCE = 1.5
# EasyEDA blocks an address after a short burst of component requests; pace them
FETCH_GAP_S = 20.0

# a part number: letters and digits together, at least 4 long
_PN = re.compile(r"^(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9.+-]{4,}$")
# footprint name tokens that describe geometry, not the part: P2.54mm, 1x02, 3x3mm, 2.8in
_GEOM = re.compile(
    r"^(?:P?\d+(?:\.\d+)?(?:x\d+(?:\.\d+)?)*(?:mm|in)?|\d+x\d+|EP.*|\d+P|\d+-?pins?|\d+mm.*)$", re.I
)


def part_numbers(e: Entry) -> list[str]:
    """Candidate part numbers, most specific first: the footprint name's tokens (vendor
    footprints carry the MPN, Vybronics_VZ30C1T8219732L), then the display name's."""
    fp_name = (e.footprint or "").rsplit(":", 1)[-1]
    seen: list[str] = []
    # a name's parentheses hold what the part contains, "C3 Mini (ESP32-C3)": not its body
    for text in (fp_name, re.sub(r"\([^)]*\)", " ", e.name)):
        for tok in sorted(re.split(r"[_\s:()/,]+", text), key=len, reverse=True):
            if _PN.match(tok) and not _GEOM.match(tok) and tok not in seen:
                seen.append(tok)
    return seen


def needs_model(e: Entry, index: KicadIndex | None) -> bool:
    if e.whole_board or e.mesh_from or e.models or not e.footprint:
        return False
    if e.part_id.startswith("mh:"):
        return False  # a mounting hole has no body
    p = plan_entry(e)
    if any(spec is None or spec.source != "lcsc" for _, _, spec in p.models):
        return False
    fp = e.footprint.removeprefix("kicad:")
    return index is None or index.model_footprint(fp) is None


def _sides(courtyard: dict[str, list[float]] | None) -> list[float] | None:
    if not courtyard:
        return None
    return sorted(courtyard["max"][i] - courtyard["min"][i] for i in (0, 1))


def same_size(e: Entry, lcsc_id: str) -> bool:
    """The fetched footprint's courtyard is the catalog footprint's within SIZE_TOLERANCE."""
    fp = plan_entry(e).fp
    ours = _sides(fp.courtyard if fp else None)
    mod = fetch_lcsc.FETCHED_DIR / "src" / lcsc_id / f"{lcsc_id}.kicad_mod"
    theirs = _sides(read_footprint(mod).courtyard) if mod.is_file() else None
    if ours is None or theirs is None:
        return False
    return all(
        0 < a and 0 < b and max(a, b) / min(a, b) <= SIZE_TOLERANCE
        for a, b in zip(ours, theirs, strict=True)
    )


def find(e: Entry) -> dict[str, Any] | None:
    for q in part_numbers(e):
        try:
            hit = fetch_lcsc.best_match(q, fetch_lcsc.search(q, 20))
        except Exception as exc:  # noqa: BLE001 - one bad search is a miss, not a stop
            sys.stderr.write(f"  search {q!r} failed: {exc}\n")
            continue
        if hit is not None:
            return {"lcsc": hit["lcsc"], "mpn": hit["mpn"], "query": q}
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", nargs="*", default=[])
    ap.add_argument("--dry-run", action="store_true", help="search only, fetch nothing")
    args = ap.parse_args(argv)
    found: dict[str, dict[str, str]] = (
        json.loads(LCSC_MODELS_JSON.read_text()) if LCSC_MODELS_JSON.is_file() else {}
    )
    index = KicadIndex.open()
    todo = [e for e in ENTRIES if (not args.only or e.part_id in args.only)]
    todo = [e for e in todo if e.part_id not in found and needs_model(e, index)]
    misses: list[str] = []
    for e in todo:
        hit = find(e)
        if hit is None:
            misses.append(f"{e.part_id} (tried {part_numbers(e)})")
            continue
        sys.stdout.write(f"{e.part_id}: {hit['query']} -> {hit['lcsc']} {hit['mpn']}\n")
        if args.dry_run:
            continue
        time.sleep(FETCH_GAP_S)
        try:
            fetch_lcsc.fetch(hit["lcsc"], e.function)
        except fetch_lcsc.RateLimited as exc:
            # every further request extends the block: stop, keep what was found
            misses.append(f"{e.part_id} ({exc}); stopped, rerun to continue")
            break
        except Exception as exc:  # noqa: BLE001
            misses.append(f"{e.part_id} ({hit['lcsc']} fetch failed: {exc})")
            continue
        step = fetch_lcsc.FETCHED_DIR / "src" / hit["lcsc"] / f"{hit['lcsc']}.step"
        if not step.is_file():
            misses.append(f"{e.part_id} ({hit['lcsc']} has no 3D model in EasyEDA)")
            continue
        if not same_size(e, hit["lcsc"]):
            misses.append(f"{e.part_id} ({hit['lcsc']} {hit['mpn']} is another size of body)")
            continue
        found[e.part_id] = {**hit, "path": f"{hit['lcsc']}/{hit['lcsc']}.step"}
        LCSC_MODELS_JSON.write_text(json.dumps(found, indent=1, sort_keys=True) + "\n")
    for m in misses:
        sys.stdout.write(f"no model: {m}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
