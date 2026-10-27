"""REST for the fit check: photo in, measurement plus the agent's proposed next step out."""

from __future__ import annotations

import base64
import binascii
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from bara.rest import ApiError, body
from bara.vision import agent
from bara.vision import measure as m

MAX_IMAGE_BYTES = 12 * 1024 * 1024


def _num(raw: Any, name: str, lo: float, hi: float, default: float | None) -> float | None:
    if raw is None or raw == "":
        return default
    try:
        v = float(raw)
    except (TypeError, ValueError) as err:
        raise ApiError("E_BAD_MESSAGE", f"{name} must be a number.") from err
    if not lo <= v <= hi:
        raise ApiError("E_BAD_MESSAGE", f"{name} must be between {lo:g} and {hi:g}.")
    return v


def build_vision_router() -> APIRouter:
    api = APIRouter()

    @api.get("/v1/vision/status")
    def status() -> JSONResponse:
        return body({"opencv": m.cv2.__version__, "remote": agent._remote_url() is not None})

    @api.get("/v1/vision/marker.png")
    def marker(mm: float = 40.0) -> Response:
        size = _num(mm, "mm", 15, 150, 40.0) or 40.0
        return Response(m.marker_png(marker_mm=size), media_type="image/png")

    @api.post("/v1/vision/fit")
    async def fit(request: Request) -> JSONResponse:
        try:
            req = await request.json()
        except ValueError as err:
            raise ApiError("E_BAD_MESSAGE", "Body must be JSON.") from err
        if not isinstance(req, dict):
            raise ApiError("E_BAD_MESSAGE", "Body must be a JSON object.")
        raw = str(req.get("image_b64") or "")
        if "," in raw[:80]:
            raw = raw.split(",", 1)[1]  # tolerate data: URLs
        try:
            data = base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError) as err:
            raise ApiError("E_BAD_MESSAGE", "image_b64 is not base64.") from err
        if not data or len(data) > MAX_IMAGE_BYTES:
            raise ApiError("E_BAD_MESSAGE", "Send one photo under 12 MB.")
        mode = req.get("mode") or "fit_inside"
        if mode not in ("fit_inside", "match"):
            raise ApiError("E_BAD_MESSAGE", "mode is fit_inside or match.")
        enc = req.get("enclosure")
        enclosure = None
        if isinstance(enc, dict) and isinstance(enc.get("outer_size_mm"), list):
            size = [_num(v, "outer_size_mm", 0, 2000, 0.0) or 0.0 for v in enc["outer_size_mm"][:3]]
            enclosure = {
                "enclosure_id": str(enc.get("enclosure_id") or "")[:80],
                "outer_size_mm": (size + [0.0, 0.0, 0.0])[:3],
            }
        from starlette.concurrency import run_in_threadpool

        try:
            result = await run_in_threadpool(
                agent.decide,
                data,
                mode=mode,
                marker_mm=_num(req.get("marker_mm"), "marker_mm", 15, 150, 40.0) or 40.0,
                clearance_mm=_num(req.get("clearance_mm"), "clearance_mm", 0, 20, 2.0) or 0.0,
                height_limit_mm=_num(req.get("height_limit_mm"), "height_limit_mm", 3, 500, None),
                device=str(req.get("device") or "")[:400],
                enclosure=enclosure,
            )
        except ValueError as err:
            raise ApiError("E_BAD_MESSAGE", str(err)) from err
        return body(result)

    return api
