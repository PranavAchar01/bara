# Open Hardware Scout

Describe a device ("handheld game console") or a part function ("USB-C battery charger") and get
back what already exists in the open: public GitHub projects that contain a real KiCad board, with
the licence detected, the board, schematic and case files, the README, the LCSC part numbers the
project uses, and live price and stock for those parts.

It is the first step of every build in [Bara](../../README.md), a tool that builds a device from
real open-source hardware and parts.

## Where and how Apify is used in Bara

1. A build starts with a run of this Actor for the requested device (the "Scouting open-source
   designs" step in the build log). With `APIFY_TOKEN` set, the engine starts the Actor on the
   Apify platform through the Apify API client and reads its dataset; without a token the same
   code runs in-process.
2. The scouted designs lead the retrieval evidence the device concept is written from, and the
   reuse step lists them as the closest open designs.
3. Each design's board is read and matched to the device's function blocks. A reusable licence
   with enough coverage makes its footprints the preferred ones when parts are chosen.
4. After the build, the LCSC parts it uses are priced through the Actor and the shopping list
   (BOM csv / json) carries price, stock and buy links, marked "sourced via Apify scout".
5. Per-build numbers (designs found, parts priced, public pages crawled) are kept and served at
   `GET /v1/apify/stats`.

## Input

| field | meaning |
| --- | --- |
| `query` | device or part function in plain words |
| `lcscIds` | extra LCSC part numbers to price (`C14267`) |
| `maxRepos` | open projects to return (default 6) |
| `maxPartsFromDesigns` | LCSC numbers per design to price (default 20) |

Set a `GITHUB_TOKEN` environment variable on the Actor to lift GitHub's unauthenticated rate limit
(60 requests an hour). It is optional.

## Output

One dataset item per result, `type` is `design`, `part` or `stats`:

```json
{"type": "design", "repo": "https://github.com/…", "licence": "MIT", "licence_source": "github",
 "kicad_pcb": "hw/board.kicad_pcb", "enclosure_files": ["case/shell.stl"], "fit": "close",
 "stars": 12, "readme": "…", "lcsc_ids": ["C14267"]}
{"type": "part", "lcsc_id": "C14267", "mpn": "CH340G", "package": "SOP-16",
 "unit_price_usd": 0.5662, "stock": 49238, "product_url": "https://www.lcsc.com/product-detail/C14267.html",
 "buy_urls": {"lcsc": "…", "digikey": "…", "mouser": "…"}}
{"type": "stats", "pages_fetched": 53, "designs": 6, "parts": 5}
```

## What it reads, and what it does not

Public pages and public APIs only, read without a login: GitHub's public repository search and
file tree, `raw.githubusercontent.com` (README, LICENSE, BOM files) and the public jlcsearch part
index (a mirror of the LCSC catalogue). Nothing behind a login or paywall is requested, no personal
data is collected (repository owners appear only inside a public repo URL), and fetched text is
parsed with regular expressions, never executed. Forks, archived and private repositories and
parts libraries are skipped. The licence is whatever GitHub detects, else sniffed from the LICENSE
file, else "none stated" (such a design is compared, never reused).

## Run it locally

```
cd actors/bara-hardware-scout
mkdir -p storage/key_value_stores/default
echo '{"query": "handheld game console", "maxRepos": 4}' > storage/key_value_stores/default/INPUT.json
apify run                      # with the Apify CLI, or:
APIFY_LOCAL_STORAGE_DIR=$PWD/storage python -m src   # with `pip install -r requirements.txt`
```

Results land in `storage/datasets/default/`.
