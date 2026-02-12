"""Reference locations CRUD endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from app.auth import require_auth
from app.models.reference import ReferenceLocation, ReferenceLocationCreate, ReferenceLocationUpdate

router = APIRouter(prefix="/api/v1/reference-locations", tags=["Reference Locations"])


@router.get("", response_model=list[ReferenceLocation])
async def list_reference_locations(request: Request) -> list[ReferenceLocation]:
    """List all reference locations."""
    db = request.app.state.db
    rows = await db.fetch(
        "SELECT id, name, latitude, longitude, radius_meters, description, "
        "created_at, updated_at FROM public.reference_locations ORDER BY name"
    )
    return [ReferenceLocation(**dict(row)) for row in rows]


@router.get("/{location_id}", response_model=ReferenceLocation)
async def get_reference_location(request: Request, location_id: int) -> ReferenceLocation:
    """Get a single reference location by ID."""
    db = request.app.state.db
    row = await db.fetchrow(
        "SELECT id, name, latitude, longitude, radius_meters, description, "
        "created_at, updated_at FROM public.reference_locations WHERE id = $1",
        location_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Reference location not found")
    return ReferenceLocation(**dict(row))


@router.post("", response_model=ReferenceLocation, status_code=201)
async def create_reference_location(
    request: Request,
    body: ReferenceLocationCreate,
    _user: dict = Depends(require_auth),
) -> ReferenceLocation:
    """Create a new reference location (auth required)."""
    db = request.app.state.db
    row = await db.fetchrow(
        "INSERT INTO public.reference_locations (name, latitude, longitude, radius_meters, description) "
        "VALUES ($1, $2, $3, $4, $5) "
        "RETURNING id, name, latitude, longitude, radius_meters, description, created_at, updated_at",
        body.name,
        body.latitude,
        body.longitude,
        body.radius_meters,
        body.description,
    )
    if not row:
        raise HTTPException(status_code=500, detail="Failed to create reference location")
    return ReferenceLocation(**dict(row))


@router.put("/{location_id}", response_model=ReferenceLocation)
async def update_reference_location(
    request: Request,
    location_id: int,
    body: ReferenceLocationUpdate,
    _user: dict = Depends(require_auth),
) -> ReferenceLocation:
    """Update a reference location (auth required)."""
    db = request.app.state.db

    # Build dynamic SET clause from non-None fields
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    set_parts: list[str] = []
    params: list = []
    idx = 1
    for field_name, value in updates.items():
        set_parts.append(f"{field_name} = ${idx}")
        params.append(value)
        idx += 1

    set_parts.append("updated_at = NOW()")
    params.append(location_id)

    row = await db.fetchrow(
        f"UPDATE public.reference_locations SET {', '.join(set_parts)} "
        f"WHERE id = ${idx} "
        f"RETURNING id, name, latitude, longitude, radius_meters, description, created_at, updated_at",
        *params,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Reference location not found")
    return ReferenceLocation(**dict(row))


@router.delete("/{location_id}", status_code=204, response_class=Response)
async def delete_reference_location(
    request: Request,
    location_id: int,
    _user: dict = Depends(require_auth),
) -> Response:
    """Delete a reference location (auth required)."""
    db = request.app.state.db
    result = await db.execute("DELETE FROM public.reference_locations WHERE id = $1", location_id)
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Reference location not found")
    return Response(status_code=204)
