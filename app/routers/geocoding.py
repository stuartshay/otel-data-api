"""Geocoding management endpoints for reverse-geocoding OwnTracks locations."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Query, Request

from app.auth import require_auth
from app.models.geocoding import GeocodingStatus, GeocodingTriggerResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/geocoding", tags=["Geocoding"])

PELIAS_BASE_URL = "http://geocoder.lab.informationcart.com"
PELIAS_REVERSE_PATH = "/v1/reverse"


@router.get("/status", response_model=GeocodingStatus)
async def geocoding_status(request: Request) -> GeocodingStatus:
    """Get geocoding coverage statistics."""
    db = request.app.state.db

    total = await db.fetchval("SELECT COUNT(*) FROM public.locations")
    geocoded = await db.fetchval("SELECT COUNT(*) FROM public.geocoded_addresses")
    success = await db.fetchval("SELECT COUNT(*) FROM public.geocoded_addresses WHERE status = 'success'")
    pending = await db.fetchval("SELECT COUNT(*) FROM public.geocoded_addresses WHERE status = 'pending'")
    no_coverage = await db.fetchval("SELECT COUNT(*) FROM public.geocoded_addresses WHERE status = 'no_coverage'")
    errors = await db.fetchval("SELECT COUNT(*) FROM public.geocoded_addresses WHERE status = 'error'")
    coverage_percent = round((geocoded / total * 100), 2) if total > 0 else 0.0

    return GeocodingStatus(
        total_locations=total,
        geocoded=geocoded,
        success=success,
        pending=pending,
        no_coverage=no_coverage,
        errors=errors,
        coverage_percent=coverage_percent,
    )


@router.post("/trigger", response_model=GeocodingTriggerResponse)
async def trigger_geocoding(
    request: Request,
    batch_size: int = Query(100, ge=1, le=1000, description="Number of locations to geocode in this batch"),
    retry_failed: bool = Query(False, description="Re-process records with status no_coverage"),
    _user: dict = Depends(require_auth),
) -> GeocodingTriggerResponse:
    """Trigger batch reverse-geocoding of un-geocoded location records (auth required).

    Fetches the next batch of locations without a geocoded address and calls
    the Pelias reverse-geocoder for each one.  Duplicate nearby coordinates
    (within 50 m) that already have a geocoded address are skipped.
    """
    db = request.app.state.db

    if retry_failed:
        rows = await db.fetch(
            "SELECT l.id, l.latitude, l.longitude "
            "FROM public.locations l "
            "INNER JOIN public.geocoded_addresses ga ON ga.location_id = l.id "
            "WHERE ga.status = 'no_coverage' "
            "ORDER BY l.id LIMIT $1",
            batch_size,
        )
    else:
        rows = await db.fetch(
            "SELECT l.id, l.latitude, l.longitude "
            "FROM public.locations l "
            "LEFT JOIN public.geocoded_addresses ga ON ga.location_id = l.id "
            "WHERE ga.id IS NULL "
            "ORDER BY l.id LIMIT $1",
            batch_size,
        )

    processed = 0
    skipped_dedup = 0

    async with httpx.AsyncClient(timeout=10.0) as client:
        for row in rows:
            location_id = row["id"]
            lat = row["latitude"]
            lon = row["longitude"]

            # Proximity dedup: skip if a nearby location (within 50m) is already geocoded
            nearby = await db.fetchval(
                "SELECT COUNT(*) FROM public.geocoded_addresses ga "
                "INNER JOIN public.locations l ON l.id = ga.location_id "
                "WHERE ga.status = 'success' "
                "AND ST_DWithin("
                "  ST_SetSRID(ST_MakePoint(l.longitude, l.latitude), 4326)::geography, "
                "  ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography, "
                "  50"
                ")",
                lon,
                lat,
            )

            if nearby and nearby > 0:
                # Copy address from nearest geocoded neighbour
                neighbour = await db.fetchrow(
                    "SELECT ga.display_address, ga.street, ga.housenumber, ga.neighbourhood, "
                    "ga.locality, ga.region, ga.country, ga.postalcode, ga.confidence, "
                    "ga.raw_response "
                    "FROM public.geocoded_addresses ga "
                    "INNER JOIN public.locations l ON l.id = ga.location_id "
                    "WHERE ga.status = 'success' "
                    "AND ST_DWithin("
                    "  ST_SetSRID(ST_MakePoint(l.longitude, l.latitude), 4326)::geography, "
                    "  ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography, "
                    "  50"
                    ") "
                    "ORDER BY ST_Distance("
                    "  ST_SetSRID(ST_MakePoint(l.longitude, l.latitude), 4326)::geography, "
                    "  ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography"
                    ") LIMIT 1",
                    lon,
                    lat,
                )
                if neighbour:
                    n = dict(neighbour)
                    await db.execute(
                        "INSERT INTO public.geocoded_addresses "
                        "(location_id, source, display_address, street, housenumber, "
                        "neighbourhood, locality, region, country, postalcode, "
                        "confidence, status, raw_response) "
                        "VALUES ($1, 'owntracks', $2, $3, $4, $5, $6, $7, $8, $9, $10, 'success', $11) "
                        "ON CONFLICT (location_id) DO UPDATE SET "
                        "display_address = EXCLUDED.display_address, "
                        "street = EXCLUDED.street, housenumber = EXCLUDED.housenumber, "
                        "neighbourhood = EXCLUDED.neighbourhood, locality = EXCLUDED.locality, "
                        "region = EXCLUDED.region, country = EXCLUDED.country, "
                        "postalcode = EXCLUDED.postalcode, confidence = EXCLUDED.confidence, "
                        "status = EXCLUDED.status, raw_response = EXCLUDED.raw_response, "
                        "geocoded_at = CURRENT_TIMESTAMP",
                        location_id,
                        n["display_address"],
                        n["street"],
                        n["housenumber"],
                        n["neighbourhood"],
                        n["locality"],
                        n["region"],
                        n["country"],
                        n["postalcode"],
                        n["confidence"],
                        n["raw_response"],
                    )
                    skipped_dedup += 1
                    continue

            # Call Pelias reverse geocoder
            try:
                resp = await client.get(
                    f"{PELIAS_BASE_URL}{PELIAS_REVERSE_PATH}",
                    params={"point.lat": lat, "point.lon": lon, "size": 1},
                )
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPError:
                logger.warning("Pelias request failed for location %d", location_id, exc_info=True)
                await _upsert_geocoded(db, location_id, status="error")
                processed += 1
                continue

            features = data.get("features", [])
            if not features:
                await _upsert_geocoded(db, location_id, status="no_coverage")
                processed += 1
                continue

            props = features[0].get("properties", {})
            await db.execute(
                "INSERT INTO public.geocoded_addresses "
                "(location_id, source, display_address, street, housenumber, "
                "neighbourhood, locality, region, country, postalcode, "
                "confidence, status, raw_response) "
                "VALUES ($1, 'owntracks', $2, $3, $4, $5, $6, $7, $8, $9, $10, 'success', $11) "
                "ON CONFLICT (location_id) DO UPDATE SET "
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
                data,
            )
            processed += 1

    remaining = await db.fetchval(
        "SELECT COUNT(*) FROM public.locations l "
        "LEFT JOIN public.geocoded_addresses ga ON ga.location_id = l.id "
        "WHERE ga.id IS NULL"
    )

    return GeocodingTriggerResponse(processed=processed, remaining=remaining, skipped_dedup=skipped_dedup)


async def _upsert_geocoded(db: Any, location_id: int, *, status: str) -> None:
    """Insert or update a geocoded_addresses row with only a status (no address data)."""
    await db.execute(
        "INSERT INTO public.geocoded_addresses (location_id, source, status) "
        "VALUES ($1, 'owntracks', $2) "
        "ON CONFLICT (location_id) DO UPDATE SET status = $2, geocoded_at = CURRENT_TIMESTAMP",
        location_id,
        status,
    )
