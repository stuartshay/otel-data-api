"""FastAPI application factory for otel-data-api."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth import configure_auth
from app.config import Config
from app.database import DatabaseService
from app.middleware import SPAN_ID_HEADER, TRACE_ID_HEADER, RequestLoggingMiddleware
from app.tracing import setup_tracing

logger = structlog.get_logger(__name__)


def create_app(config: Config) -> FastAPI:
    """Create and configure the FastAPI application."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        # Startup
        db = DatabaseService(config)
        try:
            await db.initialize()
            app.state.db = db
            logger.info("Application started — database pool ready")
        except Exception:
            logger.warning(
                "Database initialization failed \u2014 starting without DB",
                exc_info=True,
            )
            app.state.db = db
        yield
        # Shutdown
        await db.close()
        logger.info("Application shutdown — database pool closed")
        # Flush remaining OTel spans before exit
        tracer_provider = getattr(app.state, "tracer_provider", None)
        if tracer_provider is not None:
            tracer_provider.shutdown()
        log_provider = getattr(app.state, "log_provider", None)
        if log_provider is not None:
            log_provider.shutdown()

    app = FastAPI(
        title="OTel Data API",
        description="REST API for OwnTracks/Garmin GPS data with PostGIS spatial queries",
        version=config.app_version,
        lifespan=lifespan,
    )
    app.state.config = config

    # Request logging + trace correlation
    app.add_middleware(RequestLoggingMiddleware, config=config)

    # CORS
    if config.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(config.cors_origins),
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=[TRACE_ID_HEADER, SPAN_ID_HEADER],
        )

    # Auth
    configure_auth(config.cognito_issuer, config.cognito_client_id, config.oauth2_enabled)

    # Register routers
    from app.routers import garmin, geocoding, health, locations, reference, spatial, unified

    app.include_router(health.router)
    app.include_router(locations.router)
    app.include_router(garmin.router)
    app.include_router(unified.router)
    app.include_router(reference.router)
    app.include_router(spatial.router)
    app.include_router(geocoding.router)
    if config.internal_endpoints_enabled:
        app.include_router(geocoding.internal_router)

    # OpenTelemetry auto-instrumentation (opt-in via OTEL_TRACES_ENABLED)
    app.state.tracer_provider = setup_tracing(app, config)

    return app
