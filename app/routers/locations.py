"""OwnTracks location endpoints."""

from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from app.models import PaginatedResponse
from app.models.locations import DeviceInfo, Location, LocationCount, LocationDetail

router = APIRouter(prefix="/api/v1/locations", tags=["Locations"])

SORT_WHITELIST = {"id", "device_id", "timestamp", "created_at", "battery", "accuracy"}


@router.get("", response_model=PaginatedResponse[Location])
async def list_locations(
    request: Request,
    device_id: str | None = None,
    date_from: str | None = Query(None, description="Filter from date (YYYY-MM-DD)"),
    date_to: str | None = Query(None, description="Filter to date (YYYY-MM-DD)"),
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    sort: str = Query("created_at", description="Sort column"),
    order: Literal["asc", "desc"] = Query("desc"),
) -> PaginatedResponse[Location]:
    """List OwnTracks locations with filtering and pagination."""
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
        params.append(date_from)
        idx += 1

    if date_to:
        conditions.append(f"created_at < (${idx}::date + INTERVAL '1 day')")
        params.append(date_to)
        idx += 1

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    count_query = f"SELECT COUNT(*) FROM public.locations {where}"
    total = await db.fetchval(count_query, *params)

    data_query = (
        f"SELECT id, device_id, tid, latitude, longitude, accuracy, altitude, "
        f"velocity, battery, battery_status, connection_type, trigger, "
        f"timestamp, created_at "
        f"FROM public.locations {where} "
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
    date: str | None = Query(None, description="Filter by date (YYYY-MM-DD)"),
    device_id: str | None = None,
) -> LocationCount:
    """Get total location count with optional filters."""
    db = request.app.state.db

    conditions: list[str] = []
    params: list = []
    idx = 1

    if date:
        conditions.append(f"DATE(created_at) = ${idx}::date")
        params.append(date)
        idx += 1

    if device_id:
        conditions.append(f"device_id = ${idx}")
        params.append(device_id)
        idx += 1

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    count = await db.fetchval(f"SELECT COUNT(*) FROM public.locations {where}", *params)
    return LocationCount(count=count, date=date, device_id=device_id)


@router.get("/{location_id}", response_model=LocationDetail)
async def get_location(request: Request, location_id: int) -> LocationDetail:
    """Get a single location by ID, including raw payload."""
    db = request.app.state.db
    row = await db.fetchrow(
        "SELECT id, device_id, tid, latitude, longitude, accuracy, altitude, "
        "velocity, battery, battery_status, connection_type, trigger, "
        "timestamp, created_at, raw_payload "
        "FROM public.locations WHERE id = $1",
        location_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Location not found")

    data = dict(row)
    # Convert raw_payload from JSON string to dict if needed
    if data.get("raw_payload") and isinstance(data["raw_payload"], str):
        data["raw_payload"] = json.loads(data["raw_payload"])
    return LocationDetail(**data)
