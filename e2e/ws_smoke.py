"""Live WebSocket smoke test for the Bara server.

Run: uv run --with websockets --with jsonschema --with referencing python e2e/ws_smoke.py
Env: BARA_WS (default ws://127.0.0.1:8790/v1/ws), BARA_HTTP (default http://127.0.0.1:8790).
Start the server with BARA_SPEED high and BARA_EVENT_LOG_KEEP small (scripts/e2e.sh does both)
so the resume check reaches E_RESUME_GAP.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

import websockets
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

ROOT = Path(__file__).resolve().parents[1]
SPEC_DIR = ROOT / "spec"
WS_URL = os.environ.get("BARA_WS", "ws://127.0.0.1:8790/v1/ws")
HTTP_URL = os.environ.get("BARA_HTTP", "http://127.0.0.1:8790")
SPEC_VERSION = "1.1.0"
BUILD_TIMEOUT_S = float(os.environ.get("BARA_E2E_TIMEOUT", "90"))
IDLE_DRAIN_S = 0.7

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, bool(ok), detail))
    return bool(ok)


# ---------------------------------------------------------------- schemas


def load_registry() -> Registry:
    reg = Registry()
    for p in sorted((SPEC_DIR / "schemas").glob("*.json")):
        doc = json.loads(p.read_text())
        reg = reg.with_resource(doc["$id"], Resource.from_contents(doc, DRAFT202012))
    return reg


REGISTRY = load_registry()


def validator_for(schema_file: str) -> Draft202012Validator:
    doc = json.loads((SPEC_DIR / "schemas" / schema_file).read_text())
    return Draft202012Validator({"$ref": doc["$id"]}, registry=REGISTRY)


SERVER_V = validator_for("ws_server.schema.json")
CLIENT_V = validator_for("ws_client.schema.json")
REST_BUILD_V = Draft202012Validator(
    {"$ref": "https://app.invalid/spec/v1/rest.schema.json#/$defs/BuildResponse"},
    registry=REGISTRY,
)


def schema_errors(v: Draft202012Validator, msg: Any) -> list[str]:
    out = []
    for e in sorted(v.iter_errors(msg), key=lambda e: list(e.absolute_path))[:3]:
        out.append(
            f"{'/'.join(str(x) for x in e.absolute_path) or '<root>'}: {e.message[:140]}"
        )
    return out


# ---------------------------------------------------------------- fixtures


def load_streams() -> dict[str, dict]:
    out = {}
    for p in sorted((SPEC_DIR / "fixtures").glob("*.json")):
        d = json.loads(p.read_text())
        if d.get("kind") == "stream":
            out[d["fixture"]] = d
    return out


def client_steps(fx: dict) -> list[dict]:
    return [s["msg"] for s in fx["steps"] if s["dir"] == "client"]


def server_msgs(fx: dict) -> list[dict]:
    return [s["msg"] for s in fx["steps"] if s["dir"] == "server"]


# ---------------------------------------------------------------- reducer (SPEC section 9)


def _upsert(lst: list[dict], key: str, obj: dict) -> None:
    for i, o in enumerate(lst):
        if o.get(key) == obj.get(key):
            lst[i] = obj
            return
    lst.append(obj)


def new_build(build_id: str, prompt: str) -> dict:
    return {
        "build_id": build_id,
        "prompt": prompt,
        "status": "running",
        "revision": 0,
        "tier": "unknown",
        "spec": None,
        "design_id": None,
        "slots": [],
        "decisions": [],
        "parts": [],
        "connections": [],
        "layouts": [],
        "enclosures": [],
        "boards": [],
        "firmware": None,
        "checks": [],
        "warnings": [],
        "scene": None,
        "timings_ms": {},
        "error": None,
        "clarify": None,
        "clarifications": [],
        "last_seq": 0,
    }


def reduce_event(b: dict, env: dict) -> None:
    t, p = env["type"], env["payload"]
    if t == "build.snapshot":
        keep_created = b.get("created_at")
        b.clear()
        b.update(copy.deepcopy(p["build"]))
        if keep_created and "created_at" not in b:
            b["created_at"] = keep_created
    elif t == "spec.ready":
        b["spec"] = p["spec"]
    elif t == "reuse.decided":
        b["tier"], b["design_id"] = p["tier"], p["design_id"]
    elif t == "slots.ready":
        b["slots"] = p["slots"]
    elif t == "slot.updated":
        _upsert(b["slots"], "slot_id", p["slot"])
    elif t == "decision.made":
        _upsert(b["decisions"], "decision_id", p["decision"])
    elif t == "decision.reverted":
        b["decisions"] = [
            d for d in b["decisions"] if d["decision_id"] != p["decision_id"]
        ]
    elif t == "layout.added":
        _upsert(b["layouts"], "layout_id", p["layout"])
    elif t in ("part.added", "part.updated"):
        _upsert(b["parts"], "instance_id", p["part"])
    elif t == "part.removed":
        b["parts"] = [x for x in b["parts"] if x["instance_id"] != p["instance_id"]]
    elif t == "connection.added":
        _upsert(b["connections"], "connection_id", p["connection"])
    elif t == "connection.removed":
        b["connections"] = [
            c for c in b["connections"] if c["connection_id"] != p["connection_id"]
        ]
    elif t == "placement.updated":
        for e in p["placements"]:
            for part in b["parts"]:
                if part["instance_id"] == e["instance_id"]:
                    part["placement"] = e["placement"]
    elif t == "enclosure.updated":
        _upsert(b["enclosures"], "enclosure_id", p["enclosure"])
    elif t == "board.updated":
        _upsert(b["boards"], "board_id", p["board"])
    elif t == "firmware.ready":
        b["firmware"] = p["firmware"]
    elif t == "scene.ready":
        b["scene"] = p["scene"]
    elif t == "check.result":
        for r in p["results"]:
            _upsert(b["checks"], "check_key", r)
    elif t == "warning":
        _upsert(b["warnings"], "warning_id", p["warning"])
    elif t == "stage.completed":
        if p["stage"] != "edit":
            b["timings_ms"][p["stage"]] = p["duration_ms"]
    elif t == "clarify.request":
        b["clarify"], b["status"] = p, "awaiting_input"
    elif t == "clarify.resolved":
        b["clarifications"].append(p)
        b["clarify"], b["status"] = None, "running"
    elif t == "build.done":
        b["status"] = "done"
    elif t == "build.failed":
        b["status"] = "cancelled" if p["error"]["code"] == "E_CANCELLED" else "failed"
        b["error"], b["clarify"] = p["error"], None
    if env.get("build_id") is not None and t not in ("hello", "ack", "pong", "error"):
        if "revision" in env:
            b["revision"] = env["revision"]
        if t != "build.snapshot":
            b["last_seq"] = env["seq"]


def diff_builds(mine: dict, theirs: dict) -> list[str]:
    diffs = []
    for k in sorted(set(mine) | set(theirs)):
        if k == "created_at":
            continue
        if mine.get(k) != theirs.get(k):
            m, t = mine.get(k), theirs.get(k)
            if isinstance(m, list) and isinstance(t, list):
                key = next(
                    (
                        x
                        for x in (
                            "instance_id",
                            "connection_id",
                            "slot_id",
                            "check_key",
                            "warning_id",
                            "decision_id",
                            "layout_id",
                            "enclosure_id",
                            "board_id",
                        )
                        if m and x in m[0]
                    ),
                    None,
                )
                if key:
                    mi, ti = {x[key]: x for x in m}, {x[key]: x for x in t}
                    only_m, only_t = (
                        sorted(set(mi) - set(ti)),
                        sorted(set(ti) - set(mi)),
                    )
                    changed = sorted(i for i in set(mi) & set(ti) if mi[i] != ti[i])
                    diffs.append(
                        f"{k}: stream-only={only_m[:4]} rest-only={only_t[:4]} "
                        f"changed={changed[:4]}"
                    )
                    continue
            diffs.append(f"{k}: stream={json.dumps(m)[:80]} rest={json.dumps(t)[:80]}")
    return diffs


# ---------------------------------------------------------------- REST


def http_get(path: str) -> tuple[int, Any]:
    try:
        with urllib.request.urlopen(HTTP_URL + path, timeout=15) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:  # noqa: BLE001
            return e.code, None


# ---------------------------------------------------------------- client


class Session:
    def __init__(self) -> None:
        self.ws: Any = None
        self.msgs: list[dict] = []  # every server message, in arrival order
        self.bad_schema: list[str] = []
        self.hello: dict | None = None
        self.n = 0
        self.prefix = "m_e2e_" + uuid.uuid4().hex[:6]

    async def open(self) -> None:
        self.ws = await websockets.connect(WS_URL, max_size=32 * 1024 * 1024)
        env = await self.recv(10)
        check(
            "hello is first message",
            env is not None and env["type"] == "hello",
            env["type"] if env else "timeout",
        )
        self.hello = env

    async def close(self) -> None:
        if self.ws:
            await self.ws.close()

    def msg_id(self) -> str:
        self.n += 1
        return f"{self.prefix}_{self.n:04d}"

    async def recv(self, timeout: float) -> dict | None:
        try:
            raw = await asyncio.wait_for(self.ws.recv(), timeout)
        except TimeoutError:
            return None
        env = json.loads(raw)
        errs = schema_errors(SERVER_V, env)
        if errs:
            self.bad_schema.append(f"{env.get('type')} seq={env.get('seq')}: {errs[0]}")
        self.msgs.append(env)
        return env

    async def send(self, type_: str, payload: dict, msg_id: str | None = None) -> str:
        mid = msg_id or self.msg_id()
        env = {
            "spec_version": SPEC_VERSION,
            "type": type_,
            "msg_id": mid,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
            "payload": payload,
        }
        errs = schema_errors(CLIENT_V, env)
        if errs:
            check(f"client msg {type_} valid", False, errs[0])
        await self.ws.send(json.dumps(env))
        return mid

    async def wait_for(self, pred, timeout: float, on_msg=None) -> dict | None:
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                return None
            env = await self.recv(left)
            if env is None:
                return None
            if on_msg:
                await on_msg(env)
            if pred(env):
                return env

    async def drain(self, on_msg=None) -> None:
        while True:
            env = await self.recv(IDLE_DRAIN_S)
            if env is None:
                return
            if on_msg:
                await on_msg(env)


def fixture_answers(fx: dict) -> list[dict]:
    return [m["payload"] for m in client_steps(fx) if m["type"] == "clarify.answer"]


async def run_build(name: str, fx: dict, prompt: str) -> dict | None:
    """Run one build to its terminal event. Returns a dict with session, build_id, events."""
    s = Session()
    await s.open()
    answers = fixture_answers(fx)
    answered: list[str] = []

    async def on_msg(env: dict) -> None:
        if env["type"] != "clarify.request":
            return
        q = env["payload"]
        fa = answers[len(answered)] if len(answered) < len(answers) else {"skip": True}
        body: dict[str, Any] = {"build_id": build_id, "question_id": q["question_id"]}
        opt_ids = [o["option_id"] for o in q["options"]]
        if fa.get("option_id") in opt_ids:
            body["option_id"] = fa["option_id"]
        elif fa.get("skip") or not opt_ids:
            body["skip"] = True
        else:
            body["option_id"] = opt_ids[0]
        answered.append(q["question_id"])
        await s.send("clarify.answer", body)

    start_payload = {
        "prompt": prompt,
        "options": {"force_tier": None, "commercial_only": False, "seed": None},
    }
    mid = await s.send("build.start", start_payload)
    ack = await s.wait_for(
        lambda e: e["type"] == "ack" and e["payload"].get("msg_id") == mid, 15
    )
    if not check(
        f"{name}: build.start acked",
        bool(ack and ack["payload"]["accepted"]),
        json.dumps(ack["payload"])[:160] if ack else "no ack",
    ):
        await s.close()
        return None
    build_id = ack["payload"]["build_id"]
    check(f"{name}: ack carries build_id", bool(build_id), str(build_id))
    first_idx = len(s.msgs)
    term = await s.wait_for(
        lambda e: (
            e["type"] in ("build.done", "build.failed")
            and e.get("build_id") == build_id
        ),
        BUILD_TIMEOUT_S,
        on_msg,
    )
    if not check(f"{name}: reaches terminal event", term is not None, "timeout"):
        await s.close()
        return None
    await s.drain(on_msg)
    return {
        "session": s,
        "build_id": build_id,
        "prompt": prompt,
        "term": term,
        "start_idx": first_idx - 1,
        "answered": answered,
    }


def build_events(run: dict) -> list[dict]:
    return [
        e
        for e in run["session"].msgs
        if e.get("build_id") == run["build_id"]
        and e["type"] not in ("ack", "error", "pong")
    ]


def validate_stream(name: str, run: dict, fx: dict) -> None:
    s: Session = run["session"]
    evs = build_events(run)
    seqs = [e["seq"] for e in evs if e["type"] != "build.snapshot"]
    contiguous = seqs == list(range(seqs[0], seqs[0] + len(seqs))) if seqs else False
    check(
        f"{name}: seq contiguous from 1",
        contiguous and seqs[0] == 1,
        f"first={seqs[:1]} n={len(seqs)}",
    )
    ack_pos = next(
        i
        for i, m in enumerate(s.msgs)
        if m["type"] == "ack" and m["payload"].get("build_id") == run["build_id"]
    )
    first_ev = next(
        (
            i
            for i, m in enumerate(s.msgs)
            if m.get("build_id") == run["build_id"]
            and m["type"] not in ("ack", "error")
        ),
        10**9,
    )
    check(
        f"{name}: ack precedes build events",
        ack_pos < first_ev,
        f"{ack_pos} vs {first_ev}",
    )
    terms = [e for e in evs if e["type"] in ("build.done", "build.failed")]
    want = next(
        (
            m["type"]
            for m in reversed(server_msgs(fx))
            if m["type"] in ("build.done", "build.failed")
        ),
        None,
    )
    check(
        f"{name}: exactly one terminal, type {want}",
        len(terms) == 1 and terms[0]["type"] == want,
        f"got {[t['type'] for t in terms]}",
    )
    # at most one open stage
    open_stage, ok_stage = None, True
    for e in evs:
        if e["type"] == "stage.started":
            ok_stage &= open_stage is None
            open_stage = e["payload"]["stage"]
        elif e["type"] == "stage.completed":
            if open_stage == e["payload"]["stage"]:
                open_stage = None
    check(
        f"{name}: stage open/close well formed",
        ok_stage and open_stage is None,
        f"open={open_stage}",
    )
    want_tier = next(
        (m["payload"]["tier"] for m in server_msgs(fx) if m["type"] == "reuse.decided"),
        None,
    )
    got_tier = next(
        (e["payload"]["tier"] for e in evs if e["type"] == "reuse.decided"), None
    )
    if want_tier is not None:
        check(
            f"{name}: tier matches fixture ({want_tier})",
            got_tier == want_tier,
            str(got_tier),
        )
    n_clar = len(fixture_answers(fx))
    check(
        f"{name}: clarify rounds answered ({n_clar})",
        len(run["answered"]) == n_clar,
        f"answered {len(run['answered'])}",
    )
    check(
        f"{name}: all server messages match schema",
        not s.bad_schema,
        "; ".join(s.bad_schema[:2])
        + (f" (+{len(s.bad_schema) - 2})" if len(s.bad_schema) > 2 else ""),
    )


def reduce_and_compare(
    name: str, run: dict, seed_build: dict | None = None, after_edit: bool = False
) -> dict | None:
    evs = build_events(run)
    b = seed_build or new_build(run["build_id"], run["prompt"])
    for e in evs:
        reduce_event(b, e)
    status, body = http_get(f"/v1/builds/{run['build_id']}")
    if not check(f"{name}: GET /v1/builds/id 200", status == 200, f"status {status}"):
        return None
    errs = schema_errors(REST_BUILD_V, body)
    check(f"{name}: REST BuildResponse matches schema", not errs, "; ".join(errs[:2]))
    theirs = body["build"]
    diffs = diff_builds(b, theirs)
    check(f"{name}: reduced stream == GET build", not diffs, " | ".join(diffs[:3]))
    # an edit replays the base build's build.done, so its summary predates the edit
    if run["term"]["type"] == "build.done" and not after_edit:
        summ = run["term"]["payload"]["summary"]
        check(
            f"{name}: summary counts match store",
            summ["instance_count"] == len(b["parts"])
            and summ["connection_count"] == len(b["connections"]),
            f"summary inst={summ['instance_count']} conn={summ['connection_count']} "
            f"store inst={len(b['parts'])} conn={len(b['connections'])}",
        )
    return theirs


# ---------------------------------------------------------------- flows


async def flow_streams(streams: dict[str, dict]) -> dict | None:
    exact_run = None
    for name, fx in streams.items():
        prompts = fx.get("match_prompts") or []
        if not prompts:
            continue
        run = await run_build(name, fx, prompts[0])
        if run is None:
            continue
        validate_stream(name, run, fx)
        reduce_and_compare(name, run)
        if name == "exact_keyboard":
            exact_run = run
        else:
            await run["session"].close()
    return exact_run


async def flow_edit(fixture_name: str, fx: dict, base_fx: dict) -> None:
    name = f"edit:{fixture_name}"
    run = await run_build(name + " (base build)", base_fx, base_fx["match_prompts"][0])
    if run is None or run["term"]["type"] != "build.done":
        check(name + ": base build done", False, "base build did not finish")
        return
    s: Session = run["session"]
    base_events = build_events(run)
    rev = max((e.get("revision", 0) for e in base_events), default=0)
    edit = next(m for m in client_steps(fx) if m["type"] == "edit.apply")
    payload = copy.deepcopy(edit["payload"])
    payload["build_id"] = run["build_id"]
    payload["base_revision"] = rev
    mark = len(s.msgs)
    mid = await s.send("edit.apply", payload)
    ack = await s.wait_for(
        lambda e: e["type"] == "ack" and e["payload"].get("msg_id") == mid, 10
    )
    check(
        f"{name}: edit acked accepted",
        bool(ack and ack["payload"]["accepted"]),
        json.dumps(ack["payload"])[:160] if ack else "no ack",
    )
    want = next(
        m["type"]
        for m in server_msgs(fx)
        if m["type"] in ("edit.applied", "edit.rejected")
    )
    res = await s.wait_for(lambda e: e["type"] in ("edit.applied", "edit.rejected"), 20)
    check(
        f"{name}: result is {want}",
        bool(res and res["type"] == want),
        res["type"] if res else "timeout",
    )
    await s.drain()
    new_msgs = s.msgs[mark:]
    check(
        f"{name}: edit ack before edit events",
        bool(new_msgs) and new_msgs[0]["type"] == "ack",
        new_msgs[0]["type"] if new_msgs else "",
    )
    check(
        f"{name}: all server messages match schema",
        not s.bad_schema,
        "; ".join(s.bad_schema[:2]),
    )
    if res and want == "edit.applied":
        fix_rev = next(
            m["revision"] for m in server_msgs(fx) if m["type"] == "edit.applied"
        )
        check(
            f"{name}: revision {fix_rev}",
            res["payload"]["revision"] == fix_rev,
            str(res["payload"]["revision"]),
        )
        model_ev = [
            e
            for e in new_msgs
            if e["type"]
            in (
                "part.updated",
                "part.added",
                "part.removed",
                "connection.removed",
                "connection.added",
            )
        ]
        check(
            f"{name}: model events carry cause.edit_id",
            all(e.get("cause", {}).get("edit_id") for e in model_ev),
            f"{len(model_ev)} events",
        )
    if res and want == "edit.rejected":
        want_code = next(
            m["payload"]["error"]["code"]
            for m in server_msgs(fx)
            if m["type"] == "edit.rejected"
        )
        check(
            f"{name}: reject code {want_code}",
            res["payload"]["error"]["code"] == want_code,
            res["payload"]["error"]["code"],
        )
        check(
            f"{name}: no model change after reject",
            not any(
                e["type"] in ("part.updated", "part.removed", "check.result")
                for e in new_msgs
            ),
            "model events leaked",
        )
    reduce_and_compare(name, run, after_edit=True)
    await s.close()


async def flow_resume(run: dict) -> None:
    name = "resume"
    status, body = http_get(f"/v1/builds/{run['build_id']}")
    if status != 200:
        check(f"{name}: build available", False, f"status {status}")
        return
    last_seq = body["build"]["last_seq"]
    s = Session()
    await s.open()
    mid = await s.send("ping", {})
    pong = await s.wait_for(lambda e: e["type"] == "pong", 5)
    check(
        f"{name}: ping answered with same msg_id",
        bool(pong and pong["payload"]["msg_id"] == mid),
        "no pong",
    )
    # Old cursor: expect E_RESUME_GAP then snapshot.
    rid = await s.send("build.resume", {"build_id": run["build_id"], "last_seq": 0})
    ack = await s.wait_for(
        lambda e: e["type"] == "ack" and e["payload"].get("msg_id") == rid, 10
    )
    check(
        f"{name}: resume acked",
        bool(ack and ack["payload"]["accepted"]),
        json.dumps(ack["payload"])[:160] if ack else "no ack",
    )
    err = await s.wait_for(lambda e: e["type"] == "error", 5)
    check(
        f"{name}: E_RESUME_GAP error",
        bool(err and err["payload"]["error"]["code"] == "E_RESUME_GAP"),
        json.dumps(err["payload"])[:160]
        if err
        else "no error event (is BARA_EVENT_LOG_KEEP small?)",
    )
    snap = await s.wait_for(lambda e: e["type"] == "build.snapshot", 5) if err else None
    check(
        f"{name}: build.snapshot follows gap",
        bool(snap and snap["payload"]["reason"] == "resume_gap"),
        "no snapshot",
    )
    if snap:
        check(
            f"{name}: snapshot seq == build.last_seq",
            snap["seq"] == snap["payload"]["build"]["last_seq"],
            f"seq {snap['seq']} vs {snap['payload']['build']['last_seq']}",
        )
        diffs = diff_builds(
            snap["payload"]["build"],
            http_get(f"/v1/builds/{run['build_id']}")[1]["build"],
        )
        check(f"{name}: snapshot == GET build", not diffs, " | ".join(diffs[:2]))
    # Duplicate msg_id.
    await s.send(
        "build.resume", {"build_id": run["build_id"], "last_seq": 0}, msg_id=rid
    )
    dup = await s.wait_for(
        lambda e: e["type"] == "ack" and e["payload"].get("msg_id") == rid, 10
    )
    check(
        f"{name}: resent msg_id acked duplicate",
        bool(dup and dup["payload"]["duplicate"]),
        json.dumps(dup["payload"])[:160] if dup else "no ack",
    )
    await s.drain()
    # Near cursor: replay.
    s.msgs.clear()
    near = max(0, last_seq - 2)
    rid2 = await s.send("build.resume", {"build_id": run["build_id"], "last_seq": near})
    await s.wait_for(
        lambda e: e["type"] == "ack" and e["payload"].get("msg_id") == rid2, 10
    )
    await s.drain()
    replay = [
        e["seq"]
        for e in s.msgs
        if e.get("build_id") == run["build_id"]
        and e["type"] not in ("ack", "error", "build.snapshot")
    ]
    check(
        f"{name}: near cursor replays seq {near + 1}..{last_seq}",
        replay == list(range(near + 1, last_seq + 1)),
        f"got {replay[:6]}",
    )
    # Unknown build.
    rid3 = await s.send("build.resume", {"build_id": "b_doesnotexist", "last_seq": 0})
    bad = await s.wait_for(
        lambda e: e["type"] == "ack" and e["payload"].get("msg_id") == rid3, 10
    )
    check(
        f"{name}: unknown build refused with E_UNKNOWN_BUILD",
        bool(
            bad
            and not bad["payload"]["accepted"]
            and (bad["payload"].get("error") or {}).get("code") == "E_UNKNOWN_BUILD"
        ),
        json.dumps(bad["payload"])[:160] if bad else "no ack",
    )
    check(
        f"{name}: all server messages match schema",
        not s.bad_schema,
        "; ".join(s.bad_schema[:2]),
    )
    await s.close()


async def main() -> int:
    streams = load_streams()
    status, health = http_get("/v1/health")
    if not check("GET /v1/health", status == 200, f"status {status}"):
        return report()
    print(f"server: {json.dumps(health)[:200]}")
    exact_run = await flow_streams(streams)
    base = streams["exact_keyboard"]
    for name in ("edit_swap_switches", "edit_rejected_choc", "edit_remove_part"):
        if name in streams:
            await flow_edit(name, streams[name], base)
    if exact_run is not None:
        await flow_resume(exact_run)
        await exact_run["session"].close()
    else:
        check("resume: needs exact_keyboard build", False, "exact build failed")
    return report()


def report() -> int:
    w = max(len(n) for n, _, _ in RESULTS)
    print()
    for n, ok, d in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {n.ljust(w)}  {'' if ok else d}")
    fails = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(fails)}/{len(RESULTS)} passed")
    return 1 if fails else 0


if __name__ == "__main__":
    try:
        code = asyncio.run(main())
    except (OSError, websockets.exceptions.WebSocketException) as exc:
        check("connect to server", False, f"{type(exc).__name__}: {exc}")
        code = report()
    sys.exit(code)
