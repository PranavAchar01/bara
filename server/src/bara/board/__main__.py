"""`uv run python -m bara.board BRIEF.json [--parts PARTS.json] [--json OUT.json]`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import build_board


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bara.board")
    ap.add_argument("brief", type=Path)
    ap.add_argument("--parts", type=Path, default=None)
    ap.add_argument("--json", type=Path, default=None, help="write the full result here")
    ap.add_argument("--timeout", type=float, default=300.0, help="router timeout, seconds")
    args = ap.parse_args(argv)

    brief = json.loads(args.brief.read_text())
    parts = json.loads(args.parts.read_text()) if args.parts else []

    def progress(msg: str, frac: float | None) -> None:
        pct = "" if frac is None else f"{frac * 100:5.1f}% "
        sys.stderr.write(f"{pct}{msg}\n")

    res = build_board(brief, parts, progress=progress, route_timeout_s=args.timeout)
    if args.json:
        args.json.write_text(json.dumps(res, indent=1))
    out = sys.stdout
    for line in res["log"]:
        out.write(f"  log: {line}\n")
    for bd in res["boards"]:
        d = bd["drc"]
        t = bd["timings"]
        out.write(
            f"{bd['name']:>14}: {len(bd['placements'])} parts, ctrl={bd['controller']}, "
            f"route {t.get('route_s')} s, total {t.get('total_s')} s, "
            f"DRC errors={d['errors']} warnings={d['warnings']} unconnected={d['unconnected']}"
            f"{' (cached)' if bd['cache_hit'] else ''}\n"
            f"{'':>16}pcb {bd['kicad_pcb']}\n{'':>16}glb {bd['glb_url']} "
            f"({bd['glb']['bytes']} bytes)\n"
        )
    out.write(f"total {res['timings']['total_s']} s\n")
    bad = [bd for bd in res["boards"] if bd["drc"]["errors"] or bd["drc"]["unconnected"]]
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
