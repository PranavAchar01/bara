"""Live demo: an Apify scout run feeding a build.

    PYTHONPATH=src nice -n 19 uv run python scripts/demo_apify_scout.py "handheld game console"

Runs the bara-hardware-scout Actor (on Apify when APIFY_TOKEN is set, in-process otherwise),
then does what a build does with the result: matches the scouted KiCad projects against the
device's function blocks (reference design), prices the parts they use, and prints the
shopping-list rows with their "Apify scout" credit. Set GITHUB_TOKEN to lift GitHub's
unauthenticated rate limit. Nothing is written except the engine's own caches.
"""

from __future__ import annotations

import argparse
import asyncio
import os

from bara import bom
from bara.live import apify_scout, reference_design


async def main(product: str, functions: list[str]) -> None:
    print(f"== Scouting open-source designs for {product!r} "
          f"({'Apify cloud' if os.environ.get('APIFY_TOKEN') else 'local run'})")  # fmt: skip
    res = await apify_scout.run(product)
    print(res.summary())
    for d in res.designs:
        print(f"  design  {d['repo']}  {d['licence']}  {d['fit']}  {d['stars']} stars  "
              f"{len(d['lcsc_ids'])} LCSC ids")  # fmt: skip
    for p in res.parts[:8]:
        print(f"  part    {p['lcsc_id']:<10} {p['mpn'][:28]:<28} {p['package'][:14]:<14} "
              f"${p['unit_price_usd']}  stock {p['stock']}  {p['product_url']}")  # fmt: skip

    print(f"\n== Reference design match against blocks: {', '.join(functions)}")
    ref = await reference_design.match(res.designs, functions)
    if ref is None:
        print("no scouted project had a readable board")
    else:
        print(f"{ref.repo} ({ref.licence}) builds {len(ref.matched)}/{len(functions)} blocks: "
              f"{', '.join(ref.matched) or 'none'}; reusable={ref.reusable}")  # fmt: skip

    print("\n== Shopping list (parts the scouted designs use)")
    quotes = {p["lcsc_id"]: p for p in res.parts}
    build = {
        "build_id": "b_demo",
        "parts": [
            {"part_id": f"lcsc_{cid}", "instance_id": f"i_{cid}", "quantity": 1,
             "card": {"display_name": q["description"][:40] or q["mpn"]}}  # fmt: skip
            for cid, q in list(quotes.items())[:6]
        ],
    }
    for row in bom.bom(build, None, quotes)["rows"]:
        print(f"  {row['part_id']:<16} {row['mpn'][:24]:<24} ${row['unit_price_usd']}  "
              f"stock {row['stock']}  {row['lcsc_url']}  [{row['sourced_via']}]")  # fmt: skip
    apify_scout.record("b_demo", res, len(quotes))
    print("\n== Numbers so far:", apify_scout.totals())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("product", nargs="?", default="handheld game console")
    ap.add_argument("--functions", default="compute.mcu,display.tft,input.button,power.charger")
    a = ap.parse_args()
    asyncio.run(main(a.product, a.functions.split(",")))
