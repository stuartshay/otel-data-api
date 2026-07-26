"""OwnTracks location endpoints."""

from __future__ import annotations

import json
from datetime import date
from typing import Annotated, Literal

import fastapi
from fastapi import APIRouter, HTTPException, Query, Request

from app.models import PaginatedResponse
from app.models.geocoding import GeocodedAddress
from app.models.locations import DeviceInfo, Location, LocationCount, LocationDateRange, LocationDetail

router = APIRouter(prefix="/api/v1/locations", tags=["Locations"])

SORT_WHITELIST = {"id", "device_id", "timestamp", "created_at", "battery", "accuracy"}

_SORT_COLUMN_MAP: dict[str, str] = {
    "id": "l.id",
    "device_id": "l.device_id",
    "timestamp": "l.timestamp",
    "created_at": "l.created_at",
    "battery": "l.battery",
    "accuracy": "l.accuracy",
}


def _parse_date(value: str) -> date:
    """Parse a YYYY-MM-DD string to a datetime.date object for asyncpg."""
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid date format: {value!r}. Expected YYYY-MM-DD.") from None


@router.get(
    "",
    responses={422: {"description": "Invalid date format"}},
)
async def list_locations(
    request: Request,
    device_id: Annotated[str | None, Query(description="Filter by device ID", examples=["iphone_stuart"])] = None,
    date_from: Annotated[
        str | None,
        Query(description="Filter from date (YYYY-MM-DD)", examples=["2026-02-01"]),
    ] = None,
    date_to: Annotated[
        str | None,
        Query(description="Filter to date (YYYY-MM-DD)", examples=["2026-02-12"]),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=1000, description="Maximum number of locations to return per page")] = 50,
    offset: Annotated[int, Query(ge=0, description="Number of locations to skip for pagination")] = 0,
    sort: Annotated[
        str,
        Query(description="Sort column (id, device_id, timestamp, created_at, battery, accuracy)"),
    ] = "created_at",
    order: Annotated[
        Literal["asc", "desc"],
        Query(description="Sort direction: asc (oldest first) or desc (newest first)"),
    ] = "desc",
) -> PaginatedResponse[Location]:
    """List OwnTracks locations with filtering and pagination.

    Returns paginated GPS location data recorded by OwnTracks mobile app.
    Filter by device ID and date range. Includes battery, accuracy, and connection metadata.
    """
    db = request.app.state.db

    if sort not in SORT_WHITELIST:
        sort = "created_at"

    qualified_sort = _SORT_COLUMN_MAP[sort]

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

    # `page` selects and limits locations alone (index-driven top-N via
    # idx_locations_created_at etc.) *before* joining geocoded_addresses --
    # joining first and limiting after made the planner Seq Scan + hash-join
    # the entire ~350k-row geocoded_addresses table merely to sort and throw
    # away all but `limit` rows (2.4s at offset=0 in production). MATERIALIZED
    # keeps Postgres from flattening the CTE back into that same bad plan.
    # The join also needs an explicit `ga.source = 'owntracks'` -- true for
    # every row with a non-null location_id per the table's CHECK constraint,
    # but stating it lets the planner use the existing partial unique index
    # (uniq_geocoded_addresses_owntracks_location) instead of a full scan.
    # `sort` (not qualified_sort) for the outer ORDER BY: it's already
    # whitelist-validated above and names exactly the column `page` selects,
    # so it doesn't depend on _SORT_COLUMN_MAP's values staying simple
    # "l.<column>" strings the way string-stripping qualified_sort would.
    data_query = (
        f"WITH page AS MATERIALIZED ("
        f"  SELECT l.id, l.device_id, l.tid, l.latitude, l.longitude, l.accuracy, l.altitude, "
        f"  l.velocity, l.battery, l.battery_status, l.connection_type, l.trigger, "
        f"  l.timestamp, l.created_at "
        f"  FROM public.locations l "
        f"  {where} "
        f"  ORDER BY {qualified_sort} {order} "
        f"  LIMIT ${idx} OFFSET ${idx + 1}"
        f") "
        f"SELECT page.*, ga.display_address "
        f"FROM page "
        f"LEFT JOIN public.geocoded_addresses ga ON ga.location_id = page.id AND ga.source = 'owntracks' "
        f"ORDER BY page.{sort} {order}"
    )
    params.extend([limit, offset])
    rows = await db.fetch(data_query, *params)

    items = [Location(**dict(row)) for row in rows]
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/devices")
async def list_devices(request: Request) -> list[DeviceInfo]:
    """List all distinct device IDs."""
    db = request.app.state.db
    rows = await db.fetch("SELECT DISTINCT device_id FROM public.locations ORDER BY device_id")
    return [DeviceInfo(device_id=row["device_id"]) for row in rows]


@router.get(
    "/date-range",
    responses={404: {"description": "No location data found"}},
)
async def location_date_range(request: Request) -> LocationDateRange:
    """Get the earliest and latest location timestamps."""
    db = request.app.state.db
    row = await db.fetchrow("SELECT MIN(timestamp) AS min_date, MAX(timestamp) AS max_date FROM public.locations")
    if not row or row["min_date"] is None:
        raise HTTPException(status_code=404, detail="No location data found")
    return LocationDateRange(min_date=row["min_date"], max_date=row["max_date"])


@router.get(
    "/count",
    responses={422: {"description": "Invalid date format"}},
)
async def location_count(
    request: Request,
    date: Annotated[
        str | None,
        Query(description="Filter by date (YYYY-MM-DD)", examples=["2026-02-12"]),
    ] = None,
    device_id: Annotated[str | None, Query(description="Filter by device ID", examples=["iphone_stuart"])] = None,
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


@router.get(
    "/{location_id}",
    responses={404: {"description": "Location not found"}},
)
async def get_location(
    request: Request,
    location_id: Annotated[int, fastapi.Path(description="Unique location record ID")],
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
