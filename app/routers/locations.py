"""OwnTracks location endpoints."""

from __future__ import annotations

import json
from datetime import date
from typing import Literal

import fastapi
from fastapi import APIRouter, HTTPException, Query, Request

from app.models import PaginatedResponse
from app.models.geocoding import GeocodedAddress
from app.models.locations import DeviceInfo, Location, LocationCount, LocationDetail

router = APIRouter(prefix="/api/v1/locations", tags=["Locations"])

SORT_WHITELIST = {"id", "device_id", "timestamp", "created_at", "battery", "accuracy"}


def _parse_date(value: str) -> date:
    """Parse a YYYY-MM-DD string to a datetime.date object for asyncpg."""
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid date format: {value!r}. Expected YYYY-MM-DD.") from None


@router.get("", response_model=PaginatedResponse[Location])
async def list_locations(
    request: Request,
    device_id: str | None = Query(None, description="Filter by device ID", examples=["iphone_stuart"]),
    date_from: str | None = Query(None, description="Filter from date (YYYY-MM-DD)", examples=["2026-02-01"]),
    date_to: str | None = Query(None, description="Filter to date (YYYY-MM-DD)", examples=["2026-02-12"]),
    limit: int = Query(50, ge=1, le=1000, description="Maximum number of locations to return per page"),
    offset: int = Query(0, ge=0, description="Number of locations to skip for pagination"),
    sort: str = Query(
        "created_at",
        description="Sort column (id, device_id, timestamp, created_at, battery, accuracy)",
    ),
    order: Literal["asc", "desc"] = Query(
        "desc", description="Sort direction: asc (oldest first) or desc (newest first)"
    ),
) -> PaginatedResponse[Location]:
    """List OwnTracks locations with filtering and pagination.

    Returns paginated GPS location data recorded by OwnTracks mobile app.
    Filter by device ID and date range. Includes battery, accuracy, and connection metadata.
    """
    db = request.app.state.db

    if sort not in SORT_WHITELIST:
        sort = "created_at"

    conditions: list[str] = []
    params: list = []
    idx = 1

    if device_id:
        conditions.append(f"device_id = ${idx}")
        params.append(device_id)
        idx += 1

    if date_from:
        conditions.append(f"created_at >= ${idx}::date")
        params.append(_parse_date(date_from))
        idx += 1

    if date_to:
        conditions.append(f"created_at < (${idx}::date + INTERVAL '1 day')")
        params.append(_parse_date(date_to))
        idx += 1

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    count_query = f"SELECT COUNT(*) FROM public.locations {where}"
    total = await db.fetchval(count_query, *params)

    data_query = (
        f"SELECT l.id, l.device_id, l.tid, l.latitude, l.longitude, l.accuracy, l.altitude, "
        f"l.velocity, l.battery, l.battery_status, l.connection_type, l.trigger, "
        f"l.timestamp, l.created_at, "
        f"ga.display_address "
        f"FROM public.locations l "
        f"LEFT JOIN public.geocoded_addresses ga ON ga.location_id = l.id "
        f"{where} "
        f"ORDER BY {sort} {order} "
        f"LIMIT ${idx} OFFSET ${idx + 1}"
    )
    params.extend([limit, offset])
    rows = await db.fetch(data_query, *params)

    items = [Location(**dict(row)) for row in rows]
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/devices", response_model=list[DeviceInfo])
async def list_devices(request: Request) -> list[DeviceInfo]:
    """List all distinct device IDs."""
    db = request.app.state.db
    rows = await db.fetch("SELECT DISTINCT device_id FROM public.locations ORDER BY device_id")
    return [DeviceInfo(device_id=row["device_id"]) for row in rows]


@router.get("/count", response_model=LocationCount)
async def location_count(
    request: Request,
    date: str | None = Query(None, description="Filter by date (YYYY-MM-DD)", examples=["2026-02-12"]),
    device_id: str | None = Query(None, description="Filter by device ID", examples=["iphone_stuart"]),
) -> LocationCount:
    """Get total location count with optional filters."""
    db = request.app.state.db

    conditions: list[str] = []
    params: list = []
    idx = 1

    if date:
        conditions.append(f"DATE(created_at) = ${idx}::date")
        params.append(_parse_date(date))
        idx += 1

    if device_id:
        conditions.append(f"device_id = ${idx}")
        params.append(device_id)
        idx += 1

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    count = await db.fetchval(f"SELECT COUNT(*) FROM public.locations {where}", *params)
    return LocationCount(count=count, date=date, device_id=device_id)


@router.get("/{location_id}", response_model=LocationDetail)
async def get_location(
    request: Request,
    location_id: int = fastapi.Path(description="Unique location record ID"),
) -> LocationDetail:
    """Get a single location by ID, including raw payload."""
    db = request.app.state.db
    row = await db.fetchrow(
        "SELECT l.id, l.device_id, l.tid, l.latitude, l.longitude, l.accuracy, l.altitude, "
        "l.velocity, l.battery, l.battery_status, l.connection_type, l.trigger, "
        "l.timestamp, l.created_at, l.raw_payload, "
        "ga.display_address AS ga_display_address, ga.street AS ga_street, "
        "ga.housenumber AS ga_housenumber, ga.neighbourhood AS ga_neighbourhood, "
        "ga.locality AS ga_locality, ga.region AS ga_region, ga.country AS ga_country, "
        "ga.postalcode AS ga_postalcode, ga.confidence AS ga_confidence, "
        "ga.status AS ga_status, ga.geocoded_at AS ga_geocoded_at "
        "FROM public.locations l "
        "LEFT JOIN public.geocoded_addresses ga ON ga.location_id = l.id "
        "WHERE l.id = $1",
        location_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Location not found")

    data = dict(row)
    # Convert raw_payload from JSON string to dict if needed
    if data.get("raw_payload") and isinstance(data["raw_payload"], str):
        data["raw_payload"] = json.loads(data["raw_payload"])

    # Build address object from joined columns
    address = None
    if data.get("ga_status"):
        address = GeocodedAddress(
            display_address=data["ga_display_address"],
            street=data["ga_street"],
            housenumber=data["ga_housenumber"],
            neighbourhood=data["ga_neighbourhood"],
            locality=data["ga_locality"],
            region=data["ga_region"],
            country=data["ga_country"],
            postalcode=data["ga_postalcode"],
            confidence=data["ga_confidence"],
            status=data["ga_status"],
            geocoded_at=data["ga_geocoded_at"],
        )

    # Remove ga_ prefixed keys before constructing LocationDetail
    location_data = {k: v for k, v in data.items() if not k.startswith("ga_")}
    location_data["display_address"] = data.get("ga_display_address")
    return LocationDetail(**location_data, address=address)
