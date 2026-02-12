"""Unified GPS view and daily activity summary endpoints."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query, Request

from app.models import PaginatedResponse
from app.models.spatial import DailyActivitySummary, UnifiedGpsPoint

router = APIRouter(prefix="/api/v1/gps", tags=["Unified GPS"])


@router.get("/unified", response_model=PaginatedResponse[UnifiedGpsPoint])
async def list_unified_gps(
    request: Request,
    source: str | None = Query(None, description="Filter by source: owntracks or garmin"),
    date_from: str | None = Query(None, description="Filter from date (YYYY-MM-DD)"),
    date_to: str | None = Query(None, description="Filter to date (YYYY-MM-DD)"),
    limit: int = Query(100, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    order: Literal["asc", "desc"] = Query("desc"),
) -> PaginatedResponse[UnifiedGpsPoint]:
    """Query the unified_gps_points view combining OwnTracks + Garmin data."""
    db = request.app.state.db

    conditions: list[str] = []
    params: list = []
    idx = 1

    if source:
        conditions.append(f"source = ${idx}")
        params.append(source)
        idx += 1

    if date_from:
        conditions.append(f"timestamp >= ${idx}::date")
        params.append(date_from)
        idx += 1

    if date_to:
        conditions.append(f"timestamp < (${idx}::date + INTERVAL '1 day')")
        params.append(date_to)
        idx += 1

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    total = await db.fetchval(f"SELECT COUNT(*) FROM unified_gps_points {where}", *params)

    rows = await db.fetch(
        f"SELECT source, identifier, latitude, longitude, timestamp, "
        f"accuracy, battery, speed_kmh, heart_rate, created_at "
        f"FROM unified_gps_points {where} "
        f"ORDER BY timestamp {order} "
        f"LIMIT ${idx} OFFSET ${idx + 1}",
        *params,
        limit,
        offset,
    )

    items = [UnifiedGpsPoint(**dict(row)) for row in rows]
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/daily-summary", response_model=list[DailyActivitySummary])
async def daily_summary(
    request: Request,
    date_from: str | None = Query(None, description="Filter from date (YYYY-MM-DD)"),
    date_to: str | None = Query(None, description="Filter to date (YYYY-MM-DD)"),
    limit: int = Query(30, ge=1, le=365),
) -> list[DailyActivitySummary]:
    """Query the daily_activity_summary view for aggregated daily stats."""
    db = request.app.state.db

    conditions: list[str] = []
    params: list = []
    idx = 1

    if date_from:
        conditions.append(f"activity_date >= ${idx}::date")
        params.append(date_from)
        idx += 1

    if date_to:
        conditions.append(f"activity_date <= ${idx}::date")
        params.append(date_to)
        idx += 1

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    rows = await db.fetch(
        f"SELECT activity_date::text AS activity_date, owntracks_device, "
        f"owntracks_points, min_battery, max_battery, avg_accuracy, "
        f"garmin_sport, garmin_activities, total_distance_km, "
        f"total_duration_seconds, avg_heart_rate, total_calories "
        f"FROM daily_activity_summary {where} "
        f"ORDER BY activity_date DESC LIMIT ${idx}",
        *params,
        limit,
    )

    return [DailyActivitySummary(**dict(row)) for row in rows]
