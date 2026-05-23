"""Geocoding management endpoints for reverse-geocoding OwnTracks + Garmin records."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import structlog
from fastapi import APIRouter, Depends, Query, Request

from app.auth import require_auth
from app.models.geocoding import (
    GeocodingSourceStatus,
    GeocodingStatus,
    GeocodingStatusBySource,
    GeocodingTriggerResponse,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/geocoding", tags=["Geocoding"])
internal_router = APIRouter(prefix="/internal/geocoding", tags=["Internal"])

PELIAS_REVERSE_PATH = "/v1/reverse"
MAX_GEOCODE_CONCURRENCY = 5
DEFAULT_GARMIN_WAYPOINT_SPACING_KM = 1.0

_OT_CONFLICT = "ON CONFLICT (location_id) WHERE source = 'owntracks'"
_GARMIN_CONFLICT = "ON CONFLICT (garmin_track_point_id) WHERE source = 'garmin'"


@router.get("/status", response_model=GeocodingStatus)
async def geocoding_status(request: Request) -> GeocodingStatus:
    """Get geocoding coverage statistics for both OwnTracks and Garmin sources."""
    db = request.app.state.db

    total = await db.fetchval("SELECT COUNT(*) FROM public.locations")
    geocoded = await db.fetchval("SELECT COUNT(*) FROM public.geocoded_addresses WHERE source = 'owntracks'")
    ot_success = await db.fetchval(
        "SELECT COUNT(*) FROM public.geocoded_addresses WHERE source = 'owntracks' AND status = 'success'"
    )
    ot_pending = await db.fetchval(
        "SELECT COUNT(*) FROM public.geocoded_addresses WHERE source = 'owntracks' AND status = 'pending'"
    )
    ot_no_coverage = await db.fetchval(
        "SELECT COUNT(*) FROM public.geocoded_addresses WHERE source = 'owntracks' AND status = 'no_coverage'"
    )
    ot_errors = await db.fetchval(
        "SELECT COUNT(*) FROM public.geocoded_addresses WHERE source = 'owntracks' AND status = 'error'"
    )
    coverage_percent = round((geocoded / total * 100), 2) if total > 0 else 0.0

    g_success = await db.fetchval(
        "SELECT COUNT(*) FROM public.geocoded_addresses WHERE source = 'garmin' AND status = 'success'"
    )
    g_pending = await db.fetchval(
        "SELECT COUNT(*) FROM public.geocoded_addresses WHERE source = 'garmin' AND status = 'pending'"
    )
    g_no_coverage = await db.fetchval(
        "SELECT COUNT(*) FROM public.geocoded_addresses WHERE source = 'garmin' AND status = 'no_coverage'"
    )
    g_errors = await db.fetchval(
        "SELECT COUNT(*) FROM public.geocoded_addresses WHERE source = 'garmin' AND status = 'error'"
    )
    g_total_rows = (g_success or 0) + (g_pending or 0) + (g_no_coverage or 0) + (g_errors or 0)

    activities_total = await db.fetchval("SELECT COUNT(*) FROM public.garmin_activities")
    activities_geocoded = await db.fetchval(
        "SELECT COUNT(DISTINCT garmin_activity_id) FROM public.geocoded_addresses WHERE source = 'garmin'"
    )
    garmin_coverage_percent = round((activities_geocoded / activities_total * 100), 2) if activities_total else 0.0

    by_source = GeocodingStatusBySource(
        owntracks=GeocodingSourceStatus(
            success=ot_success or 0,
            pending=ot_pending or 0,
            no_coverage=ot_no_coverage or 0,
            errors=ot_errors or 0,
            total=geocoded or 0,
        ),
        garmin=GeocodingSourceStatus(
            success=g_success or 0,
            pending=g_pending or 0,
            no_coverage=g_no_coverage or 0,
            errors=g_errors or 0,
            total=g_total_rows,
        ),
        garmin_activities_total=activities_total or 0,
        garmin_activities_geocoded=activities_geocoded or 0,
        garmin_coverage_percent=garmin_coverage_percent,
    )

    return GeocodingStatus(
        total_locations=total,
        geocoded=geocoded,
        success=ot_success,
        pending=ot_pending,
        no_coverage=ot_no_coverage,
        errors=ot_errors,
        coverage_percent=coverage_percent,
        by_source=by_source,
    )


# ---------------------------------------------------------------------------
# OwnTracks trigger
# ---------------------------------------------------------------------------


@router.post("/trigger", response_model=GeocodingTriggerResponse)
async def trigger_geocoding(
    request: Request,
    batch_size: int = Query(100, ge=1, le=500, description="Number of locations to geocode in this batch"),
    retry_failed: bool = Query(False, description="Re-process records with status no_coverage or error"),
    _user: dict = Depends(require_auth),
) -> GeocodingTriggerResponse:
    """Trigger batch reverse-geocoding of OwnTracks location records (auth required)."""
    return await _trigger_geocoding_impl(request, batch_size, retry_failed)


@internal_router.post("/trigger", response_model=GeocodingTriggerResponse)
async def internal_trigger_geocoding(
    request: Request,
    batch_size: int = Query(100, ge=1, le=1000, description="Number of locations to geocode in this batch"),
    retry_failed: bool = Query(False, description="Re-process records with status no_coverage or error"),
) -> GeocodingTriggerResponse:
    """Trigger batch OwnTracks reverse-geocoding (internal, no auth)."""
    return await _trigger_geocoding_impl(request, batch_size, retry_failed)


async def _trigger_geocoding_impl(
    request: Request,
    batch_size: int,
    retry_failed: bool,
) -> GeocodingTriggerResponse:
    db = request.app.state.db
    config = request.app.state.config
    pelias_base_url = config.pelias_base_url
    pelias_timeout = config.pelias_timeout_seconds

    if retry_failed:
        rows = await db.fetch(
            "SELECT l.id, l.latitude, l.longitude "
            "FROM public.locations l "
            "INNER JOIN public.geocoded_addresses ga ON ga.location_id = l.id "
            "WHERE ga.source = 'owntracks' AND ga.status IN ('no_coverage', 'error') "
            "ORDER BY l.id LIMIT $1",
            batch_size,
        )
    else:
        rows = await db.fetch(
            "SELECT l.id, l.latitude, l.longitude "
            "FROM public.locations l "
            "LEFT JOIN public.geocoded_addresses ga "
            "  ON ga.location_id = l.id AND ga.source = 'owntracks' "
            "WHERE ga.id IS NULL "
            "ORDER BY l.id LIMIT $1",
            batch_size,
        )

    processed = 0
    skipped_dedup = 0
    sem = asyncio.Semaphore(MAX_GEOCODE_CONCURRENCY)

    async def _geocode_one(client: httpx.AsyncClient, row: dict[str, Any]) -> tuple[int, int]:
        async with sem:
            return await _process_location(db, client, pelias_base_url, row)

    async with httpx.AsyncClient(timeout=pelias_timeout) as client:
        results = await asyncio.gather(*[_geocode_one(client, dict(row)) for row in rows])
        for proc, skip in results:
            processed += proc
            skipped_dedup += skip

    remaining = await db.fetchval(
        "SELECT COUNT(*) FROM public.locations l "
        "LEFT JOIN public.geocoded_addresses ga "
        "  ON ga.location_id = l.id AND ga.source = 'owntracks' "
        "WHERE ga.id IS NULL"
    )

    return GeocodingTriggerResponse(processed=processed, remaining=remaining, skipped_dedup=skipped_dedup)


async def _process_location(
    db: Any,
    client: httpx.AsyncClient,
    pelias_base_url: str,
    row: dict[str, Any],
) -> tuple[int, int]:
    """Process a single OwnTracks location for reverse geocoding."""
    location_id = row["id"]
    lat = row["latitude"]
    lon = row["longitude"]

    try:
        return await _process_location_inner(db, client, pelias_base_url, location_id, lat, lon)
    except TimeoutError:
        logger.warning("Database timeout for location %d, skipping", location_id)
        return 0, 0
    except Exception:
        logger.warning("Unexpected error processing location %d", location_id, exc_info=True)
        try:
            await _upsert_owntracks_status(db, location_id, status="error")
        except Exception:
            logger.warning("Failed to upsert error status for location %d", location_id, exc_info=True)
        return 0, 0


async def _process_location_inner(
    db: Any,
    client: httpx.AsyncClient,
    pelias_base_url: str,
    location_id: int,
    lat: float,
    lon: float,
) -> tuple[int, int]:
    """OwnTracks geocoding: proximity dedup -> Pelias -> upsert."""
    neighbour = await _find_nearby_address(db, lat, lon)
    if neighbour:
        await _persist_owntracks_from_neighbour(db, location_id, neighbour)
        return 0, 1

    pelias_data = await _call_pelias(client, pelias_base_url, lat, lon)
    if pelias_data is None:
        await _upsert_owntracks_status(db, location_id, status="error")
        return 1, 0

    features = pelias_data.get("features", [])
    if not features:
        await _upsert_owntracks_status(db, location_id, status="no_coverage")
        return 1, 0

    props = features[0].get("properties", {})
    await _persist_owntracks_from_pelias(db, location_id, props, pelias_data)
    return 1, 0


# ---------------------------------------------------------------------------
# Garmin trigger
# ---------------------------------------------------------------------------


@internal_router.post("/trigger/garmin", response_model=GeocodingTriggerResponse)
async def internal_trigger_garmin_geocoding(
    request: Request,
    batch_size: int = Query(10, ge=1, le=100, description="Number of Garmin activities to process in this batch"),
    waypoint_spacing_km: float = Query(
        DEFAULT_GARMIN_WAYPOINT_SPACING_KM,
        ge=0.1,
        le=50.0,
        description="Approximate spacing between mid-route waypoints in kilometres",
    ),
    retry_failed: bool = Query(
        False,
        description="Re-process activities with at least one no_coverage or error waypoint",
    ),
) -> GeocodingTriggerResponse:
    """Trigger batch reverse-geocoding of Garmin activity waypoints (internal, no auth).

    For each selected activity, picks the start, end, and every-``waypoint_spacing_km`` mid-route
    track point as waypoints, then reverse-geocodes each one through Pelias.
    """
    return await _trigger_garmin_geocoding_impl(request, batch_size, waypoint_spacing_km, retry_failed)


@router.post("/trigger/garmin", response_model=GeocodingTriggerResponse)
async def trigger_garmin_geocoding(
    request: Request,
    batch_size: int = Query(10, ge=1, le=100, description="Number of Garmin activities to process in this batch"),
    waypoint_spacing_km: float = Query(
        DEFAULT_GARMIN_WAYPOINT_SPACING_KM,
        ge=0.1,
        le=50.0,
        description="Approximate spacing between mid-route waypoints in kilometres",
    ),
    retry_failed: bool = Query(
        False,
        description="Re-process activities with at least one no_coverage or error waypoint",
    ),
    _user: dict = Depends(require_auth),
) -> GeocodingTriggerResponse:
    """Trigger batch reverse-geocoding of Garmin activity waypoints (auth required)."""
    return await _trigger_garmin_geocoding_impl(request, batch_size, waypoint_spacing_km, retry_failed)


async def _trigger_garmin_geocoding_impl(
    request: Request,
    batch_size: int,
    waypoint_spacing_km: float,
    retry_failed: bool,
) -> GeocodingTriggerResponse:
    db = request.app.state.db
    config = request.app.state.config
    pelias_base_url = config.pelias_base_url
    pelias_timeout = config.pelias_timeout_seconds

    if retry_failed:
        activity_rows = await db.fetch(
            "SELECT DISTINCT a.activity_id "
            "FROM public.garmin_activities a "
            "INNER JOIN public.geocoded_addresses ga "
            "  ON ga.garmin_activity_id = a.activity_id AND ga.source = 'garmin' "
            "WHERE ga.status IN ('no_coverage', 'error') "
            "ORDER BY a.activity_id LIMIT $1",
            batch_size,
        )
    else:
        activity_rows = await db.fetch(
            "SELECT a.activity_id "
            "FROM public.garmin_activities a "
            "LEFT JOIN public.geocoded_addresses ga "
            "  ON ga.garmin_activity_id = a.activity_id AND ga.source = 'garmin' "
            "WHERE ga.id IS NULL "
            "AND EXISTS ("
            "  SELECT 1 FROM public.garmin_track_points gtp "
            "  WHERE gtp.activity_id = a.activity_id"
            ") "
            "GROUP BY a.activity_id "
            "ORDER BY MAX(a.start_time) DESC NULLS LAST "
            "LIMIT $1",
            batch_size,
        )

    processed = 0
    skipped_dedup = 0
    sem = asyncio.Semaphore(MAX_GEOCODE_CONCURRENCY)

    async def _geocode_one(client: httpx.AsyncClient, waypoint: dict[str, Any]) -> tuple[int, int]:
        async with sem:
            return await _process_garmin_waypoint(db, client, pelias_base_url, waypoint)

    async with httpx.AsyncClient(timeout=pelias_timeout) as client:
        for activity in activity_rows:
            activity_id = activity["activity_id"]
            waypoints = await _select_garmin_waypoints(db, activity_id, waypoint_spacing_km)
            results = await asyncio.gather(*[_geocode_one(client, wp) for wp in waypoints])
            for proc, skip in results:
                processed += proc
                skipped_dedup += skip

    remaining = await db.fetchval(
        "SELECT COUNT(DISTINCT a.activity_id) FROM public.garmin_activities a "
        "LEFT JOIN public.geocoded_addresses ga "
        "  ON ga.garmin_activity_id = a.activity_id AND ga.source = 'garmin' "
        "WHERE ga.id IS NULL "
        "AND EXISTS ("
        "  SELECT 1 FROM public.garmin_track_points gtp "
        "  WHERE gtp.activity_id = a.activity_id"
        ")"
    )

    return GeocodingTriggerResponse(processed=processed, remaining=remaining, skipped_dedup=skipped_dedup)


async def _select_garmin_waypoints(
    db: Any,
    activity_id: str,
    spacing_km: float,
) -> list[dict[str, Any]]:
    """Pick start, end, and every-``spacing_km`` mid-route waypoints from an activity's track."""
    rows = await db.fetch(
        "SELECT id, latitude, longitude, timestamp, distance_from_start_km "
        "FROM public.garmin_track_points "
        "WHERE activity_id = $1 "
        "ORDER BY timestamp ASC",
        activity_id,
    )
    if not rows:
        return []

    points = [dict(r) for r in rows]
    waypoints: list[dict[str, Any]] = []
    waypoints.append({**points[0], "waypoint_kind": "start", "activity_id": activity_id})

    last_d = float(points[0].get("distance_from_start_km") or 0.0)
    for p in points[1:-1]:
        d = p.get("distance_from_start_km")
        if d is None:
            continue
        d_float = float(d)
        if d_float - last_d >= spacing_km:
            waypoints.append({**p, "waypoint_kind": "waypoint", "activity_id": activity_id})
            last_d = d_float

    if len(points) > 1:
        waypoints.append({**points[-1], "waypoint_kind": "end", "activity_id": activity_id})

    return waypoints


async def _process_garmin_waypoint(
    db: Any,
    client: httpx.AsyncClient,
    pelias_base_url: str,
    waypoint: dict[str, Any],
) -> tuple[int, int]:
    """Process a single Garmin waypoint (start/end/mid) for reverse geocoding."""
    track_point_id = waypoint["id"]
    activity_id = waypoint["activity_id"]
    waypoint_kind = waypoint["waypoint_kind"]
    lat = waypoint["latitude"]
    lon = waypoint["longitude"]

    try:
        return await _process_garmin_waypoint_inner(
            db, client, pelias_base_url, track_point_id, activity_id, waypoint_kind, lat, lon
        )
    except TimeoutError:
        logger.warning("Database timeout for garmin track point %d, skipping", track_point_id)
        # Persist an error status row so this waypoint can be retried with
        # retry_failed=True; otherwise the activity selection query would
        # consider this activity "done" once any other waypoint succeeds.
        try:
            await _upsert_garmin_status(db, track_point_id, activity_id, waypoint_kind, status="error")
        except Exception:
            logger.warning(
                "Failed to upsert error status after timeout for garmin track point %d",
                track_point_id,
                exc_info=True,
            )
        return 0, 0
    except Exception:
        logger.warning("Unexpected error processing garmin track point %d", track_point_id, exc_info=True)
        try:
            await _upsert_garmin_status(db, track_point_id, activity_id, waypoint_kind, status="error")
        except Exception:
            logger.warning(
                "Failed to upsert error status for garmin track point %d",
                track_point_id,
                exc_info=True,
            )
        return 0, 0


async def _process_garmin_waypoint_inner(
    db: Any,
    client: httpx.AsyncClient,
    pelias_base_url: str,
    track_point_id: int,
    activity_id: str,
    waypoint_kind: str,
    lat: float,
    lon: float,
) -> tuple[int, int]:
    """Garmin geocoding: proximity dedup -> Pelias -> upsert with FKs + waypoint_kind."""
    neighbour = await _find_nearby_address(db, lat, lon)
    if neighbour:
        await _persist_garmin_from_neighbour(db, track_point_id, activity_id, waypoint_kind, neighbour)
        return 0, 1

    pelias_data = await _call_pelias(client, pelias_base_url, lat, lon)
    if pelias_data is None:
        await _upsert_garmin_status(db, track_point_id, activity_id, waypoint_kind, status="error")
        return 1, 0

    features = pelias_data.get("features", [])
    if not features:
        await _upsert_garmin_status(db, track_point_id, activity_id, waypoint_kind, status="no_coverage")
        return 1, 0

    props = features[0].get("properties", {})
    await _persist_garmin_from_pelias(db, track_point_id, activity_id, waypoint_kind, props, pelias_data)
    return 1, 0


# ---------------------------------------------------------------------------
# Shared helpers: Pelias call, proximity dedup, persistence
# ---------------------------------------------------------------------------


async def _find_nearby_address(db: Any, lat: float, lon: float) -> dict[str, Any] | None:
    """Return the nearest successfully geocoded address within 50 m, or None."""
    neighbour = await db.fetchrow(
        "SELECT ga.display_address, ga.street, ga.housenumber, ga.neighbourhood, "
        "ga.locality, ga.region, ga.country, ga.postalcode, ga.confidence, "
        "ga.raw_response "
        "FROM public.geocoded_addresses ga "
        "LEFT JOIN public.locations l ON l.id = ga.location_id AND ga.source = 'owntracks' "
        "LEFT JOIN public.garmin_track_points gtp "
        "  ON gtp.id = ga.garmin_track_point_id AND ga.source = 'garmin' "
        "WHERE ga.status = 'success' "
        "AND ST_DWithin("
        "  COALESCE(l.geog, ST_SetSRID(ST_MakePoint(gtp.longitude, gtp.latitude), 4326)::geography), "
        "  ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography, "
        "  50"
        ") "
        "ORDER BY ST_Distance("
        "  COALESCE(l.geog, ST_SetSRID(ST_MakePoint(gtp.longitude, gtp.latitude), 4326)::geography), "
        "  ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography"
        ") LIMIT 1",
        lon,
        lat,
    )
    return dict(neighbour) if neighbour else None


async def _call_pelias(
    client: httpx.AsyncClient,
    pelias_base_url: str,
    lat: float,
    lon: float,
) -> dict[str, Any] | None:
    """Call the Pelias reverse-geocoder. Returns parsed JSON or None on transport error."""
    try:
        resp = await client.get(
            f"{pelias_base_url}{PELIAS_REVERSE_PATH}",
            params={"point.lat": lat, "point.lon": lon, "size": 1},
        )
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        return data
    except httpx.HTTPError:
        logger.warning("Pelias request failed", exc_info=True)
        return None


# --- OwnTracks persistence -------------------------------------------------


async def _persist_owntracks_from_neighbour(db: Any, location_id: int, neighbour: dict[str, Any]) -> None:
    await db.execute(
        "INSERT INTO public.geocoded_addresses "
        "(location_id, source, display_address, street, housenumber, "
        "neighbourhood, locality, region, country, postalcode, "
        "confidence, status, raw_response) "
        "VALUES ($1, 'owntracks', $2, $3, $4, $5, $6, $7, $8, $9, $10, 'success', $11) "
        f"{_OT_CONFLICT} DO UPDATE SET "
        "display_address = EXCLUDED.display_address, "
        "street = EXCLUDED.street, housenumber = EXCLUDED.housenumber, "
        "neighbourhood = EXCLUDED.neighbourhood, locality = EXCLUDED.locality, "
        "region = EXCLUDED.region, country = EXCLUDED.country, "
        "postalcode = EXCLUDED.postalcode, confidence = EXCLUDED.confidence, "
        "status = EXCLUDED.status, raw_response = EXCLUDED.raw_response, "
        "geocoded_at = CURRENT_TIMESTAMP",
        location_id,
        neighbour["display_address"],
        neighbour["street"],
        neighbour["housenumber"],
        neighbour["neighbourhood"],
        neighbour["locality"],
        neighbour["region"],
        neighbour["country"],
        neighbour["postalcode"],
        neighbour["confidence"],
        neighbour["raw_response"],
    )


async def _persist_owntracks_from_pelias(
    db: Any, location_id: int, props: dict[str, Any], raw_data: dict[str, Any]
) -> None:
    await db.execute(
        "INSERT INTO public.geocoded_addresses "
        "(location_id, source, display_address, street, housenumber, "
        "neighbourhood, locality, region, country, postalcode, "
        "confidence, status, raw_response) "
        "VALUES ($1, 'owntracks', $2, $3, $4, $5, $6, $7, $8, $9, $10, 'success', $11) "
        f"{_OT_CONFLICT} DO UPDATE SET "
        "display_address = EXCLUDED.display_address, "
        "street = EXCLUDED.street, housenumber = EXCLUDED.housenumber, "
        "neighbourhood = EXCLUDED.neighbourhood, locality = EXCLUDED.locality, "
        "region = EXCLUDED.region, country = EXCLUDED.country, "
        "postalcode = EXCLUDED.postalcode, confidence = EXCLUDED.confidence, "
        "status = EXCLUDED.status, raw_response = EXCLUDED.raw_response, "
        "geocoded_at = CURRENT_TIMESTAMP",
        location_id,
        props.get("label"),
        props.get("street"),
        props.get("housenumber"),
        props.get("neighbourhood"),
        props.get("locality"),
        props.get("region"),
        props.get("country"),
        props.get("postalcode"),
        props.get("confidence"),
        json.dumps(raw_data),
    )


async def _upsert_owntracks_status(db: Any, location_id: int, *, status: str) -> None:
    """Insert or update an OwnTracks status-only row."""
    await db.execute(
        "INSERT INTO public.geocoded_addresses (location_id, source, status) "
        "VALUES ($1, 'owntracks', $2) "
        f"{_OT_CONFLICT} DO UPDATE SET status = $2, geocoded_at = CURRENT_TIMESTAMP",
        location_id,
        status,
    )


# Back-compat alias kept for existing tests that imported _upsert_geocoded.
_upsert_geocoded = _upsert_owntracks_status


# --- Garmin persistence ----------------------------------------------------


async def _persist_garmin_from_neighbour(
    db: Any,
    track_point_id: int,
    activity_id: str,
    waypoint_kind: str,
    neighbour: dict[str, Any],
) -> None:
    await db.execute(
        "INSERT INTO public.geocoded_addresses "
        "(garmin_track_point_id, garmin_activity_id, waypoint_kind, source, "
        "display_address, street, housenumber, neighbourhood, locality, "
        "region, country, postalcode, confidence, status, raw_response) "
        "VALUES ($1, $2, $3, 'garmin', $4, $5, $6, $7, $8, $9, $10, $11, $12, 'success', $13) "
        f"{_GARMIN_CONFLICT} DO UPDATE SET "
        "garmin_activity_id = EXCLUDED.garmin_activity_id, "
        "waypoint_kind = EXCLUDED.waypoint_kind, "
        "display_address = EXCLUDED.display_address, "
        "street = EXCLUDED.street, housenumber = EXCLUDED.housenumber, "
        "neighbourhood = EXCLUDED.neighbourhood, locality = EXCLUDED.locality, "
        "region = EXCLUDED.region, country = EXCLUDED.country, "
        "postalcode = EXCLUDED.postalcode, confidence = EXCLUDED.confidence, "
        "status = EXCLUDED.status, raw_response = EXCLUDED.raw_response, "
        "geocoded_at = CURRENT_TIMESTAMP",
        track_point_id,
        activity_id,
        waypoint_kind,
        neighbour["display_address"],
        neighbour["street"],
        neighbour["housenumber"],
        neighbour["neighbourhood"],
        neighbour["locality"],
        neighbour["region"],
        neighbour["country"],
        neighbour["postalcode"],
        neighbour["confidence"],
        neighbour["raw_response"],
    )


async def _persist_garmin_from_pelias(
    db: Any,
    track_point_id: int,
    activity_id: str,
    waypoint_kind: str,
    props: dict[str, Any],
    raw_data: dict[str, Any],
) -> None:
    await db.execute(
        "INSERT INTO public.geocoded_addresses "
        "(garmin_track_point_id, garmin_activity_id, waypoint_kind, source, "
        "display_address, street, housenumber, neighbourhood, locality, "
        "region, country, postalcode, confidence, status, raw_response) "
        "VALUES ($1, $2, $3, 'garmin', $4, $5, $6, $7, $8, $9, $10, $11, $12, 'success', $13) "
        f"{_GARMIN_CONFLICT} DO UPDATE SET "
        "garmin_activity_id = EXCLUDED.garmin_activity_id, "
        "waypoint_kind = EXCLUDED.waypoint_kind, "
        "display_address = EXCLUDED.display_address, "
        "street = EXCLUDED.street, housenumber = EXCLUDED.housenumber, "
        "neighbourhood = EXCLUDED.neighbourhood, locality = EXCLUDED.locality, "
        "region = EXCLUDED.region, country = EXCLUDED.country, "
        "postalcode = EXCLUDED.postalcode, confidence = EXCLUDED.confidence, "
        "status = EXCLUDED.status, raw_response = EXCLUDED.raw_response, "
        "geocoded_at = CURRENT_TIMESTAMP",
        track_point_id,
        activity_id,
        waypoint_kind,
        props.get("label"),
        props.get("street"),
        props.get("housenumber"),
        props.get("neighbourhood"),
        props.get("locality"),
        props.get("region"),
        props.get("country"),
        props.get("postalcode"),
        props.get("confidence"),
        json.dumps(raw_data),
    )


async def _upsert_garmin_status(
    db: Any,
    track_point_id: int,
    activity_id: str,
    waypoint_kind: str,
    *,
    status: str,
) -> None:
    """Insert or update a Garmin status-only row."""
    await db.execute(
        "INSERT INTO public.geocoded_addresses "
        "(garmin_track_point_id, garmin_activity_id, waypoint_kind, source, status) "
        "VALUES ($1, $2, $3, 'garmin', $4) "
        f"{_GARMIN_CONFLICT} DO UPDATE SET "
        "garmin_activity_id = EXCLUDED.garmin_activity_id, "
        "waypoint_kind = EXCLUDED.waypoint_kind, "
        "status = EXCLUDED.status, "
        "geocoded_at = CURRENT_TIMESTAMP",
        track_point_id,
        activity_id,
        waypoint_kind,
        status,
    )
