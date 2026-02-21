"""Garmin activity and track point endpoints."""

from __future__ import annotations

from typing import Literal

import fastapi
from fastapi import APIRouter, HTTPException, Query, Request

from app.models import PaginatedResponse
from app.models.garmin import GarminActivity, GarminChartPoint, GarminTrackPoint, SportInfo

router = APIRouter(prefix="/api/v1/garmin", tags=["Garmin"])

ACTIVITY_SORT_WHITELIST = {"start_time", "distance_km", "duration_seconds", "sport", "created_at"}
TRACK_SORT_WHITELIST = {"timestamp", "altitude", "speed_kmh", "heart_rate", "created_at"}


@router.get("/activities", response_model=PaginatedResponse[GarminActivity])
async def list_activities(
    request: Request,
    sport: str | None = Query(None, description="Filter by sport type", examples=["cycling"]),
    date_from: str | None = Query(None, description="Filter from date (YYYY-MM-DD)", examples=["2025-11-01"]),
    date_to: str | None = Query(None, description="Filter to date (YYYY-MM-DD)", examples=["2025-11-30"]),
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    sort: str = Query(
        "start_time",
        description="Sort column (start_time, distance_km, duration_seconds, sport, created_at)",
    ),
    order: Literal["asc", "desc"] = Query("desc"),
) -> PaginatedResponse[GarminActivity]:
    """List Garmin activities with filtering and pagination.

    Returns paginated Garmin cycling/running activities with track point counts.
    Filter by sport type or date range. Sort by start time, distance, duration, etc.
    """
    db = request.app.state.db

    if sort not in ACTIVITY_SORT_WHITELIST:
        sort = "start_time"

    conditions: list[str] = []
    params: list = []
    idx = 1

    if sport:
        conditions.append(f"sport = ${idx}")
        params.append(sport)
        idx += 1

    if date_from:
        conditions.append(f"start_time >= ${idx}::date")
        params.append(date_from)
        idx += 1

    if date_to:
        conditions.append(f"start_time < (${idx}::date + INTERVAL '1 day')")
        params.append(date_to)
        idx += 1

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    total = await db.fetchval(f"SELECT COUNT(*) FROM public.garmin_activities {where}", *params)

    data_query = (
        f"SELECT a.activity_id, a.sport, a.sub_sport, a.start_time, a.end_time, "
        f"a.distance_km, a.duration_seconds, a.avg_heart_rate, a.max_heart_rate, "
        f"a.avg_cadence, a.max_cadence, a.calories, a.avg_speed_kmh, a.max_speed_kmh, "
        f"a.total_ascent_m, a.total_descent_m, a.total_distance, a.avg_pace, "
        f"a.device_manufacturer, a.avg_temperature_c, a.min_temperature_c, "
        f"a.max_temperature_c, a.total_elapsed_time, a.total_timer_time, "
        f"a.created_at, a.uploaded_at, "
        f"(SELECT COUNT(DISTINCT t.timestamp) FROM public.garmin_track_points t "
        f"WHERE t.activity_id = a.activity_id) AS track_point_count "
        f"FROM public.garmin_activities a {where} "
        f"ORDER BY a.{sort} {order} "
        f"LIMIT ${idx} OFFSET ${idx + 1}"
    )
    params.extend([limit, offset])
    rows = await db.fetch(data_query, *params)

    items = [GarminActivity(**dict(row)) for row in rows]
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/sports", response_model=list[SportInfo])
async def list_sports(request: Request) -> list[SportInfo]:
    """List distinct sport types with activity counts."""
    db = request.app.state.db
    rows = await db.fetch(
        "SELECT sport, COUNT(*) AS activity_count FROM public.garmin_activities "
        "GROUP BY sport ORDER BY activity_count DESC"
    )
    return [SportInfo(**dict(row)) for row in rows]


@router.get(
    "/activities/{activity_id}",
    response_model=GarminActivity,
    responses={404: {"description": "Activity not found"}},
)
async def get_activity(
    request: Request,
    activity_id: str = fastapi.Path(description="Garmin activity ID", examples=["20932993811"]),
) -> GarminActivity:
    """Get a single Garmin activity by ID with track point count."""
    db = request.app.state.db
    row = await db.fetchrow(
        "SELECT a.activity_id, a.sport, a.sub_sport, a.start_time, a.end_time, "
        "a.distance_km, a.duration_seconds, a.avg_heart_rate, a.max_heart_rate, "
        "a.avg_cadence, a.max_cadence, a.calories, a.avg_speed_kmh, a.max_speed_kmh, "
        "a.total_ascent_m, a.total_descent_m, a.total_distance, a.avg_pace, "
        "a.device_manufacturer, a.avg_temperature_c, a.min_temperature_c, "
        "a.max_temperature_c, a.total_elapsed_time, a.total_timer_time, "
        "a.created_at, a.uploaded_at, "
        "(SELECT COUNT(DISTINCT t.timestamp) FROM public.garmin_track_points t "
        "WHERE t.activity_id = a.activity_id) AS track_point_count "
        "FROM public.garmin_activities a WHERE a.activity_id = $1",
        activity_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Activity not found")
    return GarminActivity(**dict(row))


@router.get(
    "/activities/{activity_id}/tracks",
    response_model=PaginatedResponse[GarminTrackPoint],
    responses={404: {"description": "Activity not found"}},
)
async def list_track_points(
    request: Request,
    activity_id: str = fastapi.Path(description="Garmin activity ID", examples=["20932993811"]),
    limit: int = Query(500, ge=1, le=25000),
    offset: int = Query(0, ge=0),
    sort: str = Query(
        "timestamp",
        description="Sort column (timestamp, altitude, speed_kmh, heart_rate, created_at)",
    ),
    order: Literal["asc", "desc"] = Query("asc"),
    simplify: float | None = Query(
        None,
        ge=0.000001,
        le=0.01,
        description="Douglas-Peucker simplification tolerance in degrees. "
        "When set, returns the full route simplified via PostGIS ST_Simplify, "
        "ignoring limit/offset. Recommended: 0.00001 (~1m), 0.00005 (~5m).",
    ),
) -> PaginatedResponse[GarminTrackPoint]:
    """List track points for a specific activity.

    Returns GPS track points with altitude, speed, heart rate, and cadence data.
    Use the `simplify` parameter to apply Douglas-Peucker line simplification
    for efficient map rendering of the complete route.
    """
    db = request.app.state.db

    if sort not in TRACK_SORT_WHITELIST:
        sort = "timestamp"

    # Verify activity exists
    exists = await db.fetchval("SELECT 1 FROM public.garmin_activities WHERE activity_id = $1", activity_id)
    if not exists:
        raise HTTPException(status_code=404, detail="Activity not found")

    total = await db.fetchval(
        "SELECT COUNT(DISTINCT timestamp) FROM public.garmin_track_points WHERE activity_id = $1",
        activity_id,
    )

    if simplify is not None:
        rows = await db.fetch(
            "WITH simplified AS ("
            "  SELECT ST_Simplify("
            "    ST_MakeLine(ST_MakePoint(longitude, latitude) ORDER BY timestamp ASC),"
            "    $2"
            "  ) AS geom"
            "  FROM public.garmin_track_points"
            "  WHERE activity_id = $1"
            "), simplified_coords AS ("
            "  SELECT DISTINCT ST_X((dp).geom) AS lng, ST_Y((dp).geom) AS lat"
            "  FROM simplified, LATERAL ST_DumpPoints(geom) AS dp"
            "), matched AS ("
            "  SELECT gtp.id, gtp.activity_id, gtp.latitude, gtp.longitude, "
            "  gtp.timestamp, gtp.altitude, gtp.distance_from_start_km, gtp.speed_kmh, "
            "  gtp.heart_rate, gtp.cadence, gtp.temperature_c, gtp.created_at, "
            "  ROW_NUMBER() OVER ("
            "    PARTITION BY gtp.longitude, gtp.latitude "
            "    ORDER BY gtp.timestamp, (gtp.altitude IS NOT NULL) DESC, gtp.id"
            "  ) AS rn "
            "  FROM public.garmin_track_points gtp "
            "  INNER JOIN simplified_coords sc "
            "    ON gtp.longitude = sc.lng AND gtp.latitude = sc.lat "
            "  WHERE gtp.activity_id = $1"
            ") "
            "SELECT id, activity_id, latitude, longitude, "
            "timestamp, altitude, distance_from_start_km, speed_kmh, "
            "heart_rate, cadence, temperature_c, created_at "
            "FROM matched WHERE rn = 1 "
            f"ORDER BY timestamp {order}",
            activity_id,
            simplify,
        )
        items = [GarminTrackPoint(**dict(row)) for row in rows]
        return PaginatedResponse(items=items, total=total, limit=len(items), offset=0)

    rows = await db.fetch(
        "WITH ranked AS ("
        "  SELECT id, activity_id, latitude, longitude, timestamp, altitude, "
        "  distance_from_start_km, speed_kmh, heart_rate, cadence, temperature_c, "
        "  created_at, "
        "  ROW_NUMBER() OVER ("
        "    PARTITION BY timestamp "
        "    ORDER BY (altitude IS NOT NULL) DESC, id DESC"
        "  ) AS rn "
        "  FROM public.garmin_track_points "
        "  WHERE activity_id = $1"
        ") "
        "SELECT id, activity_id, latitude, longitude, timestamp, altitude, "
        "distance_from_start_km, speed_kmh, heart_rate, cadence, temperature_c, "
        f"created_at FROM ranked WHERE rn = 1 ORDER BY {sort} {order} "
        f"LIMIT $2 OFFSET $3",
        activity_id,
        limit,
        offset,
    )

    items = [GarminTrackPoint(**dict(row)) for row in rows]
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/activities/{activity_id}/chart-data",
    response_model=list[GarminChartPoint],
    responses={404: {"description": "Activity not found"}},
)
async def get_chart_data(
    request: Request,
    activity_id: str = fastapi.Path(description="Garmin activity ID", examples=["20932993811"]),
) -> list[GarminChartPoint]:
    """Return all track points for chart rendering (no pagination).

    Provides the complete time-series data (altitude, speed, heart rate, cadence)
    for an activity, deduplicated by timestamp. Designed for client-side charting
    without pagination limits.
    """
    db = request.app.state.db

    exists = await db.fetchval("SELECT 1 FROM public.garmin_activities WHERE activity_id = $1", activity_id)
    if not exists:
        raise HTTPException(status_code=404, detail="Activity not found")

    rows = await db.fetch(
        "WITH ranked AS ("
        "  SELECT latitude, longitude, timestamp, altitude, "
        "  distance_from_start_km, speed_kmh, heart_rate, cadence, temperature_c, "
        "  ROW_NUMBER() OVER ("
        "    PARTITION BY timestamp "
        "    ORDER BY (altitude IS NOT NULL) DESC, id DESC"
        "  ) AS rn "
        "  FROM public.garmin_track_points "
        "  WHERE activity_id = $1"
        ") "
        "SELECT latitude, longitude, timestamp, altitude, "
        "distance_from_start_km, speed_kmh, heart_rate, cadence, temperature_c "
        "FROM ranked WHERE rn = 1 ORDER BY timestamp ASC",
        activity_id,
    )

    return [GarminChartPoint(**dict(row)) for row in rows]
