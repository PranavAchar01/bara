"""Build registry, fixture replay engine, clarify, cancel and live edits.

Every build-scoped event goes through BuildRun.emit, which is synchronous: it assigns the
next seq, applies the event to the reduced state, appends it to the kept event log and
puts it on every subscriber queue. Because emit never awaits, a group of events emitted
without an await in between reaches every socket in order with nothing interleaved.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import re
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from bara.catalog import Catalog
from bara.config import Settings
from bara.edits import EditEngine
from bara.library import Library
from bara.reducer import apply_event, new_build
from bara.router import Route, Router, normalize
from bara.util import envelope, error_obj, new_build_id, now_ts

log = logging.getLogger(__name__)

CONNECTION_TYPES = {"hello", "ack", "pong", "error"}
TERMINAL = {"build.done", "build.failed"}

Subscriber = Callable[[dict[str, Any]], None]


@dataclass
class ClarifyWait:
    question: dict[str, Any]
    future: asyncio.Future
    answer_msg_id: str | None = None


@dataclass
class BuildRun:
    build_id: str
    prompt: str
    options: dict[str, Any]
    keep: int
    state: dict[str, Any]
    log: list[dict[str, Any]] = field(default_factory=list)
    seq: int = 0
    subscribers: dict[int, Subscriber] = field(default_factory=dict)
    task: asyncio.Task | None = None
    open_stage: str | None = None
    open_stage_started: float = 0.0
    terminal: str | None = None
    replay_finished: bool = False
    clarify: ClarifyWait | None = None
    edit_counter: int = 0
    assumption_warnings_sent: bool = False
    started_at: float = field(default_factory=time.monotonic)
    # Library hook: set for live builds so every emitted event is kept on disk.
    recorder: Any = None
    device: str = ""

    @property
    def oldest_seq(self) -> int:
        return self.log[0]["seq"] if self.log else self.seq + 1

    def emit(
        self,
        msg_type: str,
        payload: dict[str, Any],
        *,
        stage: str | None = None,
        revision: int | None = None,
        cause: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.seq += 1
        msg = envelope(
            msg_type,
            payload,
            seq=self.seq,
            build_id=self.build_id,
            stage=stage,
            revision=revision,
            cause=cause,
        )
        apply_event(self.state, msg)
        if msg_type == "stage.started":
            self.open_stage = payload["stage"]
            self.open_stage_started = time.monotonic()
        elif msg_type == "stage.completed" and payload.get("stage") == self.open_stage:
            self.open_stage = None
        elif msg_type in TERMINAL:
            self.terminal = msg_type
        self.log.append(msg)
        if self.recorder is not None:
            try:
                self.recorder.record(self, msg)
            except OSError:
                log.exception("library write failed for %s", self.build_id)
        if len(self.log) > self.keep:
            del self.log[: len(self.log) - self.keep]
        for send in list(self.subscribers.values()):
            send(msg)
        return msg

    def snapshot(self, reason: str) -> dict[str, Any]:
        return envelope(
            "build.snapshot",
            {"build": copy.deepcopy(self.state), "reason": reason},
            seq=self.state["last_seq"],
            build_id=self.build_id,
            revision=self.state["revision"],
        )

    @property
    def stream_complete(self) -> bool:
        return self.terminal is not None and self.replay_finished


def _server_steps(fx: dict[str, Any]) -> list[dict[str, Any]]:
    return fx.get("steps", [])


def _assumption_id(facet: str, used: set[str]) -> str:
    base = "as_" + re.sub(r"[^a-z0-9_]", "_", facet.lower())[:28]
    out, n = base, 2
    while out in used:
        out, n = f"{base}_{n}", n + 1
    used.add(out)
    return out


class Engine:
    def __init__(self, catalog: Catalog, settings: Settings, router: Router, edits: EditEngine):
        self.catalog = catalog
        self.settings = settings
        self.router = router
        self.edits = edits
        self.builds: dict[str, BuildRun] = {}
        self.library = Library(settings.data_dir / "library", settings.assets_dir)
        # Live 8-stage runner for BARA_MOCK=0 (bara.live.runner.LiveRunner), set by services.
        self.live: Any = None
        kw = router.keywords
        self.skip_words: list[str] = [normalize(w) for w in kw.get("skip_answers", [])]

    # ---- registry ----------------------------------------------------------
    def get(self, build_id: str) -> BuildRun | None:
        return self.builds.get(build_id)

    def start(self, prompt: str, options: dict[str, Any] | None) -> BuildRun:
        build_id = new_build_id()
        while build_id in self.builds:
            build_id = new_build_id()
        run = BuildRun(
            build_id=build_id,
            prompt=prompt,
            options=dict(options or {}),
            keep=self.settings.event_log_keep,
            state=new_build(build_id, prompt, now_ts()),
        )
        self.builds[build_id] = run
        return run

    def launch(self, run: BuildRun) -> None:
        """Start the replay task. Call after the build.start ack has been queued."""
        run.task = asyncio.get_running_loop().create_task(self._run(run))

    async def shutdown(self) -> None:
        tasks = [r.task for r in self.builds.values() if r.task and not r.task.done()]
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):  # shutting down; nothing to report
                pass

    # ---- replay ------------------------------------------------------------
    async def _sleep(self, delay_ms: float) -> None:
        # BARA_SPEED is a playback rate: 2 plays twice as fast, 0 means no delays at all.
        speed = self.settings.speed
        await asyncio.sleep(max(0.0, delay_ms) / speed / 1000.0 if speed > 0 else 0)

    async def _run(self, run: BuildRun) -> None:
        try:
            if (
                self.live is not None
                and not self.settings.mock
                and not run.options.get("mock_fixture")
            ):
                run.recorder = self.library
                await self.live.run(run)
            else:
                await self._replay(run)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # a bug in replay must still end the build cleanly
            log.exception("build %s failed in replay", run.build_id)
            if run.terminal is None:
                tb = traceback.extract_tb(exc.__traceback__)
                where = (
                    f"{tb[-1].name} at {tb[-1].filename.rsplit('/', 1)[-1]}:{tb[-1].lineno}"
                    if tb
                    else "unknown"
                )
                self._fail(
                    run,
                    error_obj(
                        "E_INTERNAL",
                        f"Internal error in stage {run.open_stage or 'unknown'}: "
                        f"{type(exc).__name__}: {exc} ({where}).",
                        stage=run.open_stage,
                    ),
                )
        finally:
            run.replay_finished = True

    def _fail(self, run: BuildRun, error: dict[str, Any], cause: dict[str, Any] | None = None):
        if run.open_stage:
            stage = run.open_stage
            run.emit(
                "stage.completed",
                {
                    "stage": stage,
                    "status": "failed",
                    "duration_ms": int((time.monotonic() - run.open_stage_started) * 1000),
                    "message": error["message"][:200],
                },
                stage=stage,
                cause=cause,
            )
        run.emit("build.failed", {"error": error}, cause=cause)

    async def _replay(self, run: BuildRun) -> None:
        classify_label = "Understanding the request"
        run.emit(
            "stage.started",
            {
                "stage": "classify",
                "label": classify_label,
                "budget_ms": self.catalog.stage_budget("classify"),
            },
            stage="classify",
        )
        route = await self.router.route(run.prompt, run.options)
        log.info("build %s routed %s via %s", run.build_id, route.route, route.reason)
        for warning in route.warnings:
            run.emit("warning", {"warning": copy.deepcopy(warning)}, stage="classify")
        if route.fixture is None:
            self._reject_stream(run, route)
            return
        await self._replay_fixture(run, route, self.catalog.fixtures[route.fixture])

    def _reject_stream(self, run: BuildRun, route: Route) -> None:
        run.emit("spec.ready", {"spec": copy.deepcopy(route.spec)}, stage="classify")
        run.emit(
            "stage.completed",
            {
                "stage": "classify",
                "status": "ok",
                "duration_ms": int((time.monotonic() - run.started_at) * 1000),
            },
            stage="classify",
        )
        reason = (route.spec or {}).get("scope_reason") or "This request is out of scope."
        run.emit(
            "build.failed",
            {"error": error_obj("E_OUT_OF_SCOPE", reason, stage="classify")},
        )

    async def _replay_fixture(self, run: BuildRun, route: Route, fx: dict[str, Any]) -> None:
        skipped_first_classify = False
        msg_map: dict[str, str | None] = {}
        pending_resolution: dict[str, Any] | None = None
        resolutions: list[dict[str, Any]] = []
        last_answer_mid: str | None = None
        for step in _server_steps(fx):
            msg = step["msg"]
            if step.get("dir") == "client":
                if msg["type"] == "clarify.answer":
                    msg_map[msg["msg_id"]] = last_answer_mid
                continue
            kind = msg["type"]
            if kind in CONNECTION_TYPES:
                continue
            if (
                not skipped_first_classify
                and kind == "stage.started"
                and msg["payload"].get("stage") == "classify"
            ):
                skipped_first_classify = True
                continue
            if run.terminal == "build.failed":
                return
            await self._sleep(step.get("delay_ms", 0))
            payload = copy.deepcopy(msg["payload"])
            cause = None
            if msg.get("cause", {}).get("msg_id"):
                real = msg_map.get(msg["cause"]["msg_id"])
                cause = {"msg_id": real} if real else None
            stage = msg.get("stage")
            revision = msg.get("revision")

            if kind == "clarify.request":
                run.emit(kind, payload, cause=cause)
                pending_resolution = await self._wait_clarify(run, payload)
                last_answer_mid = pending_resolution.pop("_msg_id", None)
                resolutions.append({"question": payload, "resolution": pending_resolution})
                continue
            if kind == "clarify.resolved":
                if pending_resolution is not None:
                    real_cause = {"msg_id": last_answer_mid} if last_answer_mid else None
                    run.emit(kind, pending_resolution, cause=real_cause)
                    pending_resolution = None
                continue
            if kind == "spec.ready":
                payload["spec"] = self._patch_spec(run, route, payload["spec"], resolutions)
            if kind == "warning" and payload["warning"].get("code") == "assumption_made":
                if resolutions:
                    self._emit_assumption_warnings(run, resolutions, stage, cause)
                    continue
            if kind == "build.done":
                payload = self._done_payload(run, payload)
            if run.terminal == "build.done" and revision is not None:
                revision = run.state["revision"]
            run.emit(kind, payload, stage=stage, revision=revision, cause=cause)

    def _done_payload(self, run: BuildRun, payload: dict[str, Any]) -> dict[str, Any]:
        state = run.state
        counts = {"pass": 0, "fail": 0, "unknown": 0}
        for check in state["checks"]:
            status = check.get("status")
            counts[status if status in counts else "unknown"] += 1
        payload["summary"] = {
            "part_count": sum(int(p.get("quantity", 1) or 1) for p in state["parts"]),
            "instance_count": len(state["parts"]),
            "connection_count": len(state["connections"]),
            "warning_count": len(state["warnings"]),
            "checks": counts,
        }
        payload["timings_ms"] = dict(state["timings_ms"]) or payload.get("timings_ms", {})
        payload["total_ms"] = int((time.monotonic() - run.started_at) * 1000)
        return payload

    def _patch_spec(
        self,
        run: BuildRun,
        route: Route,
        spec: dict[str, Any],
        resolutions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        spec = copy.deepcopy(spec)
        if route.patch_prompt and spec.get("prompt") != run.prompt:
            spec["prompt"] = run.prompt
            spec["normalized_prompt"] = normalize(run.prompt) or run.prompt
            for req in spec.get("hard_requirements", []) + spec.get("soft_requirements", []):
                req["text_span"] = None
            spec["leftover_text"] = None
        if route.classifier is not None:
            spec["classifier"] = copy.deepcopy(route.classifier)
        if resolutions:
            reqs: list[dict[str, Any]] = []
            assumptions: list[dict[str, Any]] = []
            for entry in resolutions:
                question, res = entry["question"], entry["resolution"]
                option = self._option(question, res.get("option_id"))
                assumed = res["resolution"] in ("skipped", "timeout")
                for req in (option or {}).get("implies", []):
                    req = copy.deepcopy(req)
                    req["source"] = "assumed" if assumed else "clarified"
                    reqs.append(req)
                assumptions.extend(copy.deepcopy(res.get("assumptions", [])))
            # Requirements not tied to a clarify answer stay as the fixture had them.
            clarify_facets = {r["facet"] for r in reqs}
            implied_facets = {
                req["facet"]
                for entry in resolutions
                for option in entry["question"].get("options", [])
                for req in option.get("implies", [])
            }
            kept = [
                r
                for r in spec.get("hard_requirements", [])
                if r.get("source") not in ("clarified", "assumed")
                and r["facet"] not in clarify_facets
                and r["facet"] not in implied_facets
            ]
            merged = kept + reqs
            for i, req in enumerate(merged, start=1):
                req["req_id"] = f"r{i}"
            spec["hard_requirements"] = merged
            spec["assumptions"] = assumptions
        return spec

    def _emit_assumption_warnings(
        self,
        run: BuildRun,
        resolutions: list[dict[str, Any]],
        stage: str | None,
        cause: dict[str, Any] | None,
    ) -> None:
        if run.assumption_warnings_sent:
            return
        run.assumption_warnings_sent = True
        used = {w["warning_id"] for w in run.state["warnings"]}
        n = 0
        for entry in resolutions:
            for assumption in entry["resolution"].get("assumptions", []):
                n += 1
                warning_id = f"w_assume_{n}"
                while warning_id in used:
                    n += 1
                    warning_id = f"w_assume_{n}"
                used.add(warning_id)
                run.emit(
                    "warning",
                    {
                        "warning": {
                            "warning_id": warning_id,
                            "code": "assumption_made",
                            "severity": "info",
                            "message": (
                                f"Assumed {assumption['label']}. Change it with an edit or a "
                                "new prompt."
                            )[:300],
                            "subjects": [],
                            "stage": stage or "classify",
                        }
                    },
                    stage=stage,
                    cause=cause,
                )

    # ---- clarify -----------------------------------------------------------
    @staticmethod
    def _option(question: dict[str, Any], option_id: str | None) -> dict[str, Any] | None:
        return next((o for o in question.get("options", []) if o["option_id"] == option_id), None)

    async def _wait_clarify(self, run: BuildRun, question: dict[str, Any]) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        wait = ClarifyWait(question=question, future=loop.create_future())
        run.clarify = wait
        timeout_ms = self.settings.clarify_timeout_ms
        if timeout_ms is None:
            timeout_ms = int(question.get("timeout_ms", 60000))
        try:
            answer = await asyncio.wait_for(asyncio.shield(wait.future), timeout_ms / 1000.0)
        except TimeoutError:
            answer = None
        finally:
            run.clarify = None
        if answer is None:
            return self._resolution(question, "timeout", None, None, None)
        return answer

    def _resolution(
        self,
        question: dict[str, Any],
        resolution: str,
        option_id: str | None,
        free_text: str | None,
        msg_id: str | None,
    ) -> dict[str, Any]:
        assumptions: list[dict[str, Any]] = []
        if resolution in ("skipped", "timeout"):
            option_id = question.get("default_option_id") or question["options"][0]["option_id"]
            option = self._option(question, option_id) or question["options"][0]
            used: set[str] = set()
            why = "Skipped" if resolution == "skipped" else "No answer in time"
            for req in option.get("implies", []):
                assumptions.append(
                    {
                        "assumption_id": _assumption_id(req["facet"], used),
                        "facet": req["facet"],
                        "value": req["value"],
                        "label": (req.get("label") or option["label"])[:80],
                        "reason": f"{why}; used the most likely option, {option['label']}."[:200],
                    }
                )
            if not assumptions:
                facet = (question.get("missing_facets") or ["function"])[0]
                assumptions.append(
                    {
                        "assumption_id": _assumption_id(facet, used),
                        "facet": re.sub(r"[^a-z0-9_]", "_", facet.lower()),
                        "value": option["option_id"],
                        "label": option["label"][:80],
                        "reason": f"{why}; used the most likely option."[:200],
                    }
                )
        out = {
            "question_id": question["question_id"],
            "resolution": resolution,
            "option_id": option_id,
            "free_text": free_text,
            "assumptions": assumptions,
        }
        if msg_id:
            out["_msg_id"] = msg_id
        return out

    def _match_free_text(self, question: dict[str, Any], text: str) -> str | None:
        words = set(normalize(text).split())
        best, best_score = None, 0
        for option in question.get("options", []):
            option_words = set(
                normalize(option.get("label", "") + " " + (option.get("description") or "")).split()
            )
            option_words = {w for w in option_words if len(w) > 2}
            score = len(words & option_words)
            if score > best_score:
                best, best_score = option["option_id"], score
        return best

    def answer_clarify(self, run: BuildRun, msg_id: str, payload: dict[str, Any]) -> dict | None:
        """Validate an answer. Returns an error object, or None and resolves the wait."""
        wait = run.clarify
        if wait is None or wait.future.done():
            return error_obj("E_CLARIFY_NOT_PENDING", "No question is open for this build.")
        question = wait.question
        if payload["question_id"] != question["question_id"]:
            return error_obj(
                "E_CLARIFY_NOT_PENDING",
                f"Question {payload['question_id']} is not the open question.",
            )
        given = [
            k for k in ("option_id", "free_text", "skip") if payload.get(k) not in (None, False)
        ]
        if len(given) != 1:
            return error_obj(
                "E_INVALID_ANSWER", "Send exactly one of option_id, free_text or skip."
            )
        if payload.get("skip"):
            if question.get("allow_skip") is False:
                return error_obj("E_INVALID_ANSWER", "This question cannot be skipped.")
            result = self._resolution(question, "skipped", None, None, msg_id)
        elif payload.get("option_id") is not None:
            if self._option(question, payload["option_id"]) is None:
                return error_obj(
                    "E_INVALID_ANSWER",
                    f"Option {payload['option_id']} is not one of the offered options.",
                )
            result = self._resolution(
                question, "answered_option", payload["option_id"], None, msg_id
            )
        else:
            text = str(payload["free_text"]).strip()
            norm = normalize(text)
            if norm in self.skip_words or any(
                norm == w or norm.startswith(w + " ") for w in self.skip_words
            ):
                result = self._resolution(question, "skipped", None, text[:300], msg_id)
            elif not question.get("allow_free_text"):
                return error_obj("E_INVALID_ANSWER", "This question takes an option, not text.")
            else:
                option_id = self._match_free_text(question, text)
                result = self._resolution(question, "answered_text", option_id, text[:300], msg_id)
        wait.answer_msg_id = msg_id
        wait.future.set_result(result)
        return None

    # ---- cancel ------------------------------------------------------------
    def cancel(self, run: BuildRun, msg_id: str) -> None:
        if run.terminal is not None:
            return
        if run.task and not run.task.done():
            run.task.cancel()
        if run.clarify and not run.clarify.future.done():
            run.clarify.future.cancel()
        run.clarify = None
        self._fail(
            run,
            error_obj("E_CANCELLED", "Build cancelled.", stage=run.open_stage),
            cause={"msg_id": msg_id},
        )
        run.replay_finished = True

    # ---- edits -------------------------------------------------------------
    def edit_not_ready(self, run: BuildRun) -> dict[str, Any] | None:
        if run.terminal != "build.done":
            return error_obj(
                "E_BUILD_NOT_READY", "Edits open once the build is done.", stage="edit"
            )
        return None

    def next_edit_id(self, run: BuildRun) -> str:
        run.edit_counter += 1
        return f"ed_{run.edit_counter}"

    def apply_edit(self, run: BuildRun, msg_id: str, edit_id: str, payload: dict[str, Any]) -> None:
        started = time.monotonic()
        ops = payload["ops"]
        cause = {"msg_id": msg_id, "edit_id": edit_id}
        plan = self.edits.plan(run.state, ops, payload.get("base_revision"))
        run.emit(
            "stage.started",
            {"stage": "edit", "label": plan.label, "budget_ms": self.catalog.stage_budget("edit")},
            stage="edit",
            cause=cause,
        )

        def elapsed() -> int:
            return int((time.monotonic() - started) * 1000)

        if plan.rejection is not None:
            rej = plan.rejection
            run.emit(
                "stage.completed",
                {
                    "stage": "edit",
                    "status": "failed",
                    "duration_ms": elapsed(),
                    "message": rej.stage_message[:200],
                },
                stage="edit",
                cause=cause,
            )
            run.emit(
                "edit.rejected",
                {
                    "edit_id": edit_id,
                    "msg_id": msg_id,
                    "error": rej.error,
                    "failed_checks": rej.failed_checks,
                    "suggestions": rej.suggestions[:4],
                },
                cause=cause,
            )
            return
        revision = run.state["revision"] + 1
        for msg_type, event_payload in plan.events:
            run.emit(msg_type, event_payload, stage="edit", revision=revision, cause=cause)
        run.emit(
            "stage.completed",
            {"stage": "edit", "status": "ok", "duration_ms": elapsed()},
            stage="edit",
            cause=cause,
        )
        run.emit(
            "edit.applied",
            {
                "edit_id": edit_id,
                "msg_id": msg_id,
                "ops": copy.deepcopy(ops),
                "revision": revision,
                "duration_ms": elapsed(),
            },
            revision=revision,
            cause=cause,
        )
