"""REST API, SPEC.md section 7. Every body carries spec_version; every non 2xx body is
ErrorResponse."""

from __future__ import annotations

import io
import json
import re
import time
import zipfile
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from bara import SERVER_VERSION, SPEC_VERSION, geometry, part_ask, voice
from bara.edits import Reject
from bara.llm import providers_configured
from bara.services import Services
from bara.util import error_obj, http_status

EXPORT_FORMATS = {"bom_csv", "stl", "3mf", "step", "kicad", "firmware_zip", "zip"}
GEOMETRY_FORMATS = {"stl": "stl", "3mf": "3mf", "step": "step", "kicad": "zip"}


class ApiError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


def error_response(code: str, message: str, details: dict[str, Any] | None = None):
    return JSONResponse(
        {"spec_version": SPEC_VERSION, "error": error_obj(code, message, details=details)},
        status_code=http_status(code),
    )


def body(data: dict[str, Any], status_code: int = 200) -> JSONResponse:
    return JSONResponse({"spec_version": SPEC_VERSION, **data}, status_code=status_code)


def _int_param(request: Request, name: str, default: int, lo: int, hi: int) -> int:
    raw = request.query_params.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ApiError("E_BAD_MESSAGE", f"{name} must be an integer.") from exc
    if value < lo or value > hi:
        raise ApiError("E_BAD_MESSAGE", f"{name} must be between {lo} and {hi}.")
    return value


def _page(items: list[Any], request: Request, default: int, hi: int) -> tuple[list[Any], Any]:
    limit = _int_param(request, "limit", default, 1, hi)
    cursor = request.query_params.get("cursor") or "0"
    if not cursor.isdigit():
        raise ApiError("E_BAD_MESSAGE", "cursor is not valid.")
    start = int(cursor)
    page = items[start : start + limit]
    nxt = str(start + limit) if start + limit < len(items) else None
    return page, nxt


def _words(text: str) -> set[str]:
    return {w for w in re.split(r"[^a-z0-9]+", text.lower()) if w}


def _value_matches(actual: Any, wanted: str) -> bool:
    if isinstance(actual, bool):
        return str(actual).lower() == wanted.lower()
    if isinstance(actual, list):
        return any(_value_matches(a, wanted) for a in actual)
    return str(actual).lower() == wanted.lower()


def build_router(svc: Services) -> APIRouter:
    api = APIRouter()
    cat = svc.catalog

    def run_or_404(build_id: str):
        run = svc.engine.get(build_id)
        if run is None:
            raise ApiError("E_UNKNOWN_BUILD", f"No build {build_id}.")
        return run

    @api.get("/v1/health")
    def health() -> JSONResponse:
        keys = providers_configured()
        any_llm = keys["cerebras"] or keys["anthropic"]
        cerebras = {
            "provider": "cerebras",
            "model": svc.settings.cerebras_model,
            "status": "ok" if keys["cerebras"] else "down",
        }
        anthropic = {
            "provider": "anthropic",
            "model": svc.settings.anthropic_model,
            "status": "ok" if keys["anthropic"] else "down",
        }
        # name the provider that actually serves calls: without a Cerebras key, Anthropic does
        primary, fallback = (cerebras, anthropic) if keys["cerebras"] else (anthropic, cerebras)
        return body(
            {
                "status": "ok" if any_llm else "degraded",
                "server_version": SERVER_VERSION,
                "mock": svc.settings.mock,
                "llm": primary,
                "llm_fallback": fallback,
                "part_count": len(cat.parts),
                "design_count": len(cat.designs),
                "uptime_s": int(time.monotonic() - svc.started),
            }
        )

    @api.get("/v1/vocab")
    def vocab() -> JSONResponse:
        return body(dict(cat.vocab))

    @api.get("/v1/facets")
    def facets() -> JSONResponse:
        return body(dict(cat.facets))

    @api.get("/v1/parts")
    def parts(request: Request) -> JSONResponse:
        q = _words(request.query_params.get("q") or "")
        function = request.query_params.get("function")
        interface = request.query_params.get("interface")
        facet_filters = [
            (k[len("facet.") :], v)
            for k, v in request.query_params.multi_items()
            if k.startswith("facet.")
        ]
        matches = []
        for part_id, card in cat.cards.items():
            part = cat.part(part_id) or {}
            if q:
                hay = _words(
                    " ".join(
                        str(x)
                        for x in (part_id, card.get("display_name"), card.get("summary"))
                        if x
                    )
                )
                if not q <= hay:
                    continue
            if function:
                fns = {f.get("function_id") for f in part.get("functions", [])}
                fns.add(card.get("primary_function"))
                if function not in fns:
                    continue
            if interface and not any(
                i.get("type") == interface for i in part.get("interfaces", [])
            ):
                continue
            part_facets = part.get("facets", {})
            if any(
                key not in part_facets or not _value_matches(part_facets[key], value)
                for key, value in facet_filters
            ):
                continue
            matches.append(card)
        page, nxt = _page(matches, request, 20, 100)
        return body({"items": page, "next_cursor": nxt, "total": len(matches)})

    @api.get("/v1/parts/{part_id:path}")
    def part(part_id: str) -> JSONResponse:
        record = cat.part(part_id)
        if record is None:
            raise ApiError("E_UNKNOWN_PART", f"No part {part_id}.")
        return body({"part": record})

    @api.get("/v1/designs")
    def designs(request: Request) -> JSONResponse:
        q = _words(request.query_params.get("q") or "")
        device_class = request.query_params.get("device_class")
        items = []
        for design_id, card in cat.design_cards.items():
            design = cat.designs.get(design_id, {})
            if device_class and card.get("device_class") != device_class:
                continue
            if q:
                hay = _words(
                    " ".join([design_id, card.get("name", "")] + design.get("aliases", []))
                )
                if not q <= hay:
                    continue
            items.append(card)
        page, nxt = _page(items, request, 20, 100)
        return body({"items": page, "next_cursor": nxt, "total": len(items)})

    @api.get("/v1/designs/{design_id}")
    def design(design_id: str) -> JSONResponse:
        record = cat.designs.get(design_id)
        if record is None:
            raise ApiError("E_NOT_FOUND", f"No design {design_id}.")
        return body({"design": record})

    @api.post("/v1/builds")
    async def create_build(request: Request) -> JSONResponse:
        try:
            data = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ApiError("E_BAD_MESSAGE", "Body is not JSON.") from exc
        errors = svc.schemas.errors("rest.schema.json#/$defs/CreateBuildRequest", data)
        if errors:
            raise ApiError("E_BAD_MESSAGE", f"Bad request body: {errors[0]}")
        run = svc.engine.start(data["prompt"], data.get("options"))
        svc.engine.launch(run)
        return body(
            {
                "build_id": run.build_id,
                "ws_url": "/v1/ws",
                "events_url": f"/v1/builds/{run.build_id}/events",
            },
            201,
        )

    @api.get("/v1/builds/{build_id}")
    def get_build(build_id: str) -> JSONResponse:
        return body({"build": run_or_404(build_id).state})

    @api.get("/v1/builds/{build_id}/events")
    def events(build_id: str, request: Request) -> JSONResponse:
        run = run_or_404(build_id)
        after = _int_param(request, "after_seq", 0, 0, 10**9)
        limit = _int_param(request, "limit", 500, 1, 5000)
        if after < run.seq and after + 1 < run.oldest_seq:
            raise ApiError(
                "E_RESUME_GAP",
                f"Events after seq {after} are no longer kept; GET the build instead.",
                {"oldest_seq": run.oldest_seq},
            )
        page = [e for e in run.log if e["seq"] > after][:limit]
        next_after = page[-1]["seq"] if page else after
        return body(
            {
                "build_id": build_id,
                "events": page,
                "next_after_seq": next_after,
                "complete": run.stream_complete and next_after >= run.seq,
            }
        )

    @api.post("/v1/builds/{build_id}/ask")
    async def ask_part(build_id: str, request: Request) -> JSONResponse:
        """A spoken-style answer about one part of the build (focus card, voice agent)."""
        run = run_or_404(build_id)
        try:
            data = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ApiError("E_BAD_MESSAGE", "Body is not JSON.") from exc
        part_id, question = data.get("part_id"), data.get("question")
        if not isinstance(part_id, str) or not isinstance(question, str) or not question.strip():
            raise ApiError("E_BAD_MESSAGE", "Send part_id and question.")
        result, note = await part_ask.answer(
            run.state,
            part_id,
            question,
            cerebras_model=svc.settings.cerebras_model,
            anthropic_model=svc.settings.anthropic_model,
        )
        if result is None:
            if note == "unknown part":
                raise ApiError("E_UNKNOWN_PART", f"No part {part_id} in build {build_id}.")
            raise ApiError("E_LLM_UNAVAILABLE", f"No model answered: {note}")
        return body(
            {
                "answer": result.answer,
                "follow_ups": result.follow_ups,
                "provider": result.provider,
                "model": result.model,
                "latency_ms": result.latency_ms,
            }
        )

    @api.get("/v1/voice")
    def voice_info() -> JSONResponse:
        """Whether Bara can speak and listen here, and with which voice."""
        return body(voice.settings())

    @api.get("/v1/tts")
    async def tts(request: Request) -> Response:
        """Streams Bara saying `text` (GET, so an <audio> element can play it as it arrives)."""
        text = (request.query_params.get("text") or "").strip()
        if not text:
            raise ApiError("E_BAD_MESSAGE", "Send text.")
        try:
            client, resp = await voice.open_speech(text)
        except RuntimeError as exc:
            raise ApiError("E_LLM_UNAVAILABLE", f"No voice: {exc}") from exc
        return StreamingResponse(
            voice.relay(client, resp),
            media_type="audio/mpeg",
            headers={"cache-control": "no-store"},
        )

    @api.post("/v1/stt")
    async def stt(request: Request) -> JSONResponse:
        """Text of a short recording (raw audio body), for browsers without speech recognition."""
        audio = await request.body()
        if not audio or len(audio) > voice.MAX_STT_BYTES:
            raise ApiError("E_BAD_MESSAGE", "Send up to 8 MB of audio.")
        build_id = request.query_params.get("build_id")
        run = svc.engine.get(build_id) if build_id else None
        terms = (
            sorted({p["card"]["display_name"] for p in (run.state.get("parts") or [])})
            if run
            else None
        )
        try:
            text = await voice.transcribe(audio, request.headers.get("content-type", ""), terms)
        except RuntimeError as exc:
            raise ApiError("E_LLM_UNAVAILABLE", f"No transcription: {exc}") from exc
        return body({"text": text})

    @api.get("/v1/builds/{build_id}/slots/{slot_id}/alternatives")
    def alternatives(build_id: str, slot_id: str, request: Request) -> JSONResponse:
        run = run_or_404(build_id)
        limit = _int_param(request, "limit", 8, 1, 50)
        try:
            result = svc.edits.alternatives(
                run.state, slot_id, request.query_params.get("instance_id"), limit
            )
        except Reject as rej:
            raise ApiError(rej.error["code"], rej.error["message"]) from rej
        return body({"build_id": build_id, **result})

    @api.get("/v1/builds/{build_id}/export")
    def export(build_id: str, request: Request) -> Response:
        run = run_or_404(build_id)
        fmt = request.query_params.get("format")
        if fmt not in EXPORT_FORMATS:
            raise ApiError("E_BAD_MESSAGE", f"format must be one of {sorted(EXPORT_FORMATS)}.")
        if run.terminal != "build.done":
            raise ApiError("E_BUILD_NOT_READY", "Exports open once the build is done.")
        build = run.state
        if fmt in GEOMETRY_FORMATS:
            try:
                data, media = geometry.export(build, fmt)
            except geometry.ExportError as err:
                raise ApiError(err.code, err.message) from err
            suffix = "_kicad" if fmt == "kicad" else ""
            return _download(data, f"{build_id}{suffix}.{GEOMETRY_FORMATS[fmt]}", media)
        if fmt == "bom_csv":
            return _download(bom_csv(build).encode(), f"{build_id}_bom.csv", "text/csv")
        include_all = fmt == "zip"
        if not include_all and not (build.get("firmware") or {}).get("files"):
            raise ApiError("E_ASSET_MISSING", "This build has no firmware files.")
        data = build_zip(svc, build, include_all)
        name = f"{build_id}.zip" if include_all else f"{build_id}_firmware.zip"
        return _download(data, name, "application/zip")

    return api


def _download(data: bytes, filename: str, media_type: str) -> Response:
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def bom_csv(build: dict[str, Any]) -> str:
    return geometry.exports.bom_csv(build)


def _safe_rel(path: str) -> str | None:
    parts = [p for p in path.replace("\\", "/").split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return None
    return "/".join(parts)


def _asset_bytes(svc: Services, url: str | None) -> bytes | None:
    if not url or not url.startswith("/assets/"):
        return None
    # A ?v=<hash> suffix only versions the URL; the file is the path before it.
    rel = _safe_rel(url.split("?", 1)[0].split("#", 1)[0][len("/assets/") :])
    if rel is None:
        return None
    root = svc.settings.assets_dir.resolve()
    path = (root / rel).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return None
    return path.read_bytes()


def build_zip(svc: Services, build: dict[str, Any], include_all: bool) -> bytes:
    buf = io.BytesIO()
    missing: list[str] = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        prefix = "firmware/" if include_all else ""
        firmware = build.get("firmware") or {}
        for entry in firmware.get("files", []):
            rel = _safe_rel(entry.get("path", ""))
            if rel is None:
                continue
            if entry.get("content") is not None:
                zf.writestr(prefix + rel, entry["content"])
                continue
            data = _asset_bytes(svc, (entry.get("asset") or {}).get("url"))
            if data is None:
                missing.append(f"{rel} (asset {(entry.get('asset') or {}).get('url')})")
            else:
                zf.writestr(prefix + rel, data)
        if include_all:
            zf.writestr("bom.csv", bom_csv(build))
            zf.writestr("wiring.csv", geometry.exports.wiring_csv(build))
            zf.writestr("build.json", json.dumps(build, indent=2))
        lines = [f"Bara export of {build['build_id']} (revision {build['revision']})."]
        if missing:
            lines.append("Files not bundled because their asset is not on this server:")
            lines += [f"- {m}" for m in missing]
        zf.writestr("MANIFEST.txt", "\n".join(lines) + "\n")
    return buf.getvalue()
