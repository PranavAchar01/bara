"""Evaluate the fit check on synthetic photos with known ground truth.

    uv run python scripts/vision_eval.py OUT_DIR [--lambda URL]

Writes OUT_DIR/results.json, OUT_DIR/summary.md and a few annotated examples. Every scene is
seeded, so a rerun gives the same numbers. With --lambda it also times the same photos through
the AWS Lambda endpoint against the in-process run.
"""

from __future__ import annotations

import base64
import json
import statistics
import sys
import time
from pathlib import Path

import httpx
import numpy as np

from bara.vision import agent
from bara.vision.measure import measure
from bara.vision.synth import make_scene

SIZES = [(40, 30), (60, 40), (80, 80), (95, 45), (120, 70), (150, 60), (170, 110)]
KINDS = ["rectangle", "round"]
TILTS = [0.05, 0.12, 0.18, 0.25]


def pct(xs: list[float], q: float) -> float:
    return float(np.percentile(xs, q)) if xs else float("nan")


def main() -> None:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    lam = sys.argv[sys.argv.index("--lambda") + 1] if "--lambda" in sys.argv else None
    rows = []
    seed = 0
    for w, d in SIZES:
        for kind in KINDS:
            for tilt in TILTS:
                seed += 1
                rng = np.random.default_rng(seed)
                s = make_scene(rng, w, d, kind, tilt=tilt)
                r = measure(s.jpg, annotate=seed % 14 == 1)
                o = r["object"] or {}
                row = {
                    "seed": seed,
                    "w": w,
                    "d": d,
                    "kind": kind,
                    "tilt": tilt,
                    "status": r["status"],
                    "ms": r["ms"],
                    "strategy": next((t["strategy"] for t in r["tried"] if not t["issues"]), None),
                    "got_w": o.get("width_mm"),
                    "got_d": o.get("depth_mm"),
                    "got_kind": o.get("kind"),
                }
                if r["status"] == "ok":
                    row["err_w"] = round(abs(o["width_mm"] - w), 2)
                    row["err_d"] = round(abs(o["depth_mm"] - d), 2)
                    row["rel"] = round(max(row["err_w"] / w, row["err_d"] / d), 4)
                rows.append(row)
                if r.get("annotated_jpg_b64"):
                    (out / f"example_{seed:03d}_{kind}_{w}x{d}.jpg").write_bytes(
                        base64.b64decode(r["annotated_jpg_b64"])
                    )
                    (out / f"example_{seed:03d}_photo.jpg").write_bytes(s.jpg)

    # failure cases: the agent must ask for a retake, never return a size
    fail_cases = []
    for i in range(10):
        rng = np.random.default_rng(1000 + i)
        for name, kw in (
            ("no_marker", {"marker": False}),
            ("cut_off", {"center_mm": (505.0, 210.0)}),
            ("two_objects", {"second": (110.0, 70.0)}),
        ):
            s = make_scene(rng, 110, 70, **kw)
            res = agent.decide(s.jpg)
            fail_cases.append(
                {
                    "case": name,
                    "seed": 1000 + i,
                    "status": res["measurement"]["status"],
                    "action": res["action"]["kind"],
                    "caught": res["action"]["kind"] == "retake",
                    "message": res["message"],
                }
            )

    # agent decisions: the same scenes against an open case a few mm either side of the room
    # left after clearance. The right action comes from the true size, the agent's from the photo.
    decisions = []
    seed = 0
    for w, d in SIZES:
        for kind in KINDS:
            for tilt in TILTS:
                seed += 1
                rng = np.random.default_rng(seed)
                s = make_scene(rng, w, d, kind, tilt=tilt)
                off = float(np.random.default_rng(5000 + seed).uniform(-8, 8))
                case = [round(w - 4 + off, 1), round(d - 4 + off, 1), 25.0]
                truth_fits, _ = agent._fits((case[0], case[1]), (w - 4, d - 4))
                res = agent.decide(s.jpg, enclosure={"enclosure_id": "e", "outer_size_mm": case})
                got = res["action"]["kind"]
                want = "none" if truth_fits else "prompt"
                decisions.append(
                    {
                        "seed": seed,
                        "margin_mm": round(-off, 1),
                        "want": want,
                        "got": got,
                        "outcome": "correct" if got == want else ("retake" if got == "retake" else "wrong"),
                        "trace": res["steps"],
                    }
                )

    ok = [r for r in rows if r["status"] == "ok"]
    errs = [e for r in ok for e in (r["err_w"], r["err_d"])]
    rel = [r["rel"] for r in ok]
    kind_ok = [r for r in ok if (r["got_kind"] in ("round", "oval")) == (r["kind"] == "round")]
    by_tilt = {
        str(t): {
            "n": sum(1 for r in rows if r["tilt"] == t),
            "ok": sum(1 for r in ok if r["tilt"] == t),
            "mae_mm": round(
                statistics.mean(
                    [e for r in ok if r["tilt"] == t for e in (r["err_w"], r["err_d"])]
                    or [float("nan")]
                ),
                2,
            ),
        }
        for t in TILTS
    }
    summary = {
        "scenes": len(rows),
        "measured_ok": len(ok),
        "mae_mm": round(statistics.mean(errs), 2),
        "p95_mm": round(pct(errs, 95), 2),
        "max_mm": round(max(errs), 2),
        "p95_relative": round(pct(rel, 95), 4),
        "shape_class_correct": f"{len(kind_ok)}/{len(ok)}",
        "strategy_use": {
            s: sum(1 for r in ok if r["strategy"] == s) for s in ("lab_otsu", "adaptive", "edges")
        },
        "local_ms_median": round(statistics.median(r["ms"] for r in rows), 1),
        "by_tilt": by_tilt,
        "failure_cases": {
            name: f"{sum(1 for f in fail_cases if f['case'] == name and f['caught'])}/"
            f"{sum(1 for f in fail_cases if f['case'] == name)} asked for a retake"
            for name in ("no_marker", "cut_off", "two_objects")
        },
    }

    summary["agent_decisions"] = {
        "cases": len(decisions),
        "correct": sum(1 for x in decisions if x["outcome"] == "correct"),
        "asked_for_retake": sum(1 for x in decisions if x["outcome"] == "retake"),
        "wrong": sum(1 for x in decisions if x["outcome"] == "wrong"),
        "wrong_margins_mm": [x["margin_mm"] for x in decisions if x["outcome"] == "wrong"],
    }

    if lam:
        times = {"local_ms": [], "lambda_measure_ms": [], "lambda_round_trip_ms": []}
        agree = []
        for i in range(20):
            s = make_scene(np.random.default_rng(2000 + i), 120, 70)
            t0 = time.perf_counter()
            loc = measure(s.jpg, annotate=False)
            times["local_ms"].append((time.perf_counter() - t0) * 1e3)
            t0 = time.perf_counter()
            res = httpx.post(
                lam, json={"image_b64": base64.b64encode(s.jpg).decode()}, timeout=60
            ).json()
            times["lambda_round_trip_ms"].append((time.perf_counter() - t0) * 1e3)
            times["lambda_measure_ms"].append(res["ms"])
            if loc["object"] and res.get("object"):
                agree.append(abs(loc["object"]["width_mm"] - res["object"]["width_mm"]))
        summary["lambda"] = {
            "url": lam,
            "runs": 20,
            "first_call_round_trip_ms": round(times["lambda_round_trip_ms"][0], 1),
            **{f"{k}_median": round(statistics.median(v[1:]), 1) for k, v in times.items()},
            "max_width_disagreement_mm": round(max(agree), 3) if agree else None,
        }

    (out / "results.json").write_text(
        json.dumps(
            {
                "summary": summary,
                "scenes": rows,
                "failure_cases": fail_cases,
                "agent_decisions": decisions,
            },
            indent=1,
        )
    )
    print(json.dumps(summary, indent=1))  # noqa: T201


if __name__ == "__main__":
    main()
