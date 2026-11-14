"""CLIPNOVA FastAPI application entrypoint.

Run with:  uvicorn backend.main:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.api.routers import analysis, clips, jobs, system, videos
from backend.core.config import PROJECT_ROOT, get_settings
from backend.core.exceptions import ClipnovaError
from backend.core.logging import setup_logging
from backend.database.session import init_db, init_engine
from backend.workers import handlers  # noqa: F401  (registers job handlers)
from backend.workers.queue import job_manager

log = logging.getLogger("clipnova")
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    s = get_settings()
    s.validate_security()
    s.ensure_dirs()
    setup_logging(s)
    init_engine(s.db_url)
    init_db()
    job_manager.start(s.worker_concurrency)
    log.info("CLIPNOVA %s ready — data dir: %s", s.version, s.data_dir)
    yield
    job_manager.shutdown()
    log.info("CLIPNOVA stopped")


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="CLIPNOVA API", version=s.version, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware, allow_origins=s.cors_origins, allow_methods=["*"], allow_headers=["*"],
    )

    @app.exception_handler(ClipnovaError)
    async def _domain_error(_req: Request, exc: ClipnovaError):
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_req: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={
            "error": "validation_failed", "message": "Invalid request", "details": exc.errors()})

    @app.exception_handler(Exception)
    async def _unhandled(_req: Request, exc: Exception):
        log.exception("Unhandled error: %s", exc)
        return JSONResponse(status_code=500, content={"error": "internal_error", "message": str(exc)})

    app.include_router(system.router)
    app.include_router(videos.router)
    app.include_router(jobs.router)
    app.include_router(analysis.router)
    app.include_router(clips.router)

    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    """Serve the built React app (frontend/dist) with SPA fallback."""
    if not (FRONTEND_DIST / "index.html").exists():
        @app.get("/", include_in_schema=False)
        def _no_frontend():
            return JSONResponse({"message": "Frontend not built. Run ./install.sh or `npm run build` in frontend/."})
        return

    assets = FRONTEND_DIST / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def _spa(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse(status_code=404, content={"error": "not_found", "message": "Unknown API route"})
        candidate = (FRONTEND_DIST / full_path).resolve()
        if full_path and candidate.is_file() and Path(FRONTEND_DIST.resolve()) in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")


app = create_app()
