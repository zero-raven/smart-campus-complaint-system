"""FastAPI application factory.

Wires configuration, logging, the two database clients, the API routers and
Jinja2 template rendering. Kept free of business logic so it can be imported
by both the uvicorn entrypoint and the pytest fixtures.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from backend.core.config import PROJECT_ROOT, get_settings
from backend.core.logging import configure_logging, get_logger
from backend.services.outbox_relay import start_relay, stop_relay

logger = get_logger(__name__)

TEMPLATES_DIR = PROJECT_ROOT / "backend" / "templates"
STATIC_DIR = PROJECT_ROOT / "backend" / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown hooks: ensure MongoDB indexes, stop background tasks."""
    configure_logging()
    settings = get_settings()

    from backend.core.database import check_postgres
    from backend.core.mongo import check_mongo, ensure_indexes

    pg_ok = check_postgres()
    mongo_ok = check_mongo()
    logger.info("Startup: PostgreSQL=%s MongoDB=%s", pg_ok, mongo_ok)

    if mongo_ok:
        try:
            ensure_indexes()
        except Exception as exc:  # pragma: no cover
            logger.error("Failed to ensure MongoDB indexes: %s", exc)

    if not pg_ok:
        logger.error(
            "PostgreSQL is unreachable. Run scripts/bootstrap.sh before starting."
        )

    # Start the background outbox relay. Without it, events are only published
    # by the inline best-effort call at the end of each request, so any event
    # written while MongoDB was down would sit unpublished indefinitely. The
    # relay is what makes the outbox eventually consistent rather than merely
    # retry-once.
    if pg_ok and mongo_ok:
        try:
            start_relay()
        except Exception as exc:  # pragma: no cover
            logger.error("Failed to start outbox relay: %s", exc)

    yield

    stop_relay()
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description=(
            "Web-based campus complaint management with NLP-assisted triage and a "
            "hybrid PostgreSQL + MongoDB persistence layer."
        ),
        lifespan=lifespan,
    )

    # --- Templates and static files ---
    if TEMPLATES_DIR.exists():
        app.state.templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
        app.state.templates.env.globals["app_name"] = settings.app_name

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # --- API routers (imported here so models register before route wiring) ---
    from backend.api.v1 import router as api_router

    app.include_router(api_router, prefix="/api/v1")

    # --- Health check ---
    from backend.api.v1.health import router as health_router

    app.include_router(health_router)

    # --- HTML pages ---
    if TEMPLATES_DIR.exists():
        from backend.api.pages import router as pages_router

        app.include_router(pages_router)

        @app.get("/", response_class=HTMLResponse, include_in_schema=False)
        def index(request: Request):
            return request.app.state.templates.TemplateResponse(
                request=request,
                name="index.html",
                context={"app_name": settings.app_name},
            )

    return app


app = create_app()
