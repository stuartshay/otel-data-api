"""Health and readiness endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health(request: Request) -> dict:
    """Liveness probe — returns healthy if the service is running."""
    db = request.app.state.db
    if db and db._pool:
        return {"status": "healthy", "pool_size": db.pool.get_size()}
    return {"status": "healthy"}


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    """Readiness probe — returns ready if the database is reachable."""
    db = request.app.state.db
    result = await db.health_check()
    if result["status"] == "healthy":
        return JSONResponse(content=result)
    return JSONResponse(content=result, status_code=503)
