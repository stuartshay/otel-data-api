"""Health and readiness endpoints."""

from __future__ import annotations

import asyncio
import datetime as dt

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

# Maximum time (seconds) the /ready endpoint waits for the DB health check.
# Must be well below the K8s readinessProbe timeoutSeconds (5s).
_READY_TIMEOUT_S: float = 3.0

router = APIRouter(tags=["Health"])


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


@router.get("/health")
async def health(request: Request) -> dict:
    """Liveness probe — returns healthy if the service is running."""
    return {
        "status": "healthy",
        "version": request.app.version,
        "timestamp": _utc_now().isoformat(),
    }


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    """Readiness probe — returns ready if the database is reachable."""
    try:
        db = request.app.state.db
        db_info = await asyncio.wait_for(db.health_check(), timeout=_READY_TIMEOUT_S)
        return JSONResponse(
            content={
                "status": "ready",
                "database": db_info,
                "version": request.app.version,
                "timestamp": _utc_now().isoformat(),
            }
        )
    except TimeoutError:
        return JSONResponse(
            content={
                "status": "not_ready",
                "error": f"database health check timed out after {_READY_TIMEOUT_S}s",
            },
            status_code=503,
        )
    except Exception as exc:
        return JSONResponse(
            content={"status": "not_ready", "error": str(exc)},
            status_code=503,
        )
