"""Section 9 reducer: apply build events in seq order to one Build object."""

from __future__ import annotations

import copy
import logging
from typing import Any

log = logging.getLogger(__name__)

CONNECTION_SCOPED = {"hello", "ack", "pong", "error"}

# list field -> id key, for replace-or-append events
_UPSERT = {
    "decision.made": ("decisions", "decision", "decision_id"),
    "layout.added": ("layouts", "layout", "layout_id"),
    "part.added": ("parts", "part", "instance_id"),
    "part.updated": ("parts", "part", "instance_id"),
    "connection.added": ("connections", "connection", "connection_id"),
    "enclosure.updated": ("enclosures", "enclosure", "enclosure_id"),
    "board.updated": ("boards", "board", "board_id"),
    "slot.updated": ("slots", "slot", "slot_id"),
    "warning": ("warnings", "warning", "warning_id"),
}

_REMOVE = {
    "decision.reverted": ("decisions", "decision_id"),
    "part.removed": ("parts", "instance_id"),
    "connection.removed": ("connections", "connection_id"),
}

_NO_CHANGE = {
    "candidates.ready",
    "stage.started",
    "stage.progress",
    "firmware.progress",
    "edit.applied",
    "edit.rejected",
}


def new_build(build_id: str, prompt: str, created_at: str) -> dict[str, Any]:
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
        "created_at": created_at,
    }


def _upsert(items: list[dict[str, Any]], key: str, obj: dict[str, Any]) -> None:
    for i, existing in enumerate(items):
        if existing.get(key) == obj.get(key):
            items[i] = copy.deepcopy(obj)
            return
    items.append(copy.deepcopy(obj))


def apply_event(build: dict[str, Any] | None, msg: dict[str, Any]) -> dict[str, Any] | None:
    """Apply one server message. Returns the (possibly replaced) build."""
    kind = msg.get("type")
    if kind in CONNECTION_SCOPED:
        return build
    payload = msg.get("payload", {})
    if kind == "build.snapshot":
        return copy.deepcopy(payload["build"])
    if build is None:
        return None

    if kind in _UPSERT:
        field, inner, key = _UPSERT[kind]
        _upsert(build[field], key, payload[inner])
    elif kind in _REMOVE:
        field, key = _REMOVE[kind]
        build[field] = [x for x in build[field] if x.get(key) != payload.get(key)]
    elif kind == "spec.ready":
        build["spec"] = copy.deepcopy(payload["spec"])
    elif kind == "reuse.decided":
        build["tier"] = payload.get("tier", "unknown")
        build["design_id"] = payload.get("design_id")
    elif kind == "slots.ready":
        build["slots"] = copy.deepcopy(payload["slots"])
    elif kind == "placement.updated":
        by_id = {p["instance_id"]: p for p in build["parts"]}
        for entry in payload.get("placements", []):
            part = by_id.get(entry["instance_id"])
            if part is not None:
                part["placement"] = copy.deepcopy(entry["placement"])
    elif kind == "firmware.ready":
        build["firmware"] = copy.deepcopy(payload["firmware"])
    elif kind == "scene.ready":
        build["scene"] = copy.deepcopy(payload["scene"])
    elif kind == "check.result":
        for result in payload.get("results", []):
            _upsert(build["checks"], "check_key", result)
    elif kind == "stage.completed":
        if payload.get("stage") != "edit":
            build["timings_ms"][payload["stage"]] = payload.get("duration_ms", 0)
    elif kind == "clarify.request":
        build["clarify"] = copy.deepcopy(payload)
        build["status"] = "awaiting_input"
    elif kind == "clarify.resolved":
        build["clarifications"].append(copy.deepcopy(payload))
        build["clarify"] = None
        build["status"] = "running"
    elif kind == "build.done":
        build["status"] = "done"
    elif kind == "build.failed":
        err = payload.get("error") or {}
        build["status"] = "cancelled" if err.get("code") == "E_CANCELLED" else "failed"
        build["error"] = copy.deepcopy(err)
        build["clarify"] = None
    elif kind not in _NO_CHANGE:
        log.info("reducer: unknown event type %s ignored", kind)

    if "revision" in msg:
        build["revision"] = msg["revision"]
    if isinstance(msg.get("seq"), int):
        build["last_seq"] = msg["seq"]
    return build


def reduce_stream(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Reduce a recorded stream of client and server messages (fixture order).

    A build is created by the ack for a build.start, using the prompt and ts of that
    build.start (created_at).
    """
    build: dict[str, Any] | None = None
    starts: dict[str, dict[str, Any]] = {}
    for msg in messages:
        if msg.get("type") == "build.start" and "seq" not in msg:
            starts[msg["msg_id"]] = msg
            continue
        if "seq" not in msg:
            continue
        if msg["type"] == "ack":
            start = starts.get(msg["payload"].get("msg_id"))
            if start and msg["payload"].get("accepted") and not msg["payload"].get("duplicate"):
                build = new_build(
                    msg["payload"]["build_id"],
                    start["payload"]["prompt"],
                    start.get("ts") or msg["ts"],
                )
            continue
        build = apply_event(build, msg)
    return build
