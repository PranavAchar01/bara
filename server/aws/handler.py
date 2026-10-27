"""AWS Lambda entry for the fit measurement (arm64 / Graviton, behind a function URL).

POST {"image_b64": "...", "marker_mm": 40, "enhance": false} -> the same JSON measure() returns.
Each call logs one JSON line (status, timings, sizes; never the image) for CloudWatch.
"""

from __future__ import annotations

import base64
import json
import logging
import time

import measure as m

log = logging.getLogger("fit")
log.setLevel(logging.INFO)

MAX_IMAGE_BYTES = 4 * 1024 * 1024  # function URL payloads stop at 6 MB of base64


def _reply(code: int, payload: dict) -> dict:
    return {
        "statusCode": code,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(payload),
    }


def handler(event, _context):
    t0 = time.perf_counter()
    method = (event.get("requestContext", {}).get("http", {}) or {}).get("method", "POST")
    if method == "GET":
        return _reply(200, {"ok": True, "opencv": m.cv2.__version__})
    try:
        raw = event.get("body") or ""
        if event.get("isBase64Encoded"):
            raw = base64.b64decode(raw).decode("utf-8")
        req = json.loads(raw)
        data = base64.b64decode(req["image_b64"], validate=True)
        marker_mm = float(req.get("marker_mm") or 40.0)
        enhance = bool(req.get("enhance"))
    except (KeyError, ValueError, TypeError):
        return _reply(400, {"error": "send JSON with image_b64 (base64 JPEG or PNG)"})
    if not data or len(data) > MAX_IMAGE_BYTES or not 15 <= marker_mm <= 150:
        return _reply(400, {"error": "one photo under 4 MB, marker_mm between 15 and 150"})
    try:
        out = m.measure(data, marker_mm=marker_mm, enhance=enhance)
    except ValueError as err:
        return _reply(400, {"error": str(err)})
    out["lambda_ms"] = round((time.perf_counter() - t0) * 1e3, 1)
    obj = out.get("object") or {}
    log.info(
        json.dumps(
            {
                "event": "fit_measure",
                "status": out["status"],
                "opencv": out["opencv"],
                "image_px": out["image_px"],
                "width_mm": obj.get("width_mm"),
                "depth_mm": obj.get("depth_mm"),
                "measure_ms": out["ms"],
                "lambda_ms": out["lambda_ms"],
            }
        )
    )
    return _reply(200, out)
