"""Turn per-board results into a gate decision and the files GitLab reads: a Markdown note,
a JUnit report (MR test widget) and a Code Quality report (MR code quality widget)."""

from __future__ import annotations

import hashlib
from typing import Any
from xml.sax.saxutils import escape, quoteattr

_CQ_SEVERITY = {"error": "critical", "warning": "minor"}


def gate(board: dict[str, Any], policy: dict[str, Any]) -> list[str]:
    """Reasons this board fails the gate; empty means it passes."""
    g = policy["gate"]
    d, e, p = board["drc"], board["erc"], board["provenance"]
    why = []
    if d["errors"] > g["drc_errors"]:
        why.append(f"{d['errors']} DRC errors")
    if d["unconnected"] > g["unconnected"]:
        why.append(f"{d['unconnected']} unconnected items")
    if e["errors"] > g["erc_errors"]:
        why.append(f"{e['errors']} ERC errors")
    if p["blocked"] > g["blocked_parts"]:
        why.append(f"{p['blocked']} parts with a licence the policy does not allow")
    return why


def _where(v: dict[str, Any]) -> str:
    return f" at ({v['at_mm'][0]}, {v['at_mm'][1]}) mm" if v.get("at_mm") else ""


def markdown(run: dict[str, Any], max_items: int = 8) -> str:
    ok = all(not b["gate"] for b in run["boards"])
    lines = [
        f"## Tangible hardware gate: {'PASS' if ok else 'FAIL'}",
        "",
        f"{len(run['boards'])} boards checked with `{run['kicad']}`.",
        "",
        "| Board | DRC errors / warnings | ERC errors / warnings"
        " | Parts ok / review / blocked | Gate |",
        "|---|---|---|---|---|",
    ]
    for b in run["boards"]:
        d, e, p = b["drc"], b["erc"], b["provenance"]
        lines.append(
            f"| `{b['name']}` | {d['errors']} / {d['warnings']} | {e['errors']} / {e['warnings']}"
            f" | {p['ok']} / {p['review']} / {p['blocked']}"
            f" | {'pass' if not b['gate'] else 'fail: ' + ', '.join(b['gate'])} |"
        )
    for b in run["boards"]:
        errs = [
            (k, v)
            for k in ("drc", "erc")
            for v in b[k]["violations"]
            if v["severity"] == "error" and not v["environment"]
        ]
        review = [p for p in b["provenance"]["parts"] if p["verdict"] != "ok"]
        if not errs and not review:
            continue
        lines += ["", f"### `{b['name']}`"]
        for k, v in errs[:max_items]:
            lines.append(f"- **{k.upper()}** `{v['type']}`: {v['description']}{_where(v)}")
        if len(errs) > max_items:
            lines.append(f"- and {len(errs) - max_items} more errors in the job artifacts")
        if review:
            refs = ", ".join(f"{p['ref']} ({p['source']}, {p['licence']})" for p in review[:12])
            lines.append(f"- Licence needs a human look: {refs}")
    env = sum(b[k]["environment"] for b in run["boards"] for k in ("drc", "erc"))
    if env:
        lines += ["", f"{env} library-not-installed notices were left out of the gate."]
    return "\n".join(lines) + "\n"


def junit(run: dict[str, Any]) -> str:
    cases = []
    for b in run["boards"]:
        for k in ("drc", "erc"):
            r = b[k]
            errs = [v for v in r["violations"] if v["severity"] == "error" and not v["environment"]]
            body = "\n".join(f"{v['type']}: {v['description']}{_where(v)}" for v in errs)
            fail = (
                f"<failure message={quoteattr(f'{len(errs)} {k.upper()} errors')}>"
                f"{escape(body)}</failure>"
                if errs
                else ""
            )
            cases.append(f'<testcase classname="{b["name"]}" name="{k.upper()}">{fail}</testcase>')
        p = b["provenance"]
        blocked = [x for x in p["parts"] if x["verdict"] == "blocked"]
        fail = (
            f'<failure message="{len(blocked)} parts blocked by licence policy">'
            + escape(", ".join(f"{x['ref']} {x['licence']}" for x in blocked))
            + "</failure>"
            if blocked
            else ""
        )
        cases.append(f'<testcase classname="{b["name"]}" name="provenance">{fail}</testcase>')
    failures = sum(1 for c in cases if "<failure" in c)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<testsuite name="tangible-hardware" tests="{len(cases)}" failures="{failures}">\n'
        + "\n".join(cases)
        + "\n</testsuite>\n"
    )


def code_quality(run: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for b in run["boards"]:
        for k, file in (("drc", "main.kicad_pcb"), ("erc", "main.kicad_sch")):
            for v in b[k]["violations"]:
                if v["environment"]:
                    continue
                path = f"{b['path']}/{file}"
                desc = f"{k.upper()} {v['type']}: {v['description']}{_where(v)}"
                fp = hashlib.sha1(f"{path}|{desc}|{'|'.join(v['items'])}".encode()).hexdigest()
                out.append(
                    {
                        "description": desc,
                        "check_name": f"kicad.{k}.{v['type']}",
                        "fingerprint": fp,
                        "severity": _CQ_SEVERITY.get(v["severity"], "info"),
                        "location": {"path": path, "lines": {"begin": 1}},
                    }
                )
    return out
