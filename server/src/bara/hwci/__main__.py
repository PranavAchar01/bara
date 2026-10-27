"""Tangible hardware gate.

python -m bara.hwci check hardware/boards --policy hardware/policy.json --out hw-report
python -m bara.hwci fab   hardware/boards --out hw-fab
python -m bara.hwci post  hw-report/results.json
python -m bara.hwci smoke https://example.gitlab.io/tangible/ --expect Tangible
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

from . import kicad, provenance, report
from .gitlab import GitLab


def _say(text: str) -> None:
    sys.stdout.write(f"{text}\n")


def boards(root: Path) -> list[Path]:
    return sorted(p.parent for p in root.glob("*/main.kicad_pcb"))


def run_check(root: Path, policy: dict[str, Any]) -> dict[str, Any]:
    out = []
    for b in boards(root):
        t0 = time.monotonic()
        res: dict[str, Any] = {
            "name": b.name,
            "path": str(b),
            "drc": kicad.drc(b),
            "erc": kicad.erc(b),
            "stats": kicad.stats(b),
            "provenance": provenance.check(b, policy),
        }
        res["gate"] = report.gate(res, policy)
        res["seconds"] = round(time.monotonic() - t0, 2)
        out.append(res)
    return {"kicad": kicad.version(), "boards": out, "passed": all(not b["gate"] for b in out)}


def cmd_check(a: argparse.Namespace) -> int:
    policy = provenance.load_policy(a.policy)
    run = run_check(a.root, policy)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "results.json").write_text(json.dumps(run, indent=1))
    (a.out / "gate.md").write_text(report.markdown(run))
    (a.out / "junit.xml").write_text(report.junit(run))
    (a.out / "gl-code-quality-report.json").write_text(json.dumps(report.code_quality(run)))
    hb = a.out / "hbom"
    hb.mkdir(exist_ok=True)
    for b in run["boards"]:
        bom = provenance.cyclonedx(b["name"], b["provenance"]["parts"])
        (hb / f"{b['name']}.cdx.json").write_text(json.dumps(bom, indent=1))
    for b in run["boards"]:
        d, e = b["drc"], b["erc"]
        _say(
            f"{b['name']:>14}: DRC {d['errors']}E/{d['warnings']}W, ERC {e['errors']}E/"
            f"{e['warnings']}W, parts {b['provenance']['ok']} ok {b['provenance']['review']}"
            f" review {b['provenance']['blocked']} blocked -> "
            + ("pass" if not b["gate"] else "FAIL (" + ", ".join(b["gate"]) + ")")
        )
    _say("gate: " + ("PASS" if run["passed"] else "FAIL"))
    return 0 if run["passed"] or a.no_fail else 1


def cmd_fab(a: argparse.Namespace) -> int:
    for b in boards(a.root):
        files = kicad.fab(b, a.out / f"{b.name}-fab.zip")
        _say(f"{b.name}: {len(files)} files -> {a.out / (b.name + '-fab.zip')}")
    return 0


def cmd_post(a: argparse.Namespace) -> int:
    run = json.loads(a.results.read_text())
    body = report.markdown(run)
    gl = GitLab.from_env()
    if gl is None:
        _say("TANGIBLE_GITLAB_TOKEN not set: printing the note instead\n")
        _say(body)
        return 0
    mr = os.environ.get("CI_MERGE_REQUEST_IID")
    if mr:
        _say(gl.upsert_mr_note(mr, body))
        gl.label_mr(mr, run["passed"])
    elif not run["passed"] and os.environ.get("CI_COMMIT_BRANCH") == os.environ.get(
        "CI_DEFAULT_BRANCH"
    ):
        for b in (x for x in run["boards"] if x["gate"]):
            url = gl.open_issue(
                f"Hardware gate failing on {b['name']}",
                f"Pipeline {os.environ.get('CI_PIPELINE_URL', '')}\n\n{body}",
                "hardware::fail,tangible",
            )
            _say(f"{b['name']}: {url}")
    return 0


def cmd_smoke(a: argparse.Namespace) -> int:
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(a.url, timeout=20) as r:
            status, text = r.status, r.read().decode("utf-8", "replace")
    except OSError as exc:
        status, text = 0, str(exc)
    ms = round((time.monotonic() - t0) * 1000)
    ok = status == 200 and a.expect in text
    seen = "found" if a.expect in text else "missing"
    _say(f"{a.url}: HTTP {status} in {ms} ms, marker {seen}")
    if not ok:
        gl = GitLab.from_env()
        if gl:
            _say(gl.open_issue(f"Deployment down: {a.url}",
                                f"Smoke check got HTTP {status} after {ms} ms.",
                                "incident,tangible"))  # fmt: skip
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bara.hwci")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("root", type=Path)
    c.add_argument("--policy", type=Path, default=Path("hardware/policy.json"))
    c.add_argument("--out", type=Path, default=Path("hw-report"))
    c.add_argument("--no-fail", action="store_true", help="always exit 0 (report only)")
    f = sub.add_parser("fab")
    f.add_argument("root", type=Path)
    f.add_argument("--out", type=Path, default=Path("hw-fab"))
    p = sub.add_parser("post")
    p.add_argument("results", type=Path)
    s = sub.add_parser("smoke")
    s.add_argument("url")
    s.add_argument("--expect", default="Tangible")
    a = ap.parse_args(argv)
    return {"check": cmd_check, "fab": cmd_fab, "post": cmd_post, "smoke": cmd_smoke}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
