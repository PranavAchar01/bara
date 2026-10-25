"""Run KiCad's own DRC (with schematic parity), ERC and board statistics over saved builds and
print a summary table: pass rates, mean violations and mean check time.

    uv run python scripts/bench_kicad.py [-n 20] [--data DIR] [--ids b_x,b_y] [--json out.json]

It reads the Library on disk (newest finished builds first) and each build's routed boards in
data/cache/boards. Saved files are never written: every board is checked on a copy.
"""

# ruff: noqa: T201  (a command-line report: printing is its output)

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from statistics import mean
from typing import Any

from bara.board import kicad_checks as KC
from bara.config import load_settings

BOARD_FILES = ("main.kicad_pcb", "main.kicad_sch", "main.kicad_pro")


def saved_builds(data: Path, n: int, ids: list[str] | None) -> list[dict[str, Any]]:
    rows = []
    for meta in (data / "library").glob("b_*.meta.json"):
        try:
            row = json.loads(meta.read_text())
        except ValueError:
            continue
        if ids and row.get("build_id") not in ids:
            continue
        if not ids and (row.get("status") != "done" or row.get("hidden_at")):
            continue
        rows.append(row)
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return rows if ids else rows[:n]


def board_dirs(data: Path, build_id: str) -> list[Path]:
    """The routed board folders a build's last board.updated events name."""
    keys: dict[str, str] = {}
    events = data / "library" / f"{build_id}.jsonl"
    for line in events.read_text().splitlines() if events.exists() else []:
        if '"board.updated"' not in line or '"cache_key"' not in line:
            continue
        board = json.loads(line).get("payload", {}).get("board", {})
        key = (board.get("routing") or {}).get("cache_key")
        if key:
            keys[str(board.get("board_id"))] = key
    out = []
    for key in keys.values():
        work = data / "cache" / "boards" / key
        if (work / "main.kicad_pcb").exists() and work not in out:
            out.append(work)
    return out


def check_copy(work: Path, scratch: Path) -> dict[str, Any]:
    dst = scratch / work.name
    dst.mkdir(parents=True, exist_ok=True)
    for name in BOARD_FILES:
        if (work / name).exists():
            shutil.copyfile(work / name, dst / name)
    sch = dst / "main.kicad_sch"
    return KC.run_checks(dst / "main.kicad_pcb", sch if sch.exists() else None, use_cache=False)


def _errors(rep: dict[str, Any], tool: str) -> int | None:
    sec = rep.get(tool)
    return None if not sec else int(sec["counts"].get("error", 0))


def _ew(rep: dict[str, Any], tool: str) -> str:
    sec = rep.get(tool)
    return "-" if not sec else f"{sec['counts']['error']}/{sec['counts']['warning']}"


def _rate(values: list[bool]) -> str:
    if not values:
        return "n/a"
    return f"{100 * sum(values) / len(values):.0f}% ({sum(values)}/{len(values)})"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("-n", type=int, default=10, help="newest finished builds to check")
    ap.add_argument("--data", type=Path, default=None, help="server data dir (has library/)")
    ap.add_argument("--ids", default="", help="comma-separated build ids instead of the newest")
    ap.add_argument("--json", type=Path, default=None, help="also write every report here")
    args = ap.parse_args()
    if KC.find_kicad_cli() is None:
        print("KiCad not installed: kicad-cli was not found", file=sys.stderr)
        return 2
    data = args.data or load_settings().data_dir
    if not (data / "library").is_dir():
        print(f"no library under {data}; pass --data", file=sys.stderr)
        return 2
    builds = saved_builds(data, args.n, [i for i in args.ids.split(",") if i] or None)
    rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="bench-kicad-") as tmp:
        for b in builds:
            for work in board_dirs(data, b["build_id"]):
                rep = check_copy(work, Path(tmp))
                rows.append(
                    {
                        "build_id": b["build_id"],
                        "prompt": str(b.get("prompt") or "")[:28],
                        "board": work.name,
                        "report": rep,
                    }
                )
    ok = [r for r in rows if r["report"].get("status") == "ok"]
    cols = ("DRC e/w", "ERC e/w", "parity", "viol", "s")
    head = f"{'build':16} {'prompt':28} {'board':10} " + " ".join(f"{c:>8}" for c in cols)
    print(head)
    print("-" * len(head))
    for r in rows:
        rep = r["report"]
        lead = f"{r['build_id']:16} {r['prompt']:28} {r['board'][:10]:10}"
        if rep.get("status") != "ok":
            print(lead, rep.get("message") or rep.get("status"))
            continue
        cells = [_ew(rep, "drc"), _ew(rep, "erc")]
        par = rep.get("parity")
        cells.append("-" if not par else str(sum(par["counts"].values())))
        cells += [str(rep["total_violations"]), f"{rep['timings']['total_s']:.1f}"]
        print(lead, " ".join(f"{c:>8}" for c in cells))
    print()
    print(f"builds {len(builds)}, boards {len(rows)}, checked {len(ok)}")
    for tool, label in (("drc", "DRC"), ("erc", "ERC"), ("parity", "parity")):
        passed = [r["report"][tool]["passed"] for r in ok if r["report"].get(tool)]
        print(f"{label:7} pass rate  {_rate(passed)}")
    if ok:
        print(f"mean violations   {mean(r['report']['total_violations'] for r in ok):.1f}")
        errs = [e for r in ok for t in ("drc", "erc") if (e := _errors(r["report"], t)) is not None]
        print(f"mean errors       {mean(errs) if errs else 0:.1f}")
        print(f"mean check time   {mean(r['report']['timings']['total_s'] for r in ok):.2f} s")
        for k in ("drc_s", "erc_s", "stats_s"):
            vals = [r["report"]["timings"][k] for r in ok if k in r["report"]["timings"]]
            if vals:
                print(f"  {k:15} {mean(vals):.2f} s")
    if args.json:
        args.json.write_text(json.dumps(rows, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
