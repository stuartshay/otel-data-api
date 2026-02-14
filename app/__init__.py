"""FastAPI application factory for otel-data-api."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth import configure_auth
from app.config import Config
from app.database import DatabaseService
from app.middleware import SPAN_ID_HEADER, TRACE_ID_HEADER, TraceCorrelationMiddleware

logger = logging.getLogger(__name__)


def create_app(config: Config) -> FastAPI:
    """Create and configure the FastAPI application."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        # Startup
        db = DatabaseService(config)
        try:
            await db.initialize()
            app.state.db = db
            logger.info("Application started — database pool ready")
        except Exception:
            logger.warning("Database initialization failed — starting without DB")
            app.state.db = db
        yield
        # Shutdown
        await db.close()
        logger.info("Application shutdown — database pool closed")

    app = FastAPI(
        title="OTel Data API",
        description="REST API for OwnTracks/Garmin GPS data with PostGIS spatial queries",
        version=config.app_version,
        lifespan=lifespan,
    )

    # Trace correlation — injects X-Trace-Id / X-Span-Id response headers
    app.add_middleware(TraceCorrelationMiddleware)

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
    from app.routers import garmin, health, locations, reference, spatial, unified

    app.include_router(health.router)
    app.include_router(locations.router)
    app.include_router(garmin.router)
    app.include_router(unified.router)
    app.include_router(reference.router)
    app.include_router(spatial.router)

    return app
