"""Small shared helpers: timestamps, ids, error objects and envelopes."""

from __future__ import annotations

import secrets
import string
from datetime import UTC, datetime
from typing import Any

from bara import SPEC_VERSION

# SPEC.md section 10: code -> (http status, retryable)
ERROR_TABLE: dict[str, tuple[int, bool]] = {
    "E_BAD_MESSAGE": (400, False),
    "E_UNSUPPORTED_VERSION": (400, False),
    "E_NOT_FOUND": (404, False),
    "E_UNKNOWN_BUILD": (404, False),
    "E_BUILD_NOT_READY": (409, True),
    "E_STALE_REVISION": (409, True),
    "E_UNKNOWN_PART": (404, False),
    "E_UNKNOWN_INSTANCE": (409, False),
    "E_UNKNOWN_INTERFACE": (409, False),
    "E_INVALID_EDIT": (400, False),
    "E_INCOMPATIBLE": (409, False),
    "E_CRITICAL_PART_MISSING": (422, False),
    "E_CLASSIFY_FAILED": (422, False),
    "E_LLM_UNAVAILABLE": (503, True),
    "E_LLM_TIMEOUT": (504, True),
    "E_SOLVER_INFEASIBLE": (422, False),
    "E_SOLVER_TIMEOUT": (504, True),
    "E_ENCLOSURE_FAILED": (500, True),
    "E_BOARD_FAILED": (500, True),
    "E_FIRMWARE_FAILED": (500, True),
    "E_ASSET_MISSING": (404, False),
    "E_LICENCE_BLOCKED": (422, False),
    "E_RESUME_GAP": (409, False),
    "E_CANCELLED": (409, False),
    "E_CLARIFY_NOT_PENDING": (409, False),
    "E_INVALID_ANSWER": (400, False),
    "E_OUT_OF_SCOPE": (422, False),
    "E_RATE_LIMITED": (429, True),
    "E_INTERNAL": (500, True),
    "E_UNKNOWN": (500, True),
}

_ALNUM = string.ascii_letters + string.digits


def now_ts() -> str:
    """RFC 3339 UTC with milliseconds, for example 2026-10-24T18:02:11.120Z."""
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def new_build_id() -> str:
    return "b_" + "".join(secrets.choice(_ALNUM) for _ in range(12))


def new_session_id() -> str:
    return "s_" + "".join(secrets.choice(_ALNUM) for _ in range(10))


def http_status(code: str) -> int:
    return ERROR_TABLE.get(code, (500, True))[0]


def error_obj(
    code: str,
    message: str,
    *,
    stage: str | None = None,
    subjects: list[dict[str, Any]] | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    err: dict[str, Any] = {
        "code": code,
        "message": message[:500],
        "retryable": ERROR_TABLE.get(code, (500, True))[1],
    }
    if stage is not None:
        err["stage"] = stage
    if subjects is not None:
        err["subjects"] = subjects
    if details is not None:
        err["details"] = details
    return err


def envelope(
    msg_type: str,
    payload: dict[str, Any],
    *,
    seq: int = 0,
    build_id: str | None = None,
    stage: str | None = None,
    revision: int | None = None,
    cause: dict[str, Any] | None = None,
) -> dict[str, Any]:
    msg: dict[str, Any] = {
        "spec_version": SPEC_VERSION,
        "type": msg_type,
        "seq": seq,
        "build_id": build_id,
        "ts": now_ts(),
    }
    if stage is not None:
        msg["stage"] = stage
    if revision is not None:
        msg["revision"] = revision
    if cause:
        msg["cause"] = cause
    msg["payload"] = payload
    return msg
