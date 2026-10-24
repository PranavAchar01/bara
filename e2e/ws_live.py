# ruff: noqa: T201  (CLI report script)
"""Live-mode (BARA_MOCK=0) WebSocket run against a real server: every prompt end to end.

Run: uv run --with websockets --with jsonschema --with referencing python e2e/ws_live.py
Start the server with BARA_MOCK=0 (and optionally CEREBRAS_API_KEY / ANTHROPIC_API_KEY).
Env: BARA_WS, BARA_HTTP (as ws_smoke.py), BARA_E2E_TIMEOUT (per build, default 900 s since a
KiCad board with Freerouting takes minutes), BARA_LIVE_PROMPTS (indexes, e.g. "1,3").
Prints per-stage timings, check counts and the DRC chip text per build.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ws_smoke as W

ORDER = [
    "classify",
    "reuse",
    "compose",
    "place",
    "enclose",
    "board",
    "firmware",
    "render",
]
TERMINAL = {"build.done", "build.failed", "build.cancelled"}
TIMEOUT_S = float(os.environ.get("BARA_E2E_TIMEOUT", "900"))
PROMPTS = [
    "a keyboard",
    (
        "wireless split keyboard, 38 keys, sage and cream, red trackball on the right thumb, "
        "knob top left, tented"
    ),
    "34-key split, no trackball, two knobs, black and orange",
    "small 5x4 macropad with a knob and a screen, white",
    "a handheld weather station with an e-ink screen",
    "a desk clock",
    "make me a cool gadget",
    "a plant monitor",
    "a rover",
]


async def run_prompt(prompt: str) -> dict[str, Any]:
    s = W.Session()
    await s.open()
    try:
        await s.send("build.start", {"prompt": prompt})
        ack = await s.wait_for(lambda m: m["type"] == "ack", 15)
        if not W.check(f"ack {prompt[:30]}", bool(ack and ack["payload"].get("accepted"))):
            return {}
        build_id = ack["payload"]["build_id"]

        async def on_msg(env: dict[str, Any]) -> None:
            if env["type"] == "clarify.request":
                q = env["payload"]
                await s.send(
                    "clarify.answer",
                    {
                        "build_id": build_id,
                        "question_id": q["question_id"],
                        "option_id": q.get("default_option_id") or q["options"][0]["option_id"],
                    },
                )
            elif env["type"] == "stage.completed":
                p = env["payload"]
                print(f"    {p['stage']:<9} {p['status']:<10} {p['duration_ms']:>7} ms")

        end = await s.wait_for(lambda m: m["type"] in TERMINAL, TIMEOUT_S, on_msg)
    finally:
        await s.close()
    events = [m for m in s.msgs if m.get("build_id") == build_id]
    W.check(f"schema {prompt[:30]}", not s.bad_schema, "; ".join(s.bad_schema[:2]))
    if end is None:
        W.check(f"terminal {prompt[:30]}", False, "timeout")
        return {}
    return {"end": end, "events": events}


def summarize(prompt: str, out: dict[str, Any]) -> None:
    end, events = out["end"], out["events"]
    if end["type"] == "build.failed":
        code = end["payload"]["error"]["code"]
        W.check(f"done {prompt[:30]}", code == "E_OUT_OF_SCOPE", code)
        return
    W.check(f"done {prompt[:30]}", end["type"] == "build.done", end["type"])
    started = []
    for m in events:
        if m["type"] == "stage.started" and m["payload"]["stage"] not in started:
            started.append(m["payload"]["stage"])
    W.check(f"stage order {prompt[:30]}", started == ORDER, ",".join(started))
    p = end["payload"]
    print(f"    total {p['total_ms']} ms, checks {p['summary']['checks']}")
    for m in events:
        if m["type"] == "check.result":
            for r in m["payload"]["results"]:
                if r["rule_id"] == "board.drc":
                    print(f"    {r['message']}")


async def main() -> int:
    picks = os.environ.get("BARA_LIVE_PROMPTS")
    chosen = [PROMPTS[int(i)] for i in picks.split(",")] if picks else PROMPTS
    for prompt in chosen:
        print(f"== {prompt}")
        out = await run_prompt(prompt)
        if out:
            summarize(prompt, out)
    return W.report()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
