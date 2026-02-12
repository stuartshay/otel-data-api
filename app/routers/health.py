"""Health and readiness endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health(request: Request) -> dict:
    """Liveness probe — returns healthy if the service is running."""
    return {
        "status": "healthy",
        "version": request.app.version,
        "timestamp": datetime.now(UTC).isoformat(),
    }


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    """Readiness probe — returns ready if the database is reachable."""
    try:
        db = request.app.state.db
        db_info = await db.health_check()
        return JSONResponse(
            content={
                "status": "ready",
                "database": db_info,
                "version": request.app.version,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
    except Exception as exc:
        return JSONResponse(
            content={"status": "not_ready", "error": str(exc)},
            status_code=503,
        )
