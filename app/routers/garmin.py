"""Garmin activity and track point endpoints."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import date
from typing import Annotated, Any, Literal

import fastapi
import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import ValidationError

from app.auth import require_auth
from app.models import PaginatedResponse
from app.models.garmin import (
    GarminActivity,
    GarminActivityClimb,
    GarminActivityLap,
    GarminActivityLapsGroup,
    GarminActivityManualUpdate,
    GarminActivityTotal,
    GarminChartPoint,
    GarminDateRange,
    GarminDeviceCount,
    GarminLapsActivity,
    GarminSegment,
    GarminSegmentCreate,
    GarminSyncResponse,
    GarminTrackPoint,
    SegmentDefinition,
    SegmentEffort,
    SegmentEffortsResponse,
    SportInfo,
)
from app.models.geocoding import GarminActivityAddress, GeocodedAddressSummary

router = APIRouter(prefix="/api/v1/garmin", tags=["Garmin"])

# Shared string constants (avoid duplicating the same literal across handlers).
DESC_ACTIVITY_ID = "Garmin activity ID"
DESC_FILTER_BY_SPORT = "Filter by sport type"
DESC_SAVED_SEGMENT_ID = "Saved segment ID"
ACTIVITY_NOT_FOUND = "Activity not found"
SEGMENT_NOT_FOUND = "Segment not found"
INVALID_SYNC_RESPONSE = "Invalid response from Garmin sync service"

# Auth-protected endpoints raise these via require_auth -> get_current_user().
AUTH_RESPONSES: dict = {
    401: {"description": "Authentication required or token invalid"},
    503: {"description": "Authentication service unavailable"},
}
SQL_ACTIVITY_EXISTS = "SELECT 1 FROM public.garmin_activities WHERE activity_id = $1"
logger = structlog.get_logger(__name__)

ACTIVITY_SORT_WHITELIST = {"start_time", "distance_km", "duration_seconds", "sport", "created_at"}
TRACK_SORT_WHITELIST = {"timestamp", "altitude", "speed_kmh", "heart_rate", "created_at"}

ACTIVITY_BY_ID_SELECT = (
    "SELECT a.activity_id, a.sport, a.sub_sport, a.start_time, a.end_time, "
    "a.distance_km, a.duration_seconds, a.avg_heart_rate, a.max_heart_rate, "
    "(a.avg_heart_rate IS NOT NULL OR a.max_heart_rate IS NOT NULL OR EXISTS ("
    "SELECT 1 FROM public.garmin_track_points t_hr "
    "WHERE t_hr.activity_id = a.activity_id AND t_hr.heart_rate IS NOT NULL"
    ")) AS hr_available, "
    "a.min_heart_rate, a.aerobic_training_effect, a.anaerobic_training_effect, "
    "a.exercise_load, a.avg_respiration_rate, a.min_respiration_rate, "
    "a.max_respiration_rate, a.sweat_loss_ml, a.moderate_intensity_minutes, "
    "a.vigorous_intensity_minutes, a.total_intensity_minutes, "
    "a.paved_distance_km, a.unpaved_distance_km, a.avg_cadence, a.max_cadence, a.total_strokes, "
    "a.calories, a.avg_speed_kmh, a.max_speed_kmh, a.total_ascent_m, "
    "a.total_descent_m, a.total_distance, a.avg_pace, a.device_manufacturer, "
    "a.avg_temperature_c, a.min_temperature_c, a.max_temperature_c, "
    "a.total_elapsed_time, a.total_timer_time, a.created_at, a.uploaded_at, "
    "a.device_id, d.manufacturer AS dev_manufacturer, "
    "d.garmin_product AS dev_garmin_product, d.model AS dev_model, "
    "d.software_version AS dev_software_version, "
    "(SELECT COUNT(*) FROM public.garmin_track_points t "
    "WHERE t.activity_id = a.activity_id) AS track_point_count "
    "FROM public.garmin_activities a "
    "LEFT JOIN public.garmin_devices d ON d.device_id = a.device_id "
    "WHERE a.activity_id = $1"
)


def _coerce_sync_payload(payload: dict) -> GarminSyncResponse:
    """Normalize proxied sync payloads."""
    if not isinstance(payload, dict):
        raise ValueError("Sync payload must be an object")

    payload.setdefault("status", "error")
    payload.setdefault("message", "Unexpected response from Garmin sync service")
    return GarminSyncResponse(**payload)


def _build_sync_params(
    lookback: int | None,
    window_hours: int | None,
    resync_existing: bool | None,
    activity_id: list[str] | None,
    activity_ids: list[str] | None,
) -> dict[str, Any]:
    """Build the query params forwarded to the in-cluster garmin-sync service."""
    params: dict[str, Any] = {}
    if lookback is not None:
        params["lookback"] = lookback
    if window_hours is not None:
        params["window_hours"] = window_hours
    if resync_existing is not None:
        params["resync_existing"] = "true" if resync_existing else "false"
    if activity_id:
        params["activity_id"] = activity_id
    if activity_ids:
        params["activity_ids"] = activity_ids
    return params


@router.post(
    "/sync",
    status_code=202,
    responses={
        400: {"model": GarminSyncResponse, "description": "Invalid sync trigger parameters"},
        409: {"model": GarminSyncResponse, "description": "Sync already in progress"},
        502: {"model": GarminSyncResponse, "description": "Bad gateway from Garmin sync service"},
        503: {"model": GarminSyncResponse, "description": "Garmin sync service unavailable"},
        504: {"model": GarminSyncResponse, "description": "Garmin sync service timeout"},
    },
)
async def trigger_sync(
    request: Request,
    response: Response,
    lookback: Annotated[
        int | None,
        Query(ge=0, description="Optional activity lookback override. Non-negative integer."),
    ] = None,
    window_hours: Annotated[
        int | None,
        Query(ge=1, description="Optional sync window in hours. Positive integer."),
    ] = None,
    resync_existing: Annotated[
        bool | None,
        Query(description="Whether to re-sync activities that already exist in the database."),
    ] = None,
    activity_id: Annotated[
        list[str] | None,
        Query(description="Optional Garmin activity_id filter (repeatable)."),
    ] = None,
    activity_ids: Annotated[
        list[str] | None,
        Query(description="Optional Garmin activity_ids filter (repeatable)."),
    ] = None,
) -> GarminSyncResponse:
    """Trigger an on-demand Garmin sync via the in-cluster garmin-sync service."""
    sync_id = request.headers.get("X-Garmin-Sync-Id") or str(uuid.uuid4())
    structlog.contextvars.bind_contextvars(**{"garmin.sync_id": sync_id, "garmin.flow": True})

    if lookback is not None and window_hours is not None:
        response.status_code = 400
        return GarminSyncResponse(
            status="bad_request",
            message="lookback and window_hours cannot be combined",
        )

    config = request.app.state.config
    base_url = config.garmin_sync_base_url.rstrip("/")
    params = _build_sync_params(
        lookback=lookback,
        window_hours=window_hours,
        resync_existing=resync_existing,
        activity_id=activity_id,
        activity_ids=activity_ids,
    )

    logger.info("garmin_sync_trigger", sync_id=sync_id, params=params)

    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=config.garmin_sync_timeout_seconds) as client:
            upstream_response = await client.post(
                "/api/v1/sync",
                params=params,
                headers={"X-Garmin-Sync-Id": sync_id},
            )
    except httpx.TimeoutException:
        response.status_code = 504
        return GarminSyncResponse(status="error", message="Garmin sync service timed out")
    except httpx.HTTPError:
        response.status_code = 503
        return GarminSyncResponse(status="error", message="Garmin sync service unavailable")

    try:
        payload = upstream_response.json()
    except ValueError:
        response.status_code = 502
        return GarminSyncResponse(status="error", message=INVALID_SYNC_RESPONSE)

    if upstream_response.status_code in {202, 409, 400}:
        try:
            sync_response = _coerce_sync_payload(payload)
        except ValidationError:
            response.status_code = 502
            return GarminSyncResponse(status="error", message=INVALID_SYNC_RESPONSE)
        except ValueError:
            response.status_code = 502
            return GarminSyncResponse(status="error", message=INVALID_SYNC_RESPONSE)
        response.status_code = upstream_response.status_code
        return sync_response
    if upstream_response.status_code >= 500:
        response.status_code = 502
        return GarminSyncResponse(status="error", message="Garmin sync service error")

    response.status_code = 502
    return GarminSyncResponse(
        status="error",
        message=f"Unexpected response from Garmin sync service: {upstream_response.status_code}",
    )


@router.get(
    "/date-range",
    responses={404: {"description": "No Garmin activity data found"}},
)
async def garmin_date_range(request: Request) -> GarminDateRange:
    """Get the earliest and latest Garmin activity timestamps."""
    db = request.app.state.db
    row = await db.fetchrow(
        "SELECT MIN(start_time) AS min_date, MAX(start_time) AS max_date FROM public.garmin_activities"
    )
    if not row or row["min_date"] is None:
        raise HTTPException(status_code=404, detail="No Garmin activity data found")
    return GarminDateRange(min_date=row["min_date"], max_date=row["max_date"])


@router.get(
    "/activities",
    responses={422: {"description": "Invalid date format"}},
)
async def list_activities(
    request: Request,
    sport: Annotated[str | None, Query(description=DESC_FILTER_BY_SPORT, examples=["cycling"])] = None,
    date_from: Annotated[
        date | None,
        Query(description="Filter from date (YYYY-MM-DD)", examples=["2025-11-01"]),
    ] = None,
    date_to: Annotated[
        date | None,
        Query(description="Filter to date (YYYY-MM-DD)", examples=["2025-11-30"]),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=1000, description="Maximum number of activities to return per page")] = 50,
    offset: Annotated[int, Query(ge=0, description="Number of activities to skip for pagination")] = 0,
    sort: Annotated[
        str,
        Query(description="Sort column (start_time, distance_km, duration_seconds, sport, created_at)"),
    ] = "start_time",
    order: Annotated[
        Literal["asc", "desc"],
        Query(description="Sort direction: asc (oldest first) or desc (newest first)"),
    ] = "desc",
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
        f"(a.avg_heart_rate IS NOT NULL OR a.max_heart_rate IS NOT NULL OR EXISTS ("
        f"SELECT 1 FROM public.garmin_track_points t_hr "
        f"WHERE t_hr.activity_id = a.activity_id AND t_hr.heart_rate IS NOT NULL"
        f")) AS hr_available, "
        f"a.avg_cadence, a.max_cadence, a.total_strokes, a.calories, a.avg_speed_kmh, a.max_speed_kmh, "
        f"a.total_ascent_m, a.total_descent_m, a.total_distance, a.avg_pace, "
        f"a.device_manufacturer, a.avg_temperature_c, a.min_temperature_c, "
        f"a.max_temperature_c, a.total_elapsed_time, a.total_timer_time, "
        f"a.created_at, a.uploaded_at, "
        f"a.device_id, d.manufacturer AS dev_manufacturer, "
        f"d.garmin_product AS dev_garmin_product, d.model AS dev_model, "
        f"d.software_version AS dev_software_version, "
        f"(SELECT COUNT(*) FROM public.garmin_track_points t "
        f"WHERE t.activity_id = a.activity_id) AS track_point_count "
        f"FROM public.garmin_activities a "
        f"LEFT JOIN public.garmin_devices d ON d.device_id = a.device_id {where} "
        f"ORDER BY a.{sort} {order} "
        f"LIMIT ${idx} OFFSET ${idx + 1}"
    )
    params.extend([limit, offset])
    rows = await db.fetch(data_query, *params)

    items = [GarminActivity.from_row(row) for row in rows]
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/sports")
async def list_sports(request: Request) -> list[SportInfo]:
    """List distinct sport types with activity counts."""
    db = request.app.state.db
    rows = await db.fetch(
        "SELECT sport, COUNT(*) AS activity_count FROM public.garmin_activities "
        "GROUP BY sport ORDER BY activity_count DESC"
    )
    return [SportInfo(**dict(row)) for row in rows]


@router.get("/device-counts")
async def list_device_counts(request: Request) -> list[GarminDeviceCount]:
    """List Garmin recording device labels with activity counts.

    Activities without recording-device metadata are grouped under ``Manual``.
    Firmware/software version is intentionally excluded from this aggregate.
    """
    db = request.app.state.db
    rows = await db.fetch(
        "SELECT COALESCE(NULLIF(TRIM(d.model), ''), 'Manual') AS label, "
        "COUNT(*) AS activity_count "
        "FROM public.garmin_activities a "
        "LEFT JOIN public.garmin_devices d ON d.device_id = a.device_id "
        "GROUP BY COALESCE(NULLIF(TRIM(d.model), ''), 'Manual') "
        "ORDER BY (COALESCE(NULLIF(TRIM(d.model), ''), 'Manual') = 'Manual') ASC, "
        "activity_count DESC, label ASC"
    )
    return [GarminDeviceCount(**dict(row)) for row in rows]


@router.get(
    "/activity-totals",
    responses={422: {"description": "Invalid query parameter"}},
)
async def list_activity_totals(
    request: Request,
    period: Annotated[
        Literal["week", "month", "year"],
        Query(description="Time bucket for aggregation: week, month, or year"),
    ],
    sport: Annotated[str | None, Query(description="Filter to a single sport (e.g. cycling)")] = None,
    date_from: Annotated[
        date | None,
        Query(description="Inclusive lower bound on start_time (YYYY-MM-DD, UTC)"),
    ] = None,
    date_to: Annotated[
        date | None,
        Query(description="Inclusive upper bound on start_time (YYYY-MM-DD, UTC)"),
    ] = None,
) -> list[GarminActivityTotal]:
    """Aggregate Garmin activities into period totals (week / month / year).

    Buckets are computed via ``DATE_TRUNC(period, start_time)`` and ordered by
    ``period_start`` ascending. Each row contains activity count plus sum of
    distance, duration, ascent, and calories. Empty result returns ``[]``.
    """
    db = request.app.state.db

    # Period is the first positional parameter so the entire query stays
    # parameterized (no string interpolation of user-controlled values into SQL).
    params: list = [period]
    conditions: list[str] = []
    idx = 2

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

    query = (
        "SELECT DATE_TRUNC($1::text, start_time)::date AS period_start, "
        "COUNT(*) AS activity_count, "
        "SUM(distance_km) AS total_distance_km, "
        "SUM(duration_seconds) AS total_duration_seconds, "
        "SUM(total_ascent_m) AS total_ascent_m, "
        "SUM(calories) AS total_calories "
        f"FROM public.garmin_activities {where} "
        "GROUP BY period_start ORDER BY period_start ASC"
    )

    rows = await db.fetch(query, *params)
    return [GarminActivityTotal(**dict(row)) for row in rows]


@router.get(
    "/activities/{activity_id}",
    responses={404: {"description": ACTIVITY_NOT_FOUND}},
)
async def get_activity(
    request: Request,
    activity_id: Annotated[str, fastapi.Path(description=DESC_ACTIVITY_ID, examples=["20932993811"])],
) -> GarminActivity:
    """Get a single Garmin activity by ID with track point count."""
    db = request.app.state.db
    row = await db.fetchrow(ACTIVITY_BY_ID_SELECT, activity_id)
    if not row:
        raise HTTPException(status_code=404, detail=ACTIVITY_NOT_FOUND)
    activity = GarminActivity.from_row(row)
    if request.app.state.config.log_garmin_activity_detail:
        logger.info(
            "garmin.activity.detail",
            garmin_activity_id=activity_id,
            response=activity.model_dump(mode="json"),
        )
    return activity


@router.patch(
    "/activities/{activity_id}",
    responses={
        **AUTH_RESPONSES,
        400: {"description": "No fields to update"},
        404: {"description": ACTIVITY_NOT_FOUND},
    },
)
async def patch_activity(
    request: Request,
    body: Annotated[GarminActivityManualUpdate, fastapi.Body()],
    activity_id: Annotated[str, fastapi.Path(description=DESC_ACTIVITY_ID, examples=["20932993811"])],
    _user: Annotated[dict, Depends(require_auth)],
) -> GarminActivity:
    """Manually patch Garmin activity fields (auth required when OAuth2 is enabled)."""
    db = request.app.state.db

    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    set_parts: list[str] = []
    params: list[Any] = []
    idx = 1
    for field_name, value in updates.items():
        set_parts.append(f"{field_name} = ${idx}")
        params.append(value)
        idx += 1

    params.append(activity_id)
    updated = await db.fetchrow(
        f"UPDATE public.garmin_activities SET {', '.join(set_parts)} WHERE activity_id = ${idx} RETURNING activity_id",
        *params,
    )
    if not updated:
        raise HTTPException(status_code=404, detail=ACTIVITY_NOT_FOUND)

    row = await db.fetchrow(ACTIVITY_BY_ID_SELECT, activity_id)
    if not row:
        raise HTTPException(status_code=404, detail=ACTIVITY_NOT_FOUND)
    return GarminActivity.from_row(row)


@router.get(
    "/activities/{activity_id}/tracks",
    responses={404: {"description": ACTIVITY_NOT_FOUND}},
)
async def list_track_points(
    request: Request,
    activity_id: Annotated[str, fastapi.Path(description=DESC_ACTIVITY_ID, examples=["20932993811"])],
    limit: Annotated[int, Query(ge=1, le=25000, description="Maximum number of track points to return per page")] = 500,
    offset: Annotated[int, Query(ge=0, description="Number of track points to skip for pagination")] = 0,
    sort: Annotated[
        str,
        Query(description="Sort column (timestamp, altitude, speed_kmh, heart_rate, created_at)"),
    ] = "timestamp",
    order: Annotated[
        Literal["asc", "desc"],
        Query(description="Sort direction: asc (earliest first) or desc (latest first)"),
    ] = "asc",
    simplify: Annotated[
        float | None,
        Query(
            ge=0.000001,
            le=0.01,
            description="Douglas-Peucker simplification tolerance in degrees. "
            "When set, returns the full route simplified via PostGIS ST_Simplify, "
            "ignoring limit/offset. Recommended: 0.00001 (~1m), 0.00005 (~5m).",
        ),
    ] = None,
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
    exists = await db.fetchval(SQL_ACTIVITY_EXISTS, activity_id)
    if not exists:
        raise HTTPException(status_code=404, detail=ACTIVITY_NOT_FOUND)

    total = await db.fetchval(
        "SELECT COUNT(*) FROM public.garmin_track_points WHERE activity_id = $1",
        activity_id,
    )

    if simplify is not None:
        # Map-rendering path: skip the geocoded_addresses LEFT JOIN here.
        # The CTE chain (ST_Simplify -> ST_DumpPoints -> ROW_NUMBER de-dup)
        # combined with the address join exceeded the asyncpg statement timeout
        # on large activities. Addresses are still served by the non-simplify
        # branch and by /activities/{id}/addresses (see issue #113).
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
            "  gtp.heart_rate, gtp.hr_zone, gtp.respiration_rate, gtp.cadence, "
            "  gtp.temperature_c, gtp.surface_type, gtp.effort_level, gtp.created_at, "
            "  ROW_NUMBER() OVER ("
            "    PARTITION BY gtp.longitude, gtp.latitude "
            "    ORDER BY gtp.timestamp, (gtp.altitude IS NOT NULL) DESC, gtp.id"
            "  ) AS rn "
            "  FROM public.garmin_track_points gtp "
            "  INNER JOIN simplified_coords sc "
            "    ON gtp.longitude = sc.lng AND gtp.latitude = sc.lat "
            "  WHERE gtp.activity_id = $1"
            ") "
            "SELECT m.id, m.activity_id, m.latitude, m.longitude, "
            "m.timestamp, m.altitude, m.distance_from_start_km, m.speed_kmh, "
            "m.heart_rate, m.hr_zone, m.respiration_rate, m.cadence, "
            "m.temperature_c, m.surface_type, m.effort_level, m.created_at "
            "FROM matched m "
            "WHERE m.rn = 1 "
            f"ORDER BY m.timestamp {order}",
            activity_id,
            simplify,
        )
        items = [_row_to_track_point(row) for row in rows]
        return PaginatedResponse(items=items, total=total, limit=len(items), offset=0)

    rows = await db.fetch(
        "SELECT gtp.id, gtp.activity_id, gtp.latitude, gtp.longitude, gtp.timestamp, "
        "gtp.altitude, gtp.distance_from_start_km, gtp.speed_kmh, gtp.heart_rate, "
        "gtp.hr_zone, gtp.respiration_rate, gtp.cadence, gtp.temperature_c, "
        "gtp.surface_type, gtp.effort_level, gtp.created_at, "
        "ga.display_address, ga.street, ga.housenumber, ga.neighbourhood, "
        "ga.locality, ga.region, ga.country, ga.postalcode, ga.confidence, "
        "ga.waypoint_kind, ga.status AS address_status, ga.geocoded_at, "
        "gpc.display_address AS cell_display_address, gpc.street AS cell_street, "
        "gpc.housenumber AS cell_housenumber, gpc.neighbourhood AS cell_neighbourhood, "
        "gpc.locality AS cell_locality, gpc.region AS cell_region, "
        "gpc.country AS cell_country, gpc.postalcode AS cell_postalcode, "
        "gpc.confidence AS cell_confidence, gpc.status AS cell_status, "
        "gpc.geocoded_at AS cell_geocoded_at "
        "FROM public.garmin_track_points gtp "
        "LEFT JOIN public.geocoded_addresses ga "
        "  ON ga.garmin_track_point_id = gtp.id "
        " AND ga.garmin_activity_id = gtp.activity_id "
        " AND ga.source = 'garmin' "
        "LEFT JOIN public.geocoded_point_cells gpc "
        "  ON gpc.lat_4dp = ROUND(gtp.latitude * 10000)::INTEGER "
        " AND gpc.lon_4dp = ROUND(gtp.longitude * 10000)::INTEGER "
        f"WHERE gtp.activity_id = $1 ORDER BY gtp.{sort} {order} "
        f"LIMIT $2 OFFSET $3",
        activity_id,
        limit,
        offset,
    )

    items = [_row_to_track_point(row) for row in rows]
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/activities/{activity_id}/chart-data",
    responses={404: {"description": ACTIVITY_NOT_FOUND}},
)
async def get_chart_data(
    request: Request,
    activity_id: Annotated[str, fastapi.Path(description=DESC_ACTIVITY_ID, examples=["20932993811"])],
) -> list[GarminChartPoint]:
    """Return all track points for chart rendering (no pagination).

    Provides the complete time-series data (altitude, speed, heart rate, cadence)
    for an activity, ordered by timestamp. Uniqueness is guaranteed by the
    UNIQUE(activity_id, timestamp) database constraint.
    """
    db = request.app.state.db

    exists = await db.fetchval(SQL_ACTIVITY_EXISTS, activity_id)
    if not exists:
        raise HTTPException(status_code=404, detail=ACTIVITY_NOT_FOUND)

    rows = await db.fetch(
        "SELECT latitude, longitude, timestamp, altitude, "
        "distance_from_start_km, speed_kmh, heart_rate, hr_zone, respiration_rate, "
        "cadence, temperature_c, surface_type, effort_level "
        "FROM public.garmin_track_points WHERE activity_id = $1 ORDER BY timestamp ASC",
        activity_id,
    )

    return [GarminChartPoint(**dict(row)) for row in rows]


@router.get(
    "/activities/{activity_id}/climbs",
    responses={404: {"description": ACTIVITY_NOT_FOUND}},
)
async def list_activity_climbs(
    request: Request,
    activity_id: Annotated[str, fastapi.Path(description=DESC_ACTIVITY_ID, examples=["20932993811"])],
) -> list[GarminActivityClimb]:
    """Return Garmin-native ClimbPro typed splits for an activity."""
    db = request.app.state.db

    exists = await db.fetchval(SQL_ACTIVITY_EXISTS, activity_id)
    if not exists:
        raise HTTPException(status_code=404, detail=ACTIVITY_NOT_FOUND)

    rows = await db.fetch(
        "SELECT id, activity_id, source_split_index, message_index, split_type, "
        "climb_type, start_time, end_time, start_time_local, duration_seconds, "
        "elapsed_duration_seconds, moving_duration_seconds, distance_meters, "
        "elevation_gain_meters, elevation_loss_meters, start_elevation_meters, "
        "average_grade_percent, max_grade_percent, average_speed_mps, "
        "average_moving_speed_mps, max_speed_mps, average_vertical_speed_mps, "
        "average_elapsed_vertical_speed_mps, start_latitude, start_longitude, "
        "end_latitude, end_longitude, climb_pro_difficulty, calories, "
        "bmr_calories, average_temperature_c, min_temperature_c, "
        "max_temperature_c, created_at, updated_at "
        "FROM public.garmin_activity_climbs WHERE activity_id = $1 "
        "ORDER BY source_split_index ASC",
        activity_id,
    )

    return [GarminActivityClimb(**dict(row)) for row in rows]


@router.get(
    "/activities/{activity_id}/laps",
    responses={404: {"description": ACTIVITY_NOT_FOUND}},
)
async def list_activity_laps(
    request: Request,
    activity_id: Annotated[str, fastapi.Path(description=DESC_ACTIVITY_ID, examples=["20932993811"])],
) -> list[GarminActivityLap]:
    """Return Garmin-native or derived laps for an activity."""
    db = request.app.state.db

    exists = await db.fetchval(SQL_ACTIVITY_EXISTS, activity_id)
    if not exists:
        raise HTTPException(status_code=404, detail=ACTIVITY_NOT_FOUND)

    rows = await db.fetch(
        "SELECT id, activity_id, lap_index, start_time, end_time, "
        "duration_seconds, elapsed_duration_seconds, moving_duration_seconds, "
        "distance_meters, paved_distance_meters, unpaved_distance_meters, "
        "avg_speed_mps, avg_heart_rate, max_heart_rate, total_ascent_meters, "
        "total_descent_meters, calories, created_at, updated_at "
        "FROM public.garmin_activity_laps WHERE activity_id = $1 "
        "ORDER BY lap_index ASC",
        activity_id,
    )

    return [GarminActivityLap(**dict(row)) for row in rows]


@router.get(
    "/laps",
    responses={422: {"description": "Invalid date format"}},
)
async def list_laps(
    request: Request,
    sport: Annotated[str | None, Query(description=DESC_FILTER_BY_SPORT, examples=["cycling"])] = None,
    date_from: Annotated[
        date | None,
        Query(description="Filter from date (YYYY-MM-DD)", examples=["2026-01-01"]),
    ] = None,
    date_to: Annotated[
        date | None,
        Query(description="Filter to date (YYYY-MM-DD)", examples=["2026-06-30"]),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500, description="Maximum number of activities to return per page")] = 50,
    offset: Annotated[int, Query(ge=0, description="Number of activities to skip for pagination")] = 0,
) -> PaginatedResponse[GarminActivityLapsGroup]:
    """Batch laps across activities for cross-activity comparison.

    Returns activities (newest first) that have at least one lap, each with
    its laps ordered by ``lap_index`` ascending, so lap N can be compared
    across dates. Pagination applies to activities, not individual laps.
    """
    db = request.app.state.db

    conditions: list[str] = ["EXISTS (SELECT 1 FROM public.garmin_activity_laps l WHERE l.activity_id = a.activity_id)"]
    params: list = []
    idx = 1

    if sport:
        conditions.append(f"a.sport = ${idx}")
        params.append(sport)
        idx += 1

    if date_from:
        conditions.append(f"a.start_time >= ${idx}::date")
        params.append(date_from)
        idx += 1

    if date_to:
        conditions.append(f"a.start_time < (${idx}::date + INTERVAL '1 day')")
        params.append(date_to)
        idx += 1

    where = f"WHERE {' AND '.join(conditions)}"

    total = await db.fetchval(f"SELECT COUNT(*) FROM public.garmin_activities a {where}", *params)

    activity_rows = await db.fetch(
        f"SELECT a.activity_id, a.sport, a.sub_sport, a.start_time, a.distance_km, "
        f"a.duration_seconds, a.avg_speed_kmh, a.avg_heart_rate, a.max_heart_rate, a.total_ascent_m "
        f"FROM public.garmin_activities a {where} "
        f"ORDER BY a.start_time DESC "
        f"LIMIT ${idx} OFFSET ${idx + 1}",
        *params,
        limit,
        offset,
    )

    activities = [GarminLapsActivity(**dict(row)) for row in activity_rows]
    laps_by_activity: dict[str, list[GarminActivityLap]] = {a.activity_id: [] for a in activities}

    if activities:
        lap_rows = await db.fetch(
            "SELECT id, activity_id, lap_index, start_time, end_time, "
            "duration_seconds, elapsed_duration_seconds, moving_duration_seconds, "
            "distance_meters, paved_distance_meters, unpaved_distance_meters, "
            "avg_speed_mps, avg_heart_rate, max_heart_rate, total_ascent_meters, "
            "total_descent_meters, calories, created_at, updated_at "
            "FROM public.garmin_activity_laps WHERE activity_id = ANY($1::text[]) "
            "ORDER BY lap_index ASC",
            list(laps_by_activity.keys()),
        )
        for row in lap_rows:
            lap = GarminActivityLap(**dict(row))
            laps_by_activity[lap.activity_id].append(lap)

    items = [
        GarminActivityLapsGroup(activity=activity, laps=laps_by_activity[activity.activity_id])
        for activity in activities
    ]
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


def _row_to_track_point(row: Mapping[str, Any]) -> GarminTrackPoint:
    """Build a GarminTrackPoint, attaching the joined address summary when present.

    When both a dense-cell row and a waypoint row exist for the same point,
    the cell address takes precedence (denser, always populated once backfilled);
    the waypoint row is used as a fallback while the cell backfill is in-flight.
    """
    data: dict[str, Any] = dict(row)
    # Waypoint columns (legacy / sparse).
    address_status = data.pop("address_status", None)
    display_address = data.pop("display_address", None)
    street = data.pop("street", None)
    housenumber = data.pop("housenumber", None)
    neighbourhood = data.pop("neighbourhood", None)
    locality = data.pop("locality", None)
    region = data.pop("region", None)
    country = data.pop("country", None)
    postalcode = data.pop("postalcode", None)
    confidence = data.pop("confidence", None)
    waypoint_kind = data.pop("waypoint_kind", None)
    geocoded_at = data.pop("geocoded_at", None)
    # Dense-cell columns (preferred when present).
    cell_status = data.pop("cell_status", None)
    cell_display_address = data.pop("cell_display_address", None)
    cell_street = data.pop("cell_street", None)
    cell_housenumber = data.pop("cell_housenumber", None)
    cell_neighbourhood = data.pop("cell_neighbourhood", None)
    cell_locality = data.pop("cell_locality", None)
    cell_region = data.pop("cell_region", None)
    cell_country = data.pop("cell_country", None)
    cell_postalcode = data.pop("cell_postalcode", None)
    cell_confidence = data.pop("cell_confidence", None)
    cell_geocoded_at = data.pop("cell_geocoded_at", None)

    address: GeocodedAddressSummary | None = None
    # Only prefer the cell address when it actually carries a usable address.
    # Non-success cell rows (pending/error/no_coverage) must not hide a waypoint
    # address that was successfully geocoded.
    if cell_status == "success" and cell_display_address is not None:
        address = GeocodedAddressSummary(
            display_address=cell_display_address,
            street=cell_street,
            housenumber=cell_housenumber,
            neighbourhood=cell_neighbourhood,
            locality=cell_locality,
            region=cell_region,
            country=cell_country,
            postalcode=cell_postalcode,
            confidence=cell_confidence,
            waypoint_kind=None,
            status=cell_status,
            geocoded_at=cell_geocoded_at,
        )
    elif address_status is not None:
        address = GeocodedAddressSummary(
            display_address=display_address,
            street=street,
            housenumber=housenumber,
            neighbourhood=neighbourhood,
            locality=locality,
            region=region,
            country=country,
            postalcode=postalcode,
            confidence=confidence,
            waypoint_kind=waypoint_kind,
            status=address_status,
            geocoded_at=geocoded_at,
        )
    return GarminTrackPoint(**data, address=address)


@router.get(
    "/activities/{activity_id}/addresses",
    responses={404: {"description": ACTIVITY_NOT_FOUND}},
)
async def list_activity_addresses(
    request: Request,
    activity_id: Annotated[str, fastapi.Path(description=DESC_ACTIVITY_ID, examples=["20932993811"])],
) -> list[GarminActivityAddress]:
    """Return all reverse-geocoded addresses for a Garmin activity, in timestamp order.

    Includes start, end, and mid-route waypoints as persisted by the Garmin
    geocoding pipeline.
    """
    db = request.app.state.db

    exists = await db.fetchval(SQL_ACTIVITY_EXISTS, activity_id)
    if not exists:
        raise HTTPException(status_code=404, detail=ACTIVITY_NOT_FOUND)

    rows = await db.fetch(
        "SELECT ga.garmin_track_point_id AS track_point_id, "
        "ga.garmin_activity_id AS activity_id, ga.waypoint_kind, "
        "gtp.timestamp, gtp.latitude, gtp.longitude, "
        "ga.display_address, ga.street, ga.housenumber, ga.neighbourhood, "
        "ga.locality, ga.region, ga.country, ga.postalcode, ga.confidence, "
        "ga.status, ga.geocoded_at "
        "FROM public.geocoded_addresses ga "
        "INNER JOIN public.garmin_track_points gtp ON gtp.id = ga.garmin_track_point_id "
        "WHERE ga.source = 'garmin' AND ga.garmin_activity_id = $1 "
        "ORDER BY CASE ga.waypoint_kind "
        "WHEN 'start' THEN 0 WHEN 'waypoint' THEN 1 WHEN 'end' THEN 2 ELSE 3 END, "
        "gtp.timestamp ASC",
        activity_id,
    )

    return [GarminActivityAddress(**dict(row)) for row in rows]


async def _fetch_segment_efforts(
    db: Any,
    *,
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    tolerance_meters: float,
    sport: str | None,
    date_from: date | None,
    date_to: date | None,
    max_effort_seconds: int,
    limit: int,
) -> list[SegmentEffort]:
    """Match GPS track points to a start→end corridor and rank efforts fastest-first.

    Shared by the stateless ``/segment-efforts`` endpoint and the saved-segment
    ``/segments/{id}/efforts`` endpoint. An activity qualifies when its route
    passes within ``tolerance_meters`` of the start point and, later in time,
    within tolerance of the end point (same direction); the shortest such
    traversal per activity is used.
    """
    params: list[Any] = [start_lon, start_lat, end_lon, end_lat, tolerance_meters]
    idx = 6

    sport_clause = ""
    if sport:
        sport_clause = f" AND a.sport = ${idx}"
        params.append(sport)
        idx += 1

    date_from_clause = ""
    if date_from:
        date_from_clause = f" AND a.start_time >= ${idx}::date"
        params.append(date_from)
        idx += 1

    date_to_clause = ""
    if date_to:
        date_to_clause = f" AND a.start_time < (${idx}::date + INTERVAL '1 day')"
        params.append(date_to)
        idx += 1

    max_effort_idx = idx
    params.append(max_effort_seconds)
    idx += 1
    limit_idx = idx
    params.append(limit)

    query = f"""
        WITH seg AS (
            SELECT ST_MakePoint($1, $2)::geography AS start_pt,
                   ST_MakePoint($3, $4)::geography AS end_pt,
                   $5::double precision AS tol
        ),
        filtered_activities AS (
            SELECT a.activity_id
            FROM public.garmin_activities a
            WHERE TRUE{sport_clause}{date_from_clause}{date_to_clause}
        ),
        starts AS (
            SELECT t.activity_id, t.timestamp AS s_ts
            FROM public.garmin_track_points t
            JOIN filtered_activities fa ON fa.activity_id = t.activity_id
            CROSS JOIN seg
            WHERE t.geog IS NOT NULL AND ST_DWithin(t.geog, seg.start_pt, seg.tol)
        ),
        ends AS (
            SELECT t.activity_id, t.timestamp AS e_ts
            FROM public.garmin_track_points t
            JOIN filtered_activities fa ON fa.activity_id = t.activity_id
            CROSS JOIN seg
            WHERE t.geog IS NOT NULL AND ST_DWithin(t.geog, seg.end_pt, seg.tol)
        ),
        pairs AS (
            SELECT s.activity_id, s.s_ts, MIN(e.e_ts) AS e_ts
            FROM starts s
            JOIN ends e ON e.activity_id = s.activity_id AND e.e_ts > s.s_ts
            GROUP BY s.activity_id, s.s_ts
        ),
        best AS (
            SELECT DISTINCT ON (activity_id) activity_id, s_ts, e_ts
            FROM pairs
            ORDER BY activity_id, (e_ts - s_ts) ASC
        ),
        metrics AS (
            SELECT b.activity_id, b.s_ts, b.e_ts,
                   EXTRACT(EPOCH FROM (b.e_ts - b.s_ts)) AS elapsed_seconds,
                   AVG(t.speed_kmh) AS avg_speed_kmh,
                   AVG(t.heart_rate) FILTER (WHERE t.heart_rate > 0) AS avg_hr,
                   MAX(t.heart_rate) AS max_heart_rate,
                   MAX(t.distance_from_start_km) - MIN(t.distance_from_start_km) AS distance_km
            FROM best b
            JOIN public.garmin_track_points t
              ON t.activity_id = b.activity_id
             AND t.timestamp BETWEEN b.s_ts AND b.e_ts
            GROUP BY b.activity_id, b.s_ts, b.e_ts
        )
        SELECT m.activity_id, a.sport, a.start_time AS activity_start_time,
               m.s_ts AS effort_start, m.e_ts AS effort_end,
               m.elapsed_seconds, m.distance_km, m.avg_speed_kmh,
               ROUND(m.avg_hr)::int AS avg_heart_rate, m.max_heart_rate
        FROM metrics m
        JOIN public.garmin_activities a ON a.activity_id = m.activity_id
        WHERE m.elapsed_seconds <= ${max_effort_idx}
        ORDER BY m.elapsed_seconds ASC
        LIMIT ${limit_idx}
    """

    rows = await db.fetch(query, *params)
    return [SegmentEffort(rank=i + 1, **dict(row)) for i, row in enumerate(rows)]


@router.get(
    "/segment-efforts",
    responses={422: {"description": "Invalid date format"}},
)
async def list_segment_efforts(
    request: Request,
    start_lat: Annotated[float, Query(description="Segment start latitude", examples=[40.79366846])],
    start_lon: Annotated[float, Query(description="Segment start longitude", examples=[-73.96104321])],
    end_lat: Annotated[float, Query(description="Segment end latitude", examples=[40.79002409])],
    end_lon: Annotated[float, Query(description="Segment end longitude", examples=[-73.96422816])],
    tolerance_meters: Annotated[
        int,
        Query(ge=5, le=200, description="Corridor radius around the start/end points in meters"),
    ] = 35,
    sport: Annotated[
        str | None,
        Query(description="Filter by sport type; pass an empty value to include all sports"),
    ] = "cycling",
    date_from: Annotated[
        date | None,
        Query(description="Filter from date (YYYY-MM-DD) on activity start_time", examples=["2024-01-01"]),
    ] = None,
    date_to: Annotated[
        date | None,
        Query(description="Filter to date (YYYY-MM-DD) on activity start_time", examples=["2026-06-30"]),
    ] = None,
    max_effort_seconds: Annotated[
        int,
        Query(ge=1, le=86400, description="Ignore traversals longer than this (filters loop/return mismatches)"),
    ] = 3600,
    limit: Annotated[int, Query(ge=1, le=500, description="Maximum number of efforts to return")] = 100,
) -> SegmentEffortsResponse:
    """Rank activity efforts over an ad-hoc segment defined by start/end coordinates.

    Matches raw GPS track points with PostGIS: an activity qualifies when its
    route passes within ``tolerance_meters`` of the start point and, later in
    time, within tolerance of the end point (same direction of travel). For each
    activity the shortest such start→end traversal is used, and efforts are
    ranked fastest-first. Stateless (no stored segment) — the coordinate pair can
    be sourced from a detected climb or lap.
    """
    db = request.app.state.db

    items = await _fetch_segment_efforts(
        db,
        start_lat=start_lat,
        start_lon=start_lon,
        end_lat=end_lat,
        end_lon=end_lon,
        tolerance_meters=tolerance_meters,
        sport=sport,
        date_from=date_from,
        date_to=date_to,
        max_effort_seconds=max_effort_seconds,
        limit=limit,
    )
    return SegmentEffortsResponse(
        segment=SegmentDefinition(
            start_lat=start_lat,
            start_lon=start_lon,
            end_lat=end_lat,
            end_lon=end_lon,
            tolerance_meters=tolerance_meters,
        ),
        total=len(items),
        items=items,
    )


_SEGMENT_COLUMNS = (
    "id, name, sport, start_latitude, start_longitude, end_latitude, end_longitude, "
    "distance_meters::double precision AS distance_meters, "
    "match_tolerance_meters::double precision AS match_tolerance_meters, "
    "source_activity_id, source_lap_index, source_climb_index, created_at, updated_at"
)

# Aliased column list (table alias ``s``) for the read endpoints, which join a
# LATERAL subquery that recovers the segment route geometry.
_SEGMENT_SELECT_COLUMNS = (
    "s.id, s.name, s.sport, s.start_latitude, s.start_longitude, s.end_latitude, s.end_longitude, "
    "s.distance_meters::double precision AS distance_meters, "
    "s.match_tolerance_meters::double precision AS match_tolerance_meters, "
    "s.source_activity_id, s.source_lap_index, s.source_climb_index, s.created_at, s.updated_at, "
    "r.route"
)

# Recover each segment's real path from its source activity GPS track: snap the
# stored start/end to the nearest in-corridor track points (same ST_DWithin
# corridor used by segment efforts), slice the ordered track between them, and
# return a PostGIS-simplified array of ordered [latitude, longitude] pairs.
# Yields NULL route when the segment has no source activity or no matchable
# corridor, in which case the client falls back to a straight start→end line.
_SEGMENT_ROUTE_LATERAL = """
    LEFT JOIN LATERAL (
        WITH bounds AS (
            SELECT
                ST_MakePoint(s.start_longitude, s.start_latitude)::geography AS start_pt,
                ST_MakePoint(s.end_longitude, s.end_latitude)::geography AS end_pt,
                GREATEST(s.match_tolerance_meters, 5)::double precision AS tol
        ),
        start_ts AS (
            SELECT MIN(t.timestamp) AS ts
            FROM public.garmin_track_points t, bounds
            WHERE t.activity_id = s.source_activity_id
              AND t.geog IS NOT NULL
              AND ST_DWithin(t.geog, bounds.start_pt, bounds.tol)
        ),
        end_ts AS (
            SELECT MIN(t.timestamp) AS ts
            FROM public.garmin_track_points t, bounds, start_ts
            WHERE t.activity_id = s.source_activity_id
              AND t.geog IS NOT NULL
              AND ST_DWithin(t.geog, bounds.end_pt, bounds.tol)
              AND start_ts.ts IS NOT NULL
              AND t.timestamp > start_ts.ts
        ),
        line AS (
            SELECT ST_Simplify(
                       ST_MakeLine(ST_MakePoint(t.longitude, t.latitude) ORDER BY t.timestamp ASC),
                       0.00005
                   ) AS geom
            FROM public.garmin_track_points t, start_ts, end_ts
            WHERE t.activity_id = s.source_activity_id
              AND t.latitude IS NOT NULL
              AND t.longitude IS NOT NULL
              AND start_ts.ts IS NOT NULL
              AND end_ts.ts IS NOT NULL
              AND t.timestamp BETWEEN start_ts.ts AND end_ts.ts
        )
        SELECT array_agg(
                   ARRAY[ST_Y((dp).geom), ST_X((dp).geom)]
                   ORDER BY (dp).path
               ) AS route
        FROM line
        CROSS JOIN LATERAL ST_DumpPoints(line.geom) AS dp
        WHERE line.geom IS NOT NULL
          AND ST_NPoints(line.geom) >= 2
    ) r ON s.source_activity_id IS NOT NULL
"""


@router.get("/segments")
async def list_segments(
    request: Request,
    sport: Annotated[str | None, Query(description=DESC_FILTER_BY_SPORT, examples=["cycling"])] = None,
) -> list[GarminSegment]:
    """List saved segments (paths), newest first."""
    db = request.app.state.db
    where = "WHERE garmin_sync_status IS DISTINCT FROM 'delete_pending'"
    params: list[Any] = []
    if sport:
        where += " AND sport = $1"
        params.append(sport)
    rows = await db.fetch(
        f"SELECT {_SEGMENT_SELECT_COLUMNS} FROM public.garmin_segments s "
        f"{_SEGMENT_ROUTE_LATERAL} {where} ORDER BY created_at DESC",
        *params,
    )
    return [GarminSegment(**dict(row)) for row in rows]


@router.post(
    "/segments",
    status_code=201,
    responses={500: {"description": "Failed to create segment"}},
)
async def create_segment(
    request: Request,
    body: GarminSegmentCreate,
    _user: Annotated[dict, Depends(require_auth)],
) -> GarminSegment:
    """Save a new segment (path) from a climb, lap, or manual selection (auth required)."""
    db = request.app.state.db
    row = await db.fetchrow(
        "INSERT INTO public.garmin_segments "
        "(name, sport, start_latitude, start_longitude, end_latitude, end_longitude, "
        "distance_meters, match_tolerance_meters, source_activity_id, source_lap_index, source_climb_index) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11) "
        f"RETURNING {_SEGMENT_COLUMNS}",
        body.name,
        body.sport,
        body.start_latitude,
        body.start_longitude,
        body.end_latitude,
        body.end_longitude,
        body.distance_meters,
        body.match_tolerance_meters,
        body.source_activity_id,
        body.source_lap_index,
        body.source_climb_index,
    )
    if not row:
        raise HTTPException(status_code=500, detail="Failed to create segment")
    return GarminSegment(**dict(row))


@router.get(
    "/segments/{segment_id}",
    responses={404: {"description": SEGMENT_NOT_FOUND}},
)
async def get_segment(
    request: Request,
    segment_id: Annotated[int, fastapi.Path(description=DESC_SAVED_SEGMENT_ID)],
) -> GarminSegment:
    """Get a single saved segment by ID."""
    db = request.app.state.db
    row = await db.fetchrow(
        f"SELECT {_SEGMENT_SELECT_COLUMNS} FROM public.garmin_segments s "
        f"{_SEGMENT_ROUTE_LATERAL} "
        "WHERE id = $1 AND garmin_sync_status IS DISTINCT FROM 'delete_pending'",
        segment_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail=SEGMENT_NOT_FOUND)
    return GarminSegment(**dict(row))


@router.delete(
    "/segments/{segment_id}",
    status_code=204,
    response_class=Response,
    responses={**AUTH_RESPONSES, 404: {"description": SEGMENT_NOT_FOUND}},
)
async def delete_segment(
    request: Request,
    segment_id: Annotated[int, fastapi.Path(description=DESC_SAVED_SEGMENT_ID)],
    _user: Annotated[dict, Depends(require_auth)],
) -> Response:
    """Delete a saved segment (auth required).

    If the segment has been pushed to Garmin Connect (``garmin_segment_uuid`` is
    set) it is marked ``delete_pending`` so the garmin-sync agent removes it from
    Garmin and then deletes the row (end-to-end delete). Segments that were never
    synced are removed immediately. Either way the segment stops appearing in the
    read endpoints right away.
    """
    db = request.app.state.db
    row = await db.fetchrow(
        "SELECT garmin_segment_uuid FROM public.garmin_segments "
        "WHERE id = $1 AND garmin_sync_status IS DISTINCT FROM 'delete_pending'",
        segment_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail=SEGMENT_NOT_FOUND)
    if row["garmin_segment_uuid"] is not None:
        # Synced to Garmin: hand off to the agent for end-to-end deletion.
        await db.execute(
            "UPDATE public.garmin_segments SET garmin_sync_status = 'delete_pending', updated_at = NOW() WHERE id = $1",
            segment_id,
        )
    else:
        # Never synced to Garmin: remove immediately.
        await db.execute("DELETE FROM public.garmin_segments WHERE id = $1", segment_id)
    return Response(status_code=204)


@router.get(
    "/segments/{segment_id}/efforts",
    responses={404: {"description": SEGMENT_NOT_FOUND}},
)
async def get_segment_efforts(
    request: Request,
    segment_id: Annotated[int, fastapi.Path(description=DESC_SAVED_SEGMENT_ID)],
    date_from: Annotated[
        date | None,
        Query(description="Filter from date (YYYY-MM-DD) on activity start_time"),
    ] = None,
    date_to: Annotated[
        date | None,
        Query(description="Filter to date (YYYY-MM-DD) on activity start_time"),
    ] = None,
    max_effort_seconds: Annotated[
        int,
        Query(ge=1, le=86400, description="Ignore traversals longer than this"),
    ] = 3600,
    limit: Annotated[int, Query(ge=1, le=500, description="Maximum number of efforts to return")] = 100,
) -> SegmentEffortsResponse:
    """Rank activity efforts over a saved segment (matches the saved start/end corridor)."""
    db = request.app.state.db
    seg = await db.fetchrow(
        "SELECT sport, start_latitude, start_longitude, end_latitude, end_longitude, "
        "match_tolerance_meters::double precision AS match_tolerance_meters "
        "FROM public.garmin_segments WHERE id = $1 AND garmin_sync_status IS DISTINCT FROM 'delete_pending'",
        segment_id,
    )
    if not seg:
        raise HTTPException(status_code=404, detail=SEGMENT_NOT_FOUND)

    tolerance = float(seg["match_tolerance_meters"])
    items = await _fetch_segment_efforts(
        db,
        start_lat=seg["start_latitude"],
        start_lon=seg["start_longitude"],
        end_lat=seg["end_latitude"],
        end_lon=seg["end_longitude"],
        tolerance_meters=tolerance,
        sport=seg["sport"],
        date_from=date_from,
        date_to=date_to,
        max_effort_seconds=max_effort_seconds,
        limit=limit,
    )
    return SegmentEffortsResponse(
        segment=SegmentDefinition(
            start_lat=seg["start_latitude"],
            start_lon=seg["start_longitude"],
            end_lat=seg["end_latitude"],
            end_lon=seg["end_longitude"],
            tolerance_meters=tolerance,
        ),
        total=len(items),
        items=items,
    )
