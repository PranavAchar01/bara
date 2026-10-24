"""Shared access token for a server exposed to the internet (BARA_ACCESS_TOKEN).

REST calls send it as the X-Bara-Token header. Browsers cannot set headers on a WebSocket or on
the URLs a GLB loader or a download link fetches, so those may send it as ?token= instead.
/v1/health stays open so the web app can tell "engine offline" from "wrong key".
"""

from __future__ import annotations

import hmac
import json
from urllib.parse import parse_qs

from starlette.types import ASGIApp, Receive, Scope, Send

HEADER = b"x-bara-token"
OPEN_PATHS = frozenset({"/v1/health"})


def _presented(scope: Scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name == HEADER:
            return value.decode("latin-1")
    query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
    values = query.get("token")
    return values[0] if values else None


class AccessTokenMiddleware:
    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.token = token.encode()

    def _allowed(self, scope: Scope) -> bool:
        got = _presented(scope)
        return got is not None and hmac.compare_digest(got.encode(), self.token)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        kind = scope["type"]
        if kind == "http" and (scope["method"] == "OPTIONS" or scope["path"] in OPEN_PATHS):
            await self.app(scope, receive, send)
            return
        if kind not in ("http", "websocket") or self._allowed(scope):
            await self.app(scope, receive, send)
            return
        if kind == "websocket":
            await receive()  # websocket.connect
            await send({"type": "websocket.close", "code": 4401, "reason": "access token required"})
            return
        body = json.dumps(
            {
                "spec_version": "1.1.0",
                "error": {
                    "code": "E_UNAUTHORIZED",
                    "message": "Access token required.",
                    "retryable": False,
                },
            }
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
