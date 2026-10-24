"""WebSocket /v1/ws, SPEC.md section 8.

Each socket has one outgoing queue drained by a writer task. Handlers never await between
queueing an ack and emitting the events it precedes, so ordering holds per socket.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from bara import SERVER_VERSION
from bara.schemas import client_def
from bara.services import Services
from bara.util import envelope, error_obj, new_session_id, now_ts

log = logging.getLogger(__name__)

MSG_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{8,64}$")
VERSION_RE = re.compile(r"^(\d+)\.\d+\.\d+$")
CLIENT_TYPES = {
    "build.start",
    "build.resume",
    "edit.apply",
    "build.cancel",
    "ping",
    "clarify.answer",
}
CAPABILITIES = ["replay", "live_edit", "clarify"]


class Session:
    def __init__(self) -> None:
        self.session_id = new_session_id()
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.builds: set[str] = set()

    def send(self, msg: dict[str, Any]) -> None:
        self.queue.put_nowait(msg)


def _ack(
    msg_id: str,
    accepted: bool,
    *,
    build_id: str | None = None,
    edit_id: str | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "msg_id": msg_id,
        "accepted": accepted,
        "duplicate": False,
        "build_id": build_id,
        "edit_id": edit_id,
        "error": error,
    }


class WsHandler:
    def __init__(self, svc: Services) -> None:
        self.svc = svc

    async def serve(self, websocket: WebSocket) -> None:
        await websocket.accept()
        session = Session()

        async def writer() -> None:
            while True:
                msg = await session.queue.get()
                await websocket.send_text(json.dumps(msg))

        writer_task = asyncio.create_task(writer())
        limits = {
            "max_prompt_chars": 2000,
            "max_ops_per_edit": 20,
            "msg_id_ttl_s": self.svc.settings.msg_id_ttl_s,
        }
        session.send(
            envelope(
                "hello",
                {
                    "server_version": SERVER_VERSION,
                    "session_id": session.session_id,
                    "mock": self.svc.settings.mock,
                    "limits": limits,
                    "capabilities": CAPABILITIES,
                },
            )
        )
        try:
            while True:
                text = await websocket.receive_text()
                self.handle(session, text)
        except WebSocketDisconnect:
            pass
        except RuntimeError as exc:  # socket closed under us
            log.info("ws closed: %s", exc)
        finally:
            for build_id in session.builds:
                run = self.svc.engine.get(build_id)
                if run is not None:
                    run.subscribers.pop(id(session), None)
            writer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await writer_task

    # ---- helpers -------------------------------------------------------------
    def _subscribe(self, session: Session, run) -> None:
        run.subscribers[id(session)] = session.send
        session.builds.add(run.build_id)

    def _reject(self, session: Session, msg_id: str | None, code: str, message: str) -> None:
        err = error_obj(code, message)
        if msg_id is not None:
            session.send(envelope("ack", _ack(msg_id, False, error=err)))
        else:
            session.send(envelope("error", {"error": err, "msg_id": None}))

    def _answer(self, session: Session, msg_id: str, ack: dict[str, Any]) -> None:
        self.svc.dedupe.put(msg_id, ack)
        session.send(envelope("ack", ack))

    # ---- dispatch ------------------------------------------------------------
    def handle(self, session: Session, text: str) -> None:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            self._reject(session, None, "E_BAD_MESSAGE", "Message is not valid JSON.")
            return
        if not isinstance(data, dict):
            self._reject(session, None, "E_BAD_MESSAGE", "Message must be a JSON object.")
            return
        raw_id = data.get("msg_id")
        msg_id = raw_id if isinstance(raw_id, str) and MSG_ID_RE.match(raw_id) else None
        version = data.get("spec_version")
        match = VERSION_RE.match(version) if isinstance(version, str) else None
        if match and match.group(1) != "1":
            self._reject(
                session,
                msg_id,
                "E_UNSUPPORTED_VERSION",
                f"spec_version {version} is not supported; this server speaks 1.x.",
            )
            return
        msg_type = data.get("type")
        if msg_type not in CLIENT_TYPES:
            self._reject(session, msg_id, "E_BAD_MESSAGE", f"Unknown message type {msg_type!r}.")
            return
        errors = self.svc.schemas.errors(client_def(msg_type), data)
        if errors:
            self._reject(session, msg_id, "E_BAD_MESSAGE", f"Bad {msg_type}: {errors[0]}"[:500])
            return
        assert msg_id is not None  # the schema requires a valid msg_id
        if msg_type == "ping":
            session.send(envelope("pong", {"msg_id": msg_id, "server_time": now_ts()}))
            return
        first = self.svc.dedupe.get(msg_id)
        if first is not None:
            first["duplicate"] = True
            session.send(envelope("ack", first))
            return
        payload = data["payload"]
        getattr(self, "_on_" + msg_type.replace(".", "_"))(session, msg_id, payload)

    def _run_or_reject(self, session: Session, msg_id: str, build_id: str):
        run = self.svc.engine.get(build_id)
        if run is None:
            err = error_obj("E_UNKNOWN_BUILD", f"No build {build_id}.")
            self._answer(session, msg_id, _ack(msg_id, False, build_id=build_id, error=err))
        return run

    def _on_build_start(self, session: Session, msg_id: str, payload: dict[str, Any]) -> None:
        engine = self.svc.engine
        run = engine.start(payload["prompt"], payload.get("options"))
        self._subscribe(session, run)
        self._answer(session, msg_id, _ack(msg_id, True, build_id=run.build_id))
        engine.launch(run)

    def _on_build_resume(self, session: Session, msg_id: str, payload: dict[str, Any]) -> None:
        run = self._run_or_reject(session, msg_id, payload["build_id"])
        if run is None:
            return
        self._answer(session, msg_id, _ack(msg_id, True, build_id=run.build_id))
        last_seq = payload["last_seq"]
        if last_seq < run.seq:
            if last_seq + 1 < run.oldest_seq:
                err = error_obj(
                    "E_RESUME_GAP",
                    f"Events after seq {last_seq} are no longer kept; sending a snapshot.",
                    details={"oldest_seq": run.oldest_seq},
                )
                session.send(
                    envelope("error", {"error": err, "msg_id": msg_id}, build_id=run.build_id)
                )
                session.send(run.snapshot("resume_gap"))
            else:
                for event in run.log:
                    if event["seq"] > last_seq:
                        session.send(event)
        self._subscribe(session, run)

    def _on_edit_apply(self, session: Session, msg_id: str, payload: dict[str, Any]) -> None:
        run = self._run_or_reject(session, msg_id, payload["build_id"])
        if run is None:
            return
        engine = self.svc.engine
        err = engine.edit_not_ready(run)
        if err is None and len(payload["ops"]) > 20:
            err = error_obj("E_INVALID_EDIT", "An edit takes at most 20 ops.", stage="edit")
        if err is not None:
            self._answer(session, msg_id, _ack(msg_id, False, build_id=run.build_id, error=err))
            return
        self._subscribe(session, run)
        edit_id = engine.next_edit_id(run)
        self._answer(session, msg_id, _ack(msg_id, True, build_id=run.build_id, edit_id=edit_id))
        engine.apply_edit(run, msg_id, edit_id, payload)

    def _on_build_cancel(self, session: Session, msg_id: str, payload: dict[str, Any]) -> None:
        run = self._run_or_reject(session, msg_id, payload["build_id"])
        if run is None:
            return
        self._answer(session, msg_id, _ack(msg_id, True, build_id=run.build_id))
        self.svc.engine.cancel(run, msg_id)

    def _on_clarify_answer(self, session: Session, msg_id: str, payload: dict[str, Any]) -> None:
        run = self._run_or_reject(session, msg_id, payload["build_id"])
        if run is None:
            return
        err = self.svc.engine.answer_clarify(run, msg_id, payload)
        if err is not None:
            self._answer(session, msg_id, _ack(msg_id, False, build_id=run.build_id, error=err))
            return
        self._answer(session, msg_id, _ack(msg_id, True, build_id=run.build_id))
