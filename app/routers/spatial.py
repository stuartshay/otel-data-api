"""PostGIS spatial query endpoints."""

from __future__ import annotations

import fastapi
from fastapi import APIRouter, HTTPException, Query, Request

from app.models.spatial import DistanceResult, NearbyPoint, WithinReferenceResult

router = APIRouter(prefix="/api/v1/spatial", tags=["Spatial"])


@router.get("/nearby", response_model=list[NearbyPoint])
async def find_nearby(
    request: Request,
    lat: float = Query(..., description="Latitude of center point", examples=[40.7362]),
    lon: float = Query(..., description="Longitude of center point", examples=[-74.0394]),
    radius_meters: int = Query(1000, ge=1, le=100000, description="Search radius in meters"),
    source: str | None = Query(None, description="Filter by source: owntracks or garmin", examples=["owntracks"]),
    limit: int = Query(100, ge=1, le=5000),
) -> list[NearbyPoint]:
    """Find GPS points within a radius of a given lat/lon using PostGIS ST_DWithin.

    Searches both OwnTracks locations and Garmin track points within the
    specified radius. Results are sorted by distance from the center point.
    """
    db = request.app.state.db

    queries = []

    if source in (None, "owntracks"):
        queries.append(
            "SELECT 'owntracks' AS source, id, latitude, longitude, "
            "ST_Distance(geog, ST_MakePoint($1, $2)::geography) AS distance_meters, "
            "timestamp FROM public.locations "
            "WHERE geog IS NOT NULL "
            "AND ST_DWithin(geog, ST_MakePoint($1, $2)::geography, $3)"
        )

    if source in (None, "garmin"):
        queries.append(
            "SELECT 'garmin' AS source, id, latitude, longitude, "
            "ST_Distance(geog, ST_MakePoint($1, $2)::geography) AS distance_meters, "
            "timestamp FROM public.garmin_track_points "
            "WHERE geog IS NOT NULL "
            "AND ST_DWithin(geog, ST_MakePoint($1, $2)::geography, $3)"
        )

    if not queries:
        return []

    combined = " UNION ALL ".join(queries)
    full_query = f"{combined} ORDER BY distance_meters ASC LIMIT $4"

    rows = await db.fetch(full_query, lon, lat, radius_meters, limit)
    return [NearbyPoint(**dict(row)) for row in rows]


@router.get("/distance", response_model=DistanceResult)
async def calculate_distance(
    request: Request,
    from_lat: float = Query(..., description="From latitude (e.g. NYC)", examples=[40.7128]),
    from_lon: float = Query(..., description="From longitude (e.g. NYC)", examples=[-74.006]),
    to_lat: float = Query(..., description="To latitude (e.g. Times Square)", examples=[40.758]),
    to_lon: float = Query(..., description="To longitude (e.g. Times Square)", examples=[-73.9855]),
) -> DistanceResult:
    """Calculate the distance in meters between two points using PostGIS ST_Distance.

    Uses geodesic (geography) distance for accurate results on the Earth's surface.
    """
    db = request.app.state.db
    distance = await db.fetchval(
        "SELECT ST_Distance(  ST_MakePoint($1, $2)::geography,  ST_MakePoint($3, $4)::geography)",
        from_lon,
        from_lat,
        to_lon,
        to_lat,
    )
    return DistanceResult(
        distance_meters=distance,
        from_lat=from_lat,
        from_lon=from_lon,
        to_lat=to_lat,
        to_lon=to_lon,
    )


@router.get(
    "/within-reference/{name}",
    response_model=WithinReferenceResult,
    responses={404: {"description": "Reference location not found"}},
)
async def within_reference(
    request: Request,
    name: str = fastapi.Path(description="Reference location name", examples=["home"]),
    source: str | None = Query(None, description="Filter by source: owntracks or garmin", examples=["owntracks"]),
    limit: int = Query(100, ge=1, le=5000),
) -> WithinReferenceResult:
    """Find all GPS points within a named reference location's radius.

    Looks up a named reference location (e.g. 'home') and finds all GPS points
    from OwnTracks and/or Garmin data within its configured radius.
    """
    db = request.app.state.db

    ref = await db.fetchrow(
        "SELECT id, name, latitude, longitude, radius_meters, geog FROM public.reference_locations WHERE name = $1",
        name,
    )
    if not ref:
        raise HTTPException(status_code=404, detail=f"Reference location '{name}' not found")

    radius = ref["radius_meters"]
    ref_lon = ref["longitude"]
    ref_lat = ref["latitude"]

    queries = []

    if source in (None, "owntracks"):
        queries.append(
            "SELECT 'owntracks' AS source, id, latitude, longitude, "
            "ST_Distance(geog, ST_MakePoint($1, $2)::geography) AS distance_meters, "
            "timestamp FROM public.locations "
            "WHERE geog IS NOT NULL "
            "AND ST_DWithin(geog, ST_MakePoint($1, $2)::geography, $3)"
        )

    if source in (None, "garmin"):
        queries.append(
            "SELECT 'garmin' AS source, id, latitude, longitude, "
            "ST_Distance(geog, ST_MakePoint($1, $2)::geography) AS distance_meters, "
            "timestamp FROM public.garmin_track_points "
            "WHERE geog IS NOT NULL "
            "AND ST_DWithin(geog, ST_MakePoint($1, $2)::geography, $3)"
        )

    if not queries:
        return WithinReferenceResult(reference_name=name, radius_meters=radius, total_points=0, points=[])

    combined = " UNION ALL ".join(queries)
    full_query = f"{combined} ORDER BY distance_meters ASC LIMIT $4"

    rows = await db.fetch(full_query, ref_lon, ref_lat, radius, limit)
    points = [NearbyPoint(**dict(row)) for row in rows]

    return WithinReferenceResult(
        reference_name=name,
        radius_meters=radius,
        total_points=len(points),
        points=points,
    )
