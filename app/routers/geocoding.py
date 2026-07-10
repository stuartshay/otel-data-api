"""Geocoding management endpoints for reverse-geocoding OwnTracks + Garmin records."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Annotated, Any

import httpx
import structlog
from fastapi import APIRouter, Depends, Query, Request

from app.auth import require_auth
from app.models.geocoding import (
    GeocodingSourceStatus,
    GeocodingStatus,
    GeocodingStatusBySource,
    GeocodingTriggerResponse,
    PeliasHealth,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/geocoding", tags=["Geocoding"])
internal_router = APIRouter(prefix="/internal/geocoding", tags=["Internal"])

PELIAS_REVERSE_PATH = "/v1/reverse"
# Per-request cap on concurrent waypoint geocoding tasks (end-to-end:
# neighbour lookup + Pelias call + upsert). Raised from 5 to 20 in #129
# so the slow Pelias retry tail no longer dominates drain wall time.
MAX_GEOCODE_CONCURRENCY = 20
# Per-request cap on concurrently processed Garmin activities. Bounds the
# fan-out so the new parallel activity loop does not spike DB connections.
GARMIN_ACTIVITY_CONCURRENCY = 4
DEFAULT_GARMIN_WAYPOINT_SPACING_KM = 1.0

# Pelias retry policy: transient failures (timeout, connection, 5xx) are retried
# with exponential backoff; if all attempts fail the caller upserts status=
# 'pending' so the retry path can pick the row up again on the next pass.
# Permanent failures (4xx) short-circuit to status='error' immediately.
PELIAS_MAX_ATTEMPTS = 3
PELIAS_BACKOFF_SECONDS = (0.2, 0.8)

# Known-good coordinate used by /pelias-health to probe upstream availability.
# Times Square, NYC — inside dense Pelias coverage; expected confidence ≥ 0.5.
PELIAS_HEALTH_PROBE_LAT = 40.7580
PELIAS_HEALTH_PROBE_LON = -73.9855

# Status values that the retry path should re-process. 'pending' was previously
# only used for OwnTracks; Garmin now also writes 'pending' on transient
# Pelias failures so they can be drained without manual intervention.
RETRY_STATUSES = ("no_coverage", "error", "pending")

_OT_CONFLICT = "ON CONFLICT (location_id) WHERE source = 'owntracks'"
_GARMIN_CONFLICT = "ON CONFLICT (garmin_track_point_id) WHERE source = 'garmin'"

# Cache TTL for the /status response. The aggregates scan large tables and change
# slowly, so caching per-process avoids re-running the heavy COUNT queries on
# every dashboard poll.
_STATUS_CACHE_TTL_SECONDS = 60.0


@dataclass
class _StatusCache:
    """Per-process cache holder for the geocoding /status response."""

    value: GeocodingStatus | None = None
    expires_at: float = 0.0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class PeliasTransientError(Exception):
    """Raised by ``_call_pelias`` after all retry attempts have failed transiently."""


@router.get("/status")
async def geocoding_status(request: Request) -> GeocodingStatus:
    """Get geocoding coverage statistics for both OwnTracks and Garmin sources.

    The underlying aggregates scan large tables (millions of garmin_track_points)
    and change slowly, so the response is cached per-process for
    ``_STATUS_CACHE_TTL_SECONDS`` to avoid repeatedly running the heavy COUNT
    queries on every dashboard poll.
    """
    cache: _StatusCache | None = getattr(request.app.state, "_geocoding_status_cache", None)
    if cache is None:
        cache = _StatusCache()
        request.app.state._geocoding_status_cache = cache

    if cache.value is not None and time.monotonic() < cache.expires_at:
        return cache.value

    async with cache.lock:
        # Re-check after acquiring the lock so only one request recomputes.
        if cache.value is not None and time.monotonic() < cache.expires_at:
            return cache.value
        status = await _compute_geocoding_status(request.app.state.db)
        cache.value = status
        cache.expires_at = time.monotonic() + _STATUS_CACHE_TTL_SECONDS
        return status


async def _compute_geocoding_status(db: Any) -> GeocodingStatus:
    """Compute geocoding coverage statistics (uncached)."""
    # Per-(source, status) counts for geocoded_addresses in a single GROUP BY
    # instead of eight separate COUNT(*) round-trips.
    addr_rows = await db.fetch(
        "SELECT source, status, COUNT(*) AS n FROM public.geocoded_addresses "
        "WHERE source IN ('owntracks', 'garmin') GROUP BY source, status"
    )
    addr: dict[tuple[str, str], int] = {(r["source"], r["status"]): r["n"] for r in addr_rows}
    ot_success = addr.get(("owntracks", "success"), 0)
    ot_pending = addr.get(("owntracks", "pending"), 0)
    ot_no_coverage = addr.get(("owntracks", "no_coverage"), 0)
    ot_errors = addr.get(("owntracks", "error"), 0)
    geocoded = sum(n for (src, _status), n in addr.items() if src == "owntracks")
    g_success = addr.get(("garmin", "success"), 0)
    g_pending = addr.get(("garmin", "pending"), 0)
    g_no_coverage = addr.get(("garmin", "no_coverage"), 0)
    g_errors = addr.get(("garmin", "error"), 0)
    g_total_rows = g_success + g_pending + g_no_coverage + g_errors

    total = await db.fetchval("SELECT COUNT(*) FROM public.locations")
    coverage_percent = round((geocoded / total * 100), 2) if total else 0.0

    activities_total = await db.fetchval("SELECT COUNT(*) FROM public.garmin_activities")
    activities_geocoded = await db.fetchval(
        "SELECT COUNT(DISTINCT garmin_activity_id) FROM public.geocoded_addresses WHERE source = 'garmin'"
    )
    garmin_coverage_percent = round((activities_geocoded / activities_total * 100), 2) if activities_total else 0.0
    garmin_waypoint_success_percent = round((g_success / g_total_rows * 100), 2) if g_total_rows else 0.0

    # Dense per-point cell coverage (geocoded_point_cells, 4dp ~ 11 m resolution).
    # Per-status counts in a single GROUP BY instead of four separate COUNT(*) calls.
    cell_rows = await db.fetch("SELECT status, COUNT(*) AS n FROM public.geocoded_point_cells GROUP BY status")
    cell: dict[str, int] = {r["status"]: r["n"] for r in cell_rows}
    dense_success = cell.get("success", 0)
    dense_pending = cell.get("pending", 0)
    dense_no_coverage = cell.get("no_coverage", 0)
    dense_errors = cell.get("error", 0)
    dense_geocoded = dense_success + dense_pending + dense_no_coverage + dense_errors

    # Derive all materialized-view metrics in a SINGLE query so dense_total_cells,
    # total and covered come from one MV snapshot. The MV (migrations 18 + 21) is
    # refreshed out-of-band, so computing these as separate statements could span a
    # refresh and briefly skew the coverage percentage. The MV carries a per-cell
    # point_count; a LEFT JOIN to geocoded_point_cells on the indexed (lat_4dp, lon_4dp)
    # key yields covered points via FILTER — replacing the old ~5.2s COUNT(*) ...
    # WHERE EXISTS(ROUND ...) Parallel Seq Scan over ~4.5M garmin_track_points rows
    # (~0.9s now). Staleness of hours is acceptable (see migration 21).
    mv_metrics = await db.fetchrow(
        "SELECT COUNT(*)::BIGINT AS dense_total_cells, "
        "COALESCE(SUM(m.point_count), 0)::BIGINT AS total_track_points, "
        "COALESCE(SUM(m.point_count) FILTER (WHERE g.lat_4dp IS NOT NULL), 0)::BIGINT "
        "AS covered_track_points "
        "FROM public.mv_garmin_track_point_cells m "
        "LEFT JOIN public.geocoded_point_cells g USING (lat_4dp, lon_4dp)"
    )
    dense_total_cells = mv_metrics["dense_total_cells"] if mv_metrics else 0
    total_track_points = mv_metrics["total_track_points"] if mv_metrics else 0
    covered_track_points = mv_metrics["covered_track_points"] if mv_metrics else 0
    dense_point_coverage_percent = (
        round((covered_track_points / total_track_points * 100), 2) if total_track_points else 0.0
    )

    # Note: every count below is already a non-null integer — dict.get() uses a
    # 0 default, COUNT(*) never returns NULL, and the mv_metrics values are
    # guarded above — so no additional ``or 0`` fallbacks are needed.
    by_source = GeocodingStatusBySource(
        owntracks=GeocodingSourceStatus(
            success=ot_success,
            pending=ot_pending,
            no_coverage=ot_no_coverage,
            errors=ot_errors,
            total=geocoded,
        ),
        garmin=GeocodingSourceStatus(
            success=g_success,
            pending=g_pending,
            no_coverage=g_no_coverage,
            errors=g_errors,
            total=g_total_rows,
        ),
        garmin_activities_total=activities_total,
        garmin_activities_geocoded=activities_geocoded,
        garmin_coverage_percent=garmin_coverage_percent,
        garmin_waypoint_success_percent=garmin_waypoint_success_percent,
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
        dense_cells_total=dense_total_cells,
        dense_cells_geocoded=dense_geocoded,
        dense_cells_success=dense_success,
        dense_cells_pending=dense_pending,
        dense_cells_no_coverage=dense_no_coverage,
        dense_cells_errors=dense_errors,
        dense_point_coverage_percent=dense_point_coverage_percent,
    )


# ---------------------------------------------------------------------------
# Pelias health probe
# ---------------------------------------------------------------------------


@router.get("/pelias-health")
async def pelias_health(request: Request) -> PeliasHealth:
    """Probe the upstream Pelias reverse-geocoder with a known-good coordinate.

    Returns 200 with ``healthy=false`` rather than failing so that callers
    (Airflow sensors, dashboards) can branch on the boolean. Used as a
    pre-flight gate before batched trigger runs to avoid recording large
    numbers of false-positive errors during a Pelias outage.
    """
    cfg = request.app.state.config
    pelias_base_url = cfg.pelias_base_url
    start = time.perf_counter()
    healthy = False
    detail: str | None = None
    features = 0
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{pelias_base_url}{PELIAS_REVERSE_PATH}",
                params={
                    "point.lat": PELIAS_HEALTH_PROBE_LAT,
                    "point.lon": PELIAS_HEALTH_PROBE_LON,
                    "size": 1,
                },
            )
        if 200 <= resp.status_code < 300:
            try:
                body = resp.json()
            except ValueError as e:
                detail = f"invalid JSON response: {e}"
            else:
                features = len(body.get("features", []))
                healthy = features > 0
                if not healthy:
                    detail = "Pelias responded but returned zero features for probe coordinate"
        else:
            detail = f"Pelias HTTP {resp.status_code}"
    except httpx.TimeoutException as e:
        detail = f"timeout: {e}"
    except httpx.HTTPError as e:
        detail = f"transport error: {e}"
    latency_ms = round((time.perf_counter() - start) * 1000, 1)
    return PeliasHealth(
        healthy=healthy,
        latency_ms=latency_ms,
        sample_features_count=features,
        detail=detail,
    )


# ---------------------------------------------------------------------------
# OwnTracks trigger
# ---------------------------------------------------------------------------


@router.post("/trigger")
async def trigger_geocoding(
    request: Request,
    _user: Annotated[dict, Depends(require_auth)],
    batch_size: Annotated[int, Query(ge=1, le=500, description="Number of locations to geocode in this batch")] = 100,
    retry_failed: Annotated[bool, Query(description="Re-process records with statuses no_coverage or error")] = False,
) -> GeocodingTriggerResponse:
    """Trigger batch reverse-geocoding of OwnTracks location records (auth required)."""
    return await _trigger_geocoding_impl(request, batch_size, retry_failed)


@internal_router.post("/trigger")
async def internal_trigger_geocoding(
    request: Request,
    batch_size: Annotated[int, Query(ge=1, le=1000, description="Number of locations to geocode in this batch")] = 100,
    retry_failed: Annotated[bool, Query(description="Re-process records with statuses no_coverage or error")] = False,
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
            "WHERE ga.source = 'owntracks' AND ga.status = ANY($2::text[]) "
            "ORDER BY l.id LIMIT $1",
            batch_size,
            list(RETRY_STATUSES),
        )
    else:
        rows = await db.fetch(
            "SELECT l.id, l.latitude, l.longitude "
            "FROM public.locations l "
            "WHERE NOT EXISTS ("
            "  SELECT 1 FROM public.geocoded_addresses ga "
            "  WHERE ga.location_id = l.id AND ga.source = 'owntracks'"
            ") "
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
        "WHERE NOT EXISTS ("
        "  SELECT 1 FROM public.geocoded_addresses ga "
        "  WHERE ga.location_id = l.id AND ga.source = 'owntracks'"
        ")"
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

    try:
        pelias_data = await _call_pelias(client, pelias_base_url, lat, lon)
    except PeliasTransientError:
        # Transport / 5xx after retries: mark pending so the retry path picks
        # it up again. Avoids burning permanent 'error' rows during outages.
        await _upsert_owntracks_status(db, location_id, status="pending")
        return 1, 0

    if pelias_data is None:
        # Permanent failure (4xx response or invalid JSON body).
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


@internal_router.post("/trigger/garmin")
async def internal_trigger_garmin_geocoding(
    request: Request,
    batch_size: Annotated[
        int,
        Query(ge=1, le=100, description="Number of Garmin activities to process in this batch"),
    ] = 10,
    waypoint_spacing_km: Annotated[
        float,
        Query(ge=0.1, le=50.0, description="Approximate spacing between mid-route waypoints in kilometres"),
    ] = DEFAULT_GARMIN_WAYPOINT_SPACING_KM,
    retry_failed: Annotated[
        bool,
        Query(description="Re-process activities with at least one waypoint in statuses no_coverage or error"),
    ] = False,
) -> GeocodingTriggerResponse:
    """Trigger batch reverse-geocoding of Garmin activity waypoints (internal, no auth).

    For each selected activity, picks the start, end, and every-``waypoint_spacing_km`` mid-route
    track point as waypoints, then reverse-geocodes each one through Pelias.
    """
    return await _trigger_garmin_geocoding_impl(request, batch_size, waypoint_spacing_km, retry_failed)


@router.post("/trigger/garmin")
async def trigger_garmin_geocoding(
    request: Request,
    _user: Annotated[dict, Depends(require_auth)],
    batch_size: Annotated[
        int,
        Query(ge=1, le=100, description="Number of Garmin activities to process in this batch"),
    ] = 10,
    waypoint_spacing_km: Annotated[
        float,
        Query(ge=0.1, le=50.0, description="Approximate spacing between mid-route waypoints in kilometres"),
    ] = DEFAULT_GARMIN_WAYPOINT_SPACING_KM,
    retry_failed: Annotated[
        bool,
        Query(description="Re-process activities with at least one waypoint in statuses no_coverage or error"),
    ] = False,
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
        # Rotate across the backlog by least-recently-attempted activity so consecutive
        # batches process distinct activities until the failure-status set is drained.
        activity_rows = await db.fetch(
            "SELECT a.activity_id "
            "FROM public.garmin_activities a "
            "INNER JOIN public.geocoded_addresses ga "
            "  ON ga.garmin_activity_id = a.activity_id AND ga.source = 'garmin' "
            "WHERE ga.status = ANY($2::text[]) "
            "GROUP BY a.activity_id "
            "ORDER BY MIN(ga.geocoded_at) ASC NULLS FIRST "
            "LIMIT $1",
            batch_size,
            list(RETRY_STATUSES),
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
    activity_sem = asyncio.Semaphore(GARMIN_ACTIVITY_CONCURRENCY)
    started_at = time.monotonic()

    async def _geocode_one(client: httpx.AsyncClient, waypoint: dict[str, Any]) -> tuple[int, int]:
        async with sem:
            return await _process_garmin_waypoint(db, client, pelias_base_url, waypoint)

    async def _process_activity(client: httpx.AsyncClient, activity_id: str) -> tuple[int, int]:
        async with activity_sem:
            if retry_failed:
                # Single-query selector: returns ONLY rows already flagged for retry.
                # Avoids the full-track scan + Python-side thinning + second status
                # query that the fresh-pass path needs.
                waypoints = await _select_garmin_retry_waypoints(db, activity_id)
            else:
                waypoints = await _select_garmin_waypoints(db, activity_id, waypoint_spacing_km)
            wp_results = await asyncio.gather(*[_geocode_one(client, wp) for wp in waypoints])
            return (
                sum(proc for proc, _ in wp_results),
                sum(skip for _, skip in wp_results),
            )

    async with httpx.AsyncClient(timeout=pelias_timeout) as client:
        activity_results = await asyncio.gather(*[_process_activity(client, a["activity_id"]) for a in activity_rows])
    for proc, skip in activity_results:
        processed += proc
        skipped_dedup += skip

    logger.info(
        "garmin_geocoding_batch_complete",
        retry_failed=retry_failed,
        activities=len(activity_rows),
        processed=processed,
        skipped_dedup=skipped_dedup,
        elapsed_seconds=round(time.monotonic() - started_at, 2),
    )

    if retry_failed:
        remaining = await db.fetchval(
            "SELECT COUNT(DISTINCT ga.garmin_activity_id) "
            "FROM public.geocoded_addresses ga "
            "WHERE ga.source = 'garmin' "
            "AND ga.status = ANY($1::text[])",
            list(RETRY_STATUSES),
        )
    else:
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


async def _select_garmin_retry_waypoints(
    db: Any,
    activity_id: str,
) -> list[dict[str, Any]]:
    """Return only the waypoints that already need a retry — in one SQL query.

    The fresh-pass path uses ``_select_garmin_waypoints`` which pulls every
    track point for the activity (often 5k-20k rows) and thins them to ~1 km
    in Python, then re-queries status to filter to retryable rows. For an
    activity with 3 failed waypoints that's >99% wasted I/O.
    """
    rows = await db.fetch(
        "SELECT gtp.id, gtp.latitude, gtp.longitude, ga.waypoint_kind "
        "FROM public.geocoded_addresses ga "
        "INNER JOIN public.garmin_track_points gtp "
        "  ON gtp.id = ga.garmin_track_point_id "
        "WHERE ga.source = 'garmin' "
        "AND ga.garmin_activity_id = $1 "
        "AND ga.status = ANY($2::text[]) "
        "ORDER BY ga.geocoded_at ASC NULLS FIRST",
        activity_id,
        list(RETRY_STATUSES),
    )
    return [
        {
            "id": r["id"],
            "latitude": r["latitude"],
            "longitude": r["longitude"],
            "waypoint_kind": r["waypoint_kind"] or "waypoint",
            "activity_id": activity_id,
        }
        for r in rows
    ]


async def _select_garmin_waypoints(
    db: Any,
    activity_id: str,
    spacing_km: float,
    *,
    retry_failed: bool = False,
) -> list[dict[str, Any]]:
    """Pick start, end, and every-``spacing_km`` mid-route waypoints from an activity's track.

    When ``retry_failed`` is True, the returned list is filtered to only waypoints whose
    current ``geocoded_addresses`` row has a retryable status (see ``RETRY_STATUSES`` —
    currently ``no_coverage``, ``error``, and ``pending``). Waypoints with status
    ``success`` are skipped so transient Pelias failures cannot demote them, and
    waypoints with no existing row are skipped because they belong to the fresh-pass path.
    """
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

    if retry_failed and waypoints:
        track_point_ids = [wp["id"] for wp in waypoints]
        status_rows = await db.fetch(
            "SELECT garmin_track_point_id, status "
            "FROM public.geocoded_addresses "
            "WHERE source = 'garmin' AND garmin_track_point_id = ANY($1::bigint[])",
            track_point_ids,
        )
        retryable = {r["garmin_track_point_id"] for r in status_rows if r["status"] in RETRY_STATUSES}
        waypoints = [wp for wp in waypoints if wp["id"] in retryable]

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

    try:
        pelias_data = await _call_pelias(client, pelias_base_url, lat, lon)
    except PeliasTransientError:
        # Transport / 5xx after retries: mark pending so the next retry pass
        # picks this waypoint up. Prevents a Pelias outage from being recorded
        # as a permanent 'error' that requires manual intervention.
        await _upsert_garmin_status(db, track_point_id, activity_id, waypoint_kind, status="pending")
        return 1, 0

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


_NEARBY_RADIUS_METRES = 50
_NEARBY_CANDIDATE_LIMIT = 5


async def _find_nearby_address(db: Any, lat: float, lon: float) -> dict[str, Any] | None:
    """Return the nearest successfully geocoded address within 50 m, or None.

    Implemented as two GIST-indexed candidate lookups (locations + garmin
    track points; #132) followed by a per-source lookup in
    ``geocoded_addresses`` via the existing unique partial btree indexes. A
    combined ``COALESCE``/OR query forced a sequential scan over all success
    rows, so each source is now queried independently; see #165.
    """
    ow_candidates = await db.fetch(
        "SELECT id "
        "FROM public.locations "
        "WHERE ST_DWithin(geog, ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography, $3) "
        "ORDER BY geog <-> ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography "
        "LIMIT $4",
        lon,
        lat,
        _NEARBY_RADIUS_METRES,
        _NEARBY_CANDIDATE_LIMIT,
    )
    gt_candidates = await db.fetch(
        "SELECT id "
        "FROM public.garmin_track_points "
        "WHERE ST_DWithin(geog, ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography, $3) "
        "ORDER BY geog <-> ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography "
        "LIMIT $4",
        lon,
        lat,
        _NEARBY_RADIUS_METRES,
        _NEARBY_CANDIDATE_LIMIT,
    )

    ow_ids = [row["id"] for row in ow_candidates]
    gt_ids = [row["id"] for row in gt_candidates]
    if not ow_ids and not gt_ids:
        return None

    # Look up the geocoded address for each source independently. A single
    # OR-across-columns LEFT JOIN forced a sequential scan over all 'success'
    # rows in geocoded_addresses (NR slow-query analysis: avg ~1.8 s, max
    # ~13 s). Splitting by source lets the planner use the partial unique
    # indexes (location_id WHERE source='owntracks' / garmin_track_point_id
    # WHERE source='garmin'); each side then sorts the bounded candidate set
    # by true distance and returns its nearest neighbour. See #165.
    _ADDRESS_COLS = (
        "ga.display_address, ga.street, ga.housenumber, ga.neighbourhood, "
        "ga.locality, ga.region, ga.country, ga.postalcode, ga.confidence, "
        "ga.raw_response"
    )
    _POINT = "ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography"
    candidates: list[Any] = []

    if ow_ids:
        ow_match = await db.fetchrow(
            f"SELECT {_ADDRESS_COLS}, ST_Distance(l.geog, {_POINT}) AS _dist "
            "FROM public.geocoded_addresses ga "
            "JOIN public.locations l ON l.id = ga.location_id "
            "WHERE ga.source = 'owntracks' AND ga.status = 'success' "
            "AND ga.location_id = ANY($3::bigint[]) "
            "ORDER BY _dist ASC LIMIT 1",
            lon,
            lat,
            ow_ids,
        )
        if ow_match:
            candidates.append(ow_match)

    if gt_ids:
        gt_match = await db.fetchrow(
            f"SELECT {_ADDRESS_COLS}, ST_Distance(gtp.geog, {_POINT}) AS _dist "
            "FROM public.geocoded_addresses ga "
            "JOIN public.garmin_track_points gtp ON gtp.id = ga.garmin_track_point_id "
            "WHERE ga.source = 'garmin' AND ga.status = 'success' "
            "AND ga.garmin_track_point_id = ANY($3::bigint[]) "
            "ORDER BY _dist ASC LIMIT 1",
            lon,
            lat,
            gt_ids,
        )
        if gt_match:
            candidates.append(gt_match)

    if not candidates:
        return None

    nearest = min(
        candidates,
        key=lambda r: r["_dist"] if r["_dist"] is not None else float("inf"),
    )
    return {key: value for key, value in dict(nearest).items() if key != "_dist"}


def _interpret_pelias_response(resp: httpx.Response) -> dict[str, Any] | None:
    """Interpret a single Pelias HTTP response.

    Returns the parsed JSON dict on a 2xx success, or ``None`` on a permanent
    failure (invalid JSON body on a 2xx, or a 4xx client error). Raises
    ``httpx.HTTPStatusError`` for 5xx (and any other non-2xx/4xx) responses so
    the caller treats them as transient and retries.
    """
    status_code = resp.status_code
    if 200 <= status_code < 300:
        try:
            data: dict[str, Any] = resp.json()
            return data
        except ValueError:
            logger.warning("Pelias returned non-JSON body", exc_info=True)
            # Treat invalid JSON on 2xx as permanent—no point retrying.
            return None
    if 400 <= status_code < 500:
        logger.warning(
            "Pelias permanent client error",
            status_code=status_code,
            body_preview=resp.text[:200],
        )
        return None
    # 5xx and anything else (e.g. 1xx/3xx) — treat as transient.
    raise httpx.HTTPStatusError(f"Pelias status {status_code}", request=resp.request, response=resp)


async def _call_pelias(
    client: httpx.AsyncClient,
    pelias_base_url: str,
    lat: float,
    lon: float,
) -> dict[str, Any] | None:
    """Call Pelias reverse-geocoder with retry/backoff.

    Returns:
        Parsed JSON dict on success, or ``None`` on a permanent failure (4xx
        response, malformed JSON).

    Raises:
        PeliasTransientError: after ``PELIAS_MAX_ATTEMPTS`` attempts have all
            failed with a transient condition (timeout, transport error, 5xx).
            Callers should upsert ``status='pending'`` so the retry path will
            pick the row up again.
    """
    last_err: Exception | None = None
    for attempt in range(PELIAS_MAX_ATTEMPTS):
        try:
            resp = await client.get(
                f"{pelias_base_url}{PELIAS_REVERSE_PATH}",
                params={"point.lat": lat, "point.lon": lon, "size": 1},
            )
            # Permanent outcomes (2xx success/invalid-JSON, 4xx) return directly;
            # transient outcomes (5xx/other) raise HTTPStatusError, handled below.
            return _interpret_pelias_response(resp)
        except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as e:
            last_err = e
            logger.warning(
                "Pelias request failed (attempt %d/%d)",
                attempt + 1,
                PELIAS_MAX_ATTEMPTS,
                exc_info=True,
            )

        if attempt < PELIAS_MAX_ATTEMPTS - 1:
            await asyncio.sleep(PELIAS_BACKOFF_SECONDS[attempt])

    logger.warning(
        "Pelias unavailable after %d attempts; marking row pending",
        PELIAS_MAX_ATTEMPTS,
    )
    raise PeliasTransientError(f"Pelias unavailable after {PELIAS_MAX_ATTEMPTS} attempts") from last_err


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


# ---------------------------------------------------------------------------
# Dense per-point cell geocoding (geocoded_point_cells, 4dp ~ 11 m resolution)
# ---------------------------------------------------------------------------


_CELL_CONFLICT = "ON CONFLICT (lat_4dp, lon_4dp)"


@internal_router.post("/trigger/garmin-dense")
async def internal_trigger_garmin_dense(
    request: Request,
    batch_size: Annotated[
        int, Query(ge=1, le=1000, description="Number of dense cells to process in this batch")
    ] = 100,
    retry_failed: Annotated[
        bool,
        Query(description="Re-process cells whose status is no_coverage, error, or pending"),
    ] = False,
) -> GeocodingTriggerResponse:
    """Trigger batch reverse-geocoding of distinct 4dp GPS cells (internal, no auth)."""
    return await _trigger_garmin_dense_impl(request, batch_size, retry_failed)


@router.post("/trigger/garmin-dense")
async def trigger_garmin_dense(
    request: Request,
    _user: Annotated[dict, Depends(require_auth)],
    batch_size: Annotated[int, Query(ge=1, le=500, description="Number of dense cells to process in this batch")] = 100,
    retry_failed: Annotated[
        bool,
        Query(description="Re-process cells whose status is no_coverage, error, or pending"),
    ] = False,
) -> GeocodingTriggerResponse:
    """Trigger batch reverse-geocoding of distinct 4dp GPS cells (auth required)."""
    return await _trigger_garmin_dense_impl(request, batch_size, retry_failed)


async def _trigger_garmin_dense_impl(
    request: Request,
    batch_size: int,
    retry_failed: bool,
) -> GeocodingTriggerResponse:
    db = request.app.state.db
    config = request.app.state.config
    pelias_base_url = config.pelias_base_url
    pelias_timeout = config.pelias_timeout_seconds

    if retry_failed:
        cell_rows = await db.fetch(
            "SELECT lat_4dp, lon_4dp FROM public.geocoded_point_cells "
            "WHERE status = ANY($2::text[]) "
            "ORDER BY geocoded_at ASC NULLS FIRST "
            "LIMIT $1",
            batch_size,
            list(RETRY_STATUSES),
        )
    else:
        # Distinct cells observed in garmin_track_points that have no row yet
        # in geocoded_point_cells. Indexed equality on (lat_4dp, lon_4dp).
        cell_rows = await db.fetch(
            "SELECT DISTINCT "
            "  ROUND(gtp.latitude * 10000)::INTEGER AS lat_4dp, "
            "  ROUND(gtp.longitude * 10000)::INTEGER AS lon_4dp "
            "FROM public.garmin_track_points gtp "
            "WHERE NOT EXISTS ("
            "  SELECT 1 FROM public.geocoded_point_cells gpc "
            "  WHERE gpc.lat_4dp = ROUND(gtp.latitude * 10000)::INTEGER "
            "    AND gpc.lon_4dp = ROUND(gtp.longitude * 10000)::INTEGER"
            ") "
            "LIMIT $1",
            batch_size,
        )

    processed = 0
    sem = asyncio.Semaphore(MAX_GEOCODE_CONCURRENCY)

    async def _process_one(client: httpx.AsyncClient, lat_4dp: int, lon_4dp: int) -> int:
        async with sem:
            return await _process_cell(db, client, pelias_base_url, lat_4dp, lon_4dp)

    if cell_rows:
        async with httpx.AsyncClient(timeout=pelias_timeout) as client:
            results = await asyncio.gather(*[_process_one(client, row["lat_4dp"], row["lon_4dp"]) for row in cell_rows])
            processed = sum(results)

    # Remaining work. In retry mode, count cells still in a retryable status;
    # otherwise count distinct track-point cells that have no row yet.
    if retry_failed:
        remaining = await db.fetchval(
            "SELECT COUNT(*) FROM public.geocoded_point_cells WHERE status = ANY($1::text[])",
            list(RETRY_STATUSES),
        )
    else:
        remaining = await db.fetchval(
            "SELECT COUNT(*) FROM ("
            "  SELECT DISTINCT "
            "    ROUND(gtp.latitude * 10000)::INTEGER AS lat_4dp, "
            "    ROUND(gtp.longitude * 10000)::INTEGER AS lon_4dp "
            "  FROM public.garmin_track_points gtp "
            "  WHERE NOT EXISTS ("
            "    SELECT 1 FROM public.geocoded_point_cells gpc "
            "    WHERE gpc.lat_4dp = ROUND(gtp.latitude * 10000)::INTEGER "
            "      AND gpc.lon_4dp = ROUND(gtp.longitude * 10000)::INTEGER"
            "  )"
            ") AS pending_cells"
        )

    return GeocodingTriggerResponse(
        processed=processed,
        remaining=remaining or 0,
        skipped_dedup=0,
    )


async def _process_cell(
    db: Any,
    client: httpx.AsyncClient,
    pelias_base_url: str,
    lat_4dp: int,
    lon_4dp: int,
) -> int:
    """Reverse-geocode a single 4dp cell and upsert the result.

    Returns 1 if a row was upserted (success/no_coverage/error/pending), 0 if
    the cell was skipped due to an unexpected exception (already logged).
    """
    lat = lat_4dp / 10000.0
    lon = lon_4dp / 10000.0
    try:
        try:
            pelias_data = await _call_pelias(client, pelias_base_url, lat, lon)
        except PeliasTransientError:
            await _upsert_cell_status(db, lat_4dp, lon_4dp, status="pending")
            return 1

        if pelias_data is None:
            await _upsert_cell_status(db, lat_4dp, lon_4dp, status="error")
            return 1

        features = pelias_data.get("features", [])
        if not features:
            await _upsert_cell_status(db, lat_4dp, lon_4dp, status="no_coverage")
            return 1

        props = features[0].get("properties", {})
        await _upsert_cell_from_pelias(db, lat_4dp, lon_4dp, props, pelias_data)
        return 1
    except Exception:
        logger.warning(
            "Unexpected error processing dense cell (%d, %d)",
            lat_4dp,
            lon_4dp,
            exc_info=True,
        )
        try:
            await _upsert_cell_status(db, lat_4dp, lon_4dp, status="error")
            return 1
        except Exception:
            logger.warning("Failed to upsert error status for cell (%d, %d)", lat_4dp, lon_4dp, exc_info=True)
            return 0


async def _upsert_cell_from_pelias(
    db: Any,
    lat_4dp: int,
    lon_4dp: int,
    props: dict[str, Any],
    raw_data: dict[str, Any],
) -> None:
    await db.execute(
        "INSERT INTO public.geocoded_point_cells "
        "(lat_4dp, lon_4dp, display_address, street, housenumber, neighbourhood, "
        "locality, region, country, postalcode, confidence, status, raw_response) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, 'success', $12) "
        f"{_CELL_CONFLICT} DO UPDATE SET "
        "display_address = EXCLUDED.display_address, "
        "street = EXCLUDED.street, housenumber = EXCLUDED.housenumber, "
        "neighbourhood = EXCLUDED.neighbourhood, locality = EXCLUDED.locality, "
        "region = EXCLUDED.region, country = EXCLUDED.country, "
        "postalcode = EXCLUDED.postalcode, confidence = EXCLUDED.confidence, "
        "status = EXCLUDED.status, raw_response = EXCLUDED.raw_response, "
        "geocoded_at = CURRENT_TIMESTAMP",
        lat_4dp,
        lon_4dp,
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


async def _upsert_cell_status(db: Any, lat_4dp: int, lon_4dp: int, *, status: str) -> None:
    """Insert or update a status-only row in geocoded_point_cells."""
    await db.execute(
        "INSERT INTO public.geocoded_point_cells (lat_4dp, lon_4dp, status) "
        "VALUES ($1, $2, $3) "
        f"{_CELL_CONFLICT} DO UPDATE SET status = $3, geocoded_at = CURRENT_TIMESTAMP",
        lat_4dp,
        lon_4dp,
        status,
    )
