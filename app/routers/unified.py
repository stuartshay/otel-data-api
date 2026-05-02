"""Unified GPS view and daily activity summary endpoints."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from app.models import PaginatedResponse
from app.models.spatial import DailyActivitySummary, DailySummaryDateRange, UnifiedGpsPoint

router = APIRouter(prefix="/api/v1/gps", tags=["Unified GPS"])

# Default lookback period when no date filters are provided.
# Prevents full-table scans on the 4M+ row unified view.
_DEFAULT_LOOKBACK_DAYS = 90


def _parse_date(value: str) -> date:
    """Parse a YYYY-MM-DD string to a datetime.date object for asyncpg."""
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid date format: {value!r}. Expected YYYY-MM-DD.") from None


@router.get("/unified", response_model=PaginatedResponse[UnifiedGpsPoint])
async def list_unified_gps(
    request: Request,
    source: str | None = Query(None, description="Filter by source: owntracks or garmin", examples=["owntracks"]),
    date_from: str | None = Query(
        None,
        description="Filter from date (YYYY-MM-DD). Defaults to 90 days ago when both date_from and date_to are omitted.",
        examples=["2026-02-01"],
    ),
    date_to: str | None = Query(None, description="Filter to date (YYYY-MM-DD)", examples=["2026-02-12"]),
    limit: int = Query(100, ge=1, le=5000, description="Maximum number of GPS points to return per page"),
    offset: int = Query(0, ge=0, description="Number of GPS points to skip for pagination"),
    order: Literal["asc", "desc"] = Query(
        "desc", description="Sort direction: asc (oldest first) or desc (newest first)"
    ),
    exclude_stationary: bool = Query(False, description="Exclude stationary points where speed_kmh = 0"),
    deduplicate: bool = Query(
        False,
        description="Remove points with duplicate coordinates (rounded to ~11m precision)",
    ),
) -> PaginatedResponse[UnifiedGpsPoint]:
    """Query the unified_gps_points view combining OwnTracks + Garmin data.

    Merges OwnTracks location data and Garmin track points into a single
    chronological stream. Filter by data source or date range.

    When no date filters are specified (both date_from and date_to omitted),
    defaults to the last 90 days to avoid expensive full-table scans on the
    underlying 4M+ row tables.
    """
    db = request.app.state.db

    parsed_from = _parse_date(date_from) if date_from else None
    parsed_to = _parse_date(date_to) if date_to else None

    if parsed_from is None and parsed_to is None:
        parsed_from = date.today() - timedelta(days=_DEFAULT_LOOKBACK_DAYS)

    conditions: list[str] = []
    params: list = []
    idx = 1

    if source:
        conditions.append(f"source = ${idx}")
        params.append(source)
        idx += 1

    if parsed_from:
        conditions.append(f"timestamp >= ${idx}::date")
        params.append(parsed_from)
        idx += 1

    if parsed_to:
        conditions.append(f"timestamp < (${idx}::date + INTERVAL '1 day')")
        params.append(parsed_to)
        idx += 1

    if exclude_stationary:
        conditions.append("(speed_kmh > 0 OR speed_kmh IS NULL)")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    # When deduplicating, use a subquery with DISTINCT ON rounded coordinates.
    # Rounding to 4 decimal places gives ~11m precision.
    if deduplicate:
        inner_table = (
            f"(SELECT DISTINCT ON (ROUND(latitude::numeric, 4), ROUND(longitude::numeric, 4)) "
            f"source, identifier, latitude, longitude, timestamp, "
            f"accuracy, battery, speed_kmh, heart_rate, created_at "
            f"FROM unified_gps_points {where} "
            f"ORDER BY ROUND(latitude::numeric, 4), ROUND(longitude::numeric, 4), timestamp {order}"
            f") AS deduped"
        )

        total = await db.fetchval(f"SELECT COUNT(*) FROM {inner_table}", *params)

        rows = await db.fetch(
            f"SELECT source, identifier, latitude, longitude, timestamp, "
            f"accuracy, battery, speed_kmh, heart_rate, created_at "
            f"FROM {inner_table} "
            f"ORDER BY timestamp {order} "
            f"LIMIT ${idx} OFFSET ${idx + 1}",
            *params,
            limit,
            offset,
        )
    else:
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


@router.get("/daily-summary", response_model=PaginatedResponse[DailyActivitySummary])
async def daily_summary(
    request: Request,
    date_from: str | None = Query(
        None,
        description="Filter from date (YYYY-MM-DD). Defaults to 90 days ago when both date_from and date_to are omitted.",
        examples=["2026-02-01"],
    ),
    date_to: str | None = Query(None, description="Filter to date (YYYY-MM-DD)", examples=["2026-02-12"]),
    limit: int = Query(30, ge=1, le=365, description="Maximum number of daily summaries to return per page"),
    offset: int = Query(0, ge=0, description="Number of daily summaries to skip for pagination"),
) -> PaginatedResponse[DailyActivitySummary]:
    """Query the daily_activity_summary view for aggregated daily stats.

    Returns per-day aggregates including OwnTracks point counts, battery stats,
    and Garmin activity metrics (distance, duration, heart rate, calories).

    When no date filters are specified (both date_from and date_to omitted),
    defaults to the last 90 days to avoid expensive full-table aggregations.
    """
    db = request.app.state.db

    parsed_from = _parse_date(date_from) if date_from else None
    parsed_to = _parse_date(date_to) if date_to else None

    if parsed_from is None and parsed_to is None:
        parsed_from = date.today() - timedelta(days=_DEFAULT_LOOKBACK_DAYS)

    conditions: list[str] = []
    params: list = []
    idx = 1

    if parsed_from:
        conditions.append(f"activity_date >= ${idx}::date")
        params.append(parsed_from)
        idx += 1

    if parsed_to:
        conditions.append(f"activity_date <= ${idx}::date")
        params.append(parsed_to)
        idx += 1

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    total = await db.fetchval(f"SELECT COUNT(*) FROM daily_activity_summary {where}", *params)

    rows = await db.fetch(
        f"SELECT activity_date::text AS activity_date, owntracks_device, "
        f"owntracks_points, min_battery, max_battery, avg_accuracy, "
        f"garmin_sport, garmin_activities, total_distance_km, "
        f"total_duration_seconds, avg_heart_rate, total_calories "
        f"FROM daily_activity_summary {where} "
        f"ORDER BY activity_date DESC LIMIT ${idx} OFFSET ${idx + 1}",
        *params,
        limit,
        offset,
    )

    items = [DailyActivitySummary(**dict(row)) for row in rows]
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/daily-summary/date-range", response_model=DailySummaryDateRange)
async def daily_summary_date_range(request: Request) -> DailySummaryDateRange:
    """Get the earliest and latest activity dates available in the daily summary view."""
    db = request.app.state.db
    row = await db.fetchrow(
        "SELECT MIN(activity_date) AS min_date, MAX(activity_date) AS max_date FROM daily_activity_summary"
    )
    if not row or row["min_date"] is None:
        raise HTTPException(status_code=404, detail="No daily summary data found")
    return DailySummaryDateRange(min_date=row["min_date"], max_date=row["max_date"])
