"""REST routes for the simulator screen, under /v1/builds/{build_id}/sim."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, PlainTextResponse

from bara import part_ask
from bara.library import BUILD_ID_RE
from bara.reducer import apply_event, new_build

from .agent import ai_labels, apply_labels, chat_patch
from .codegen import FwConfig
from .io import controller_part
from .session import SimBuild, SimStore
from .surface import SurfaceStore, make_surface

INPUT_ACTIONS = {"press", "release", "tap", "turn", "axis", "sensor", "power", "reset"}


def mcu_part(state: dict[str, Any]) -> dict[str, Any] | None:
    return controller_part([p for p in state.get("parts") or [] if p.get("instance_id")])


def _label(session: Any, input_id: str) -> str:
    row = session.inputs.by_id.get(input_id) or {}
    return str(row.get("label") or "").lower()


def scene_of(raw: Any) -> dict[str, Any] | None:
    """The combined device the page says this build stands in, cut to plain short strings."""
    if not isinstance(raw, dict) or not isinstance(raw.get("title"), str):
        return None

    def texts(v: Any) -> list[str]:
        return [str(x)[:200] for x in v[:8] if isinstance(x, str)] if isinstance(v, list) else []

    return {
        "title": raw["title"][:80],
        "testing": str(raw.get("testing") or "")[:300],
        "devices": texts(raw.get("devices")),
        "flows": texts(raw.get("flows")),
    }


def sim_routes(api: APIRouter, svc: Any) -> None:
    from bara.rest import ApiError, body  # rest imports this module inside build_router

    store = SimStore(
        svc.settings.assets_dir, boards_root=svc.settings.data_dir / "cache" / "boards"
    )
    surfaces = SurfaceStore(svc.settings.data_dir / "cache" / "sim_surface")
    models = {
        "cerebras_model": svc.settings.cerebras_model,
        "anthropic_model": svc.settings.anthropic_model,
    }

    def build_state(build_id: str) -> dict[str, Any]:
        if not BUILD_ID_RE.fullmatch(build_id):
            raise ApiError("E_UNKNOWN_BUILD", f"No build {build_id}.")
        run = svc.engine.get(build_id)
        if run is not None:
            return run.state
        entry = svc.engine.library.get(build_id)
        if entry is None:
            raise ApiError("E_UNKNOWN_BUILD", f"No build {build_id}.")
        state: dict[str, Any] | None = new_build(
            build_id, str(entry.get("prompt") or ""), str(entry.get("created_at") or "")
        )
        for ev in entry.get("events") or []:
            state = apply_event(state, ev) or state
        return state or {}

    # One start/rebuild at a time per build: all SimBuilds of a build compile into one folder,
    # and a page that mounts twice (or two tabs) sends two starts at once.
    locks: dict[str, asyncio.Lock] = {}
    recent: dict[str, tuple[float, str]] = {}

    def lock_for(build_id: str) -> asyncio.Lock:
        return locks.setdefault(build_id, asyncio.Lock())

    def part_record(part_id: str) -> dict[str, Any] | None:
        record = svc.catalog.part(part_id)
        if record is None and svc.engine.live is not None:
            try:
                record = svc.engine.live.source.get_part(part_id)
            except KeyError:
                record = None
        return record

    def with_controller_record(state: dict[str, Any]) -> dict[str, Any]:
        """Attach the controller's part record: the card is generic, the record says which chip."""
        mcu = mcu_part(state)
        if mcu is None or not mcu.get("part_id"):
            return state
        rec = part_record(str(mcu["part_id"])) or {}
        keep = {k: rec.get(k) for k in ("display_name", "mpn", "facets") if rec.get(k)}
        parts = [
            {**p, "record": keep} if p.get("instance_id") == mcu.get("instance_id") else p
            for p in state.get("parts") or []
        ]
        return {**state, "parts": parts}

    def need(build_id: str) -> SimBuild:
        sb = store.get(build_id)
        if sb is None:
            raise ApiError("E_NOT_FOUND", "Start the simulator first (POST .../sim/start).")
        return sb

    async def json_body(request: Request) -> dict[str, Any]:
        try:
            data = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ApiError("E_BAD_MESSAGE", "Body is not JSON.") from exc
        if not isinstance(data, dict):
            raise ApiError("E_BAD_MESSAGE", "Body must be an object.")
        return data

    @api.post("/v1/builds/{build_id}/sim/start")
    async def sim_start(build_id: str, request: Request) -> JSONResponse:
        """Plan the inputs and outputs, label them, compile the firmware, boot it."""
        data = await json_body(request) if await request.body() else {}
        key = json.dumps(data, sort_keys=True)
        async with lock_for(build_id):
            last = recent.get(build_id)
            sb = store.get(build_id)
            if sb is not None and last and last[1] == key and time.monotonic() - last[0] < 10:
                return body({"sim": sb.view()})  # the same start a moment ago: reuse it
            state = with_controller_record(build_state(build_id))
            if mcu_part(state) is None:
                raise ApiError(
                    "E_NOT_FOUND", "This build has no controller, so no firmware to run."
                )
            sb = store.create(build_id, state)
            client = {str(k): str(v) for k, v in (data.get("names") or {}).items()}
            codes = {str(k): str(v) for k, v in (data.get("codes") or {}).items()}
            sb.cfg = FwConfig.from_dict(data.get("config"))
            sb.scene = scene_of(data.get("scene"))
            sb.plan(client, codes)
            if data.get("labels", True):
                labels, notes = await ai_labels(state, sb.io, **models)
                sb.label_notes = notes
                if labels:
                    sb.labels = labels
                    apply_labels(sb.io, labels)
            await run_in_threadpool(sb.compile)
            recent[build_id] = (time.monotonic(), key)
            return body({"sim": sb.view()})

    @api.get("/v1/builds/{build_id}/sim")
    def sim_get(build_id: str) -> JSONResponse:
        return body({"sim": need(build_id).view()})

    @api.post("/v1/builds/{build_id}/sim/input")
    async def sim_input(build_id: str, request: Request) -> JSONResponse:
        sb = need(build_id)
        data = await json_body(request)
        action, iid = data.get("action"), str(data.get("id") or "")
        since = int(data.get("since") or 0)
        if action not in INPUT_ACTIONS:
            raise ApiError("E_BAD_MESSAGE", f"action must be one of {sorted(INPUT_ACTIONS)}.")
        s = sb.session
        if s is None:
            raise ApiError("E_NOT_FOUND", "The firmware did not build, so nothing is running.")

        def act() -> dict[str, Any]:
            with sb.lock:
                try:
                    if action == "power":
                        s.set_power(bool(data.get("value", True)))
                    elif action == "reset":  # value true = boot button held: bootloader
                        s.reboot(bootloader=bool(data.get("value")))
                    elif action == "turn":
                        s.turn(iid, int(data.get("value") or 1))
                    elif action == "sensor":
                        s.set_sensor(iid, float(data.get("value") or 0.0))
                    elif action == "axis":
                        s.set_axis(iid, float(data.get("value") or 0.0))
                    elif action == "tap":
                        s.press(iid, True)
                        s.run_ms(40)
                        s.press(iid, False)
                    else:
                        s.press(iid, action == "press")
                    pressed = action in ("press", "tap")
                    if pressed and "reset" in _label(s, iid):
                        # the reset button restarts the chip; with the boot button held it
                        # comes up in the bootloader instead of the firmware
                        boot_held = any(
                            "boot" in _label(s, k) for k, v in s.inputs.closed.items() if v
                        )
                        s.reboot(bootloader=boot_held)
                except KeyError as exc:
                    raise ApiError("E_BAD_MESSAGE", f"No input {iid}.") from exc
                s.run_ms(float(data.get("run_ms") or 20))
                return s.snapshot(since)

        return body({"snapshot": await run_in_threadpool(act)})

    @api.post("/v1/builds/{build_id}/sim/run")
    async def sim_run(build_id: str, request: Request) -> JSONResponse:
        sb = need(build_id)
        data = await json_body(request)
        ms = max(0.0, min(float(data.get("ms") or 100), 5000.0))
        since = int(data.get("since") or 0)
        s = sb.session
        if s is None:
            raise ApiError("E_NOT_FOUND", "The firmware did not build, so nothing is running.")

        def go() -> dict[str, Any]:
            with sb.lock:
                s.run_ms(ms)
                return s.snapshot(since)

        return body({"snapshot": await run_in_threadpool(go)})

    @api.post("/v1/builds/{build_id}/sim/surface")
    async def sim_surface(build_id: str, request: Request) -> JSONResponse:
        """The play surface: which controls, how each output shows. One model call, checked
        against the real parts and cached per build; the parts alone decide when none answers."""
        sb = need(build_id)
        data = await json_body(request) if await request.body() else {}
        surface = await make_surface(
            sb.state, sb.io, surfaces, build_id, **models, refresh=bool(data.get("refresh"))
        )
        return body({"surface": surface})

    @api.post("/v1/builds/{build_id}/sim/reset")
    async def sim_reset(build_id: str) -> JSONResponse:
        sb = need(build_id)
        await run_in_threadpool(sb.start)
        return body({"sim": sb.view()})

    @api.post("/v1/builds/{build_id}/sim/tests")
    async def sim_tests(build_id: str, request: Request) -> JSONResponse:
        sb = need(build_id)
        data = await json_body(request) if await request.body() else {}
        ids = data.get("ids")
        if ids is not None and not (isinstance(ids, list) and all(isinstance(i, str) for i in ids)):
            raise ApiError("E_BAD_MESSAGE", "ids must be a list of test ids.")
        async with lock_for(build_id):
            results = await run_in_threadpool(sb.run_tests, ids)
        return body({"results": results, "sim": sb.view()})

    @api.post("/v1/builds/{build_id}/sim/config")
    async def sim_config(build_id: str, request: Request) -> JSONResponse:
        """Change firmware settings by hand, then rebuild and boot."""
        sb = need(build_id)
        data = await json_body(request)
        merged = {**sb.cfg.to_dict(), **data}
        async with lock_for(build_id):
            sb.cfg = FwConfig.from_dict(merged)
            sb.plan()
            await run_in_threadpool(sb.compile)
        return body({"sim": sb.view()})

    @api.post("/v1/builds/{build_id}/sim/chat")
    async def sim_chat(build_id: str, request: Request) -> JSONResponse:
        """Talk to the build agent: a change rebuilds the firmware and re-runs the tests."""
        sb = need(build_id)
        data = await json_body(request)
        message = str(data.get("message") or "").strip()[:1000]
        if not message:
            raise ApiError("E_BAD_MESSAGE", "Send a message.")
        sb.chat.append({"role": "user", "text": message})
        patch, reply, kind, by = await chat_patch(
            message, sb.cfg.to_dict(), sb.io, **models, scene=sb.scene
        )
        rebuilt = False
        ops = patch.pop("surface_ops", [])
        if ops and not reply:
            reply = "Done."
        if kind == "question" and not patch and not ops:
            mcu = mcu_part(sb.state)
            if mcu and mcu.get("part_id") and not reply:
                ans, _note = await part_ask.answer(sb.state, mcu["part_id"], message, **models)
                if ans:
                    reply = ans.answer
        results: list[dict[str, Any]] = []
        if patch:  # firmware settings changed
            merged = {**sb.cfg.to_dict(), **{k: v for k, v in patch.items() if k != "labels"}}
            merged["labels"] = {**sb.cfg.labels, **(patch.get("labels") or {})}
            async with lock_for(build_id):
                sb.cfg = FwConfig.from_dict(merged)
                sb.plan()
                await run_in_threadpool(sb.compile)
                rebuilt = True
                # every check that can run again does: firmware, emulation, pin map, ngspice, KiCad
                results = await run_in_threadpool(
                    sb.run_tests, [t["id"] for t in sb.view()["tests"]]
                )
        passed = sum(1 for r in results if r["status"] == "pass")
        failed = sum(1 for r in results if r["status"] == "fail")
        entry = {
            "role": "agent",
            "text": reply,
            "changes": patch,
            "surface_ops": ops,
            "rebuilt": rebuilt,
            "by": by,
            "build_status": sb.fw.get("status") if rebuilt else None,
            "tests": {"passed": passed, "failed": failed} if results else None,
        }
        sb.chat.append(entry)
        return body({"reply": entry, "sim": sb.view()})

    @api.get("/v1/builds/{build_id}/sim/source/{name}")
    def sim_source(build_id: str, name: str) -> PlainTextResponse:
        text = need(build_id).source(name)
        if text is None:
            raise ApiError("E_NOT_FOUND", f"No source file {name}.")
        return PlainTextResponse(text)
