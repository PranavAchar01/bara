"""FastAPI app factory and the bara-server entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request, WebSocket
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from bara.access import AccessTokenMiddleware
from bara.config import Settings, load_dotenv, load_settings
from bara.rest import ApiError, build_router, error_response
from bara.services import build_services
from bara.ws import WsHandler

log = logging.getLogger(__name__)

CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
# The Vercel deploys (production and previews) and the self-hosted site on its own quick tunnel
# reach a local server through a tunnel. The engine is already open to anyone with its link, so
# letting a quick-tunnel page read it exposes nothing new.
CORS_ORIGIN_REGEX = r"https://(bara(-[a-z0-9-]+)?\.vercel\.app|[a-z0-9-]+\.trycloudflare\.com)"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    svc = build_services(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        await svc.engine.shutdown()

    app = FastAPI(title="Bara", version="0.1.0", lifespan=lifespan)
    app.state.services = svc
    if settings.access_token:
        # Added before CORS so CORS stays outermost and a 401 still carries CORS headers.
        app.add_middleware(AccessTokenMiddleware, token=settings.access_token)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_origin_regex=CORS_ORIGIN_REGEX,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, exc: ApiError):
        return error_response(exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation(_request: Request, exc: RequestValidationError):
        return error_response("E_BAD_MESSAGE", f"Bad request: {exc.errors()[:1]}")

    @app.exception_handler(StarletteHTTPException)
    async def _http(_request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404:
            return error_response("E_NOT_FOUND", "Not found.")
        if exc.status_code == 405:
            return error_response("E_BAD_MESSAGE", "Method not allowed.")
        return error_response("E_INTERNAL", str(exc.detail))

    app.include_router(build_router(svc))
    handler = WsHandler(svc)

    @app.websocket("/v1/ws")
    async def ws(websocket: WebSocket) -> None:
        await handler.serve(websocket)

    settings.assets_dir.mkdir(parents=True, exist_ok=True)

    @app.get("/assets/parts/kicad_gen/{stem}.glb")
    def kicad_generated_glb(stem: str) -> FileResponse:
        """Generated-tier GLBs are converted on first request, then served from the cache."""
        from bara.kicad_generated import KicadIndex, glb_stem

        index = KicadIndex.open(settings.catalog_dir / "kicad_index.sqlite")
        if index is None:
            raise StarletteHTTPException(404)
        glb = index.glb_dir / f"{stem}.glb"
        if not glb.is_file():
            rows = index.rows("SELECT part_id FROM kicad_parts WHERE kind = 'footprint'")
            match = next((r[0] for r in rows if glb_stem(r[0]) == stem), None)
            if match is None or index.ensure_glb(match) is None:
                raise StarletteHTTPException(404)
        return FileResponse(glb, media_type="model/gltf-binary")

    app.mount("/assets", StaticFiles(directory=settings.assets_dir), name="assets")
    return app


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = load_settings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
