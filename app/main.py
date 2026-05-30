"""FastAPI application factory.

Wires logging, Sentry, middleware (request-id, metrics, CORS), exception
handlers, and routers. Phase 1 mounts health; later milestones extend
``api_router`` in ``app.api.v1.router``.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router, root_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.i18n import LocaleMiddleware
from app.core.logging import configure_logging, get_logger, request_id_ctx
from app.core.metrics import setup_metrics
from app.core.redis import close_redis
from app.core.sentry import init_sentry

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    configure_logging()
    init_sentry()
    logger.info("Starting African Investment Hub API v%s", settings.APP_VERSION)
    yield
    await close_redis()
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    configure_logging()

    app = FastAPI(
        title="African Investment Hub API",
        version=settings.APP_VERSION,
        description="Backend API for the African Investment Hub platform.",
        # OpenAPI docs disabled in production (PRD §11).
        docs_url="/docs" if settings.ENABLE_DOCS and not settings.is_production else None,
        redoc_url="/redoc" if settings.ENABLE_DOCS and not settings.is_production else None,
        openapi_url="/openapi.json"
        if settings.ENABLE_DOCS and not settings.is_production
        else None,
        lifespan=lifespan,
    )

    # ── Middleware (order matters: last added runs first) ──
    @app.middleware("http")
    async def add_request_id(request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        token = request_id_ctx.set(request_id)
        try:
            response: Response = await call_next(request)
        finally:
            request_id_ctx.reset(token)
        response.headers["X-Request-ID"] = request_id
        return response

    setup_metrics(app)
    app.add_middleware(LocaleMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    register_exception_handlers(app)

    app.include_router(root_router)
    app.include_router(api_router)

    return app


app = create_app()
