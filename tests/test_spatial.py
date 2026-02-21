"""Tests for spatial query endpoints."""

import pytest
from httpx import AsyncClient


def _nearby_row(source: str = "owntracks", point_id: int = 1) -> dict:
    return {
        "source": source,
        "id": point_id,
        "latitude": 40.736202,
        "longitude": -74.039404,
        "distance_meters": 0.4,
        "timestamp": "2026-02-02T10:30:53+00:00",
    }


def _reference_row() -> dict:
    return {
        "id": 1,
        "name": "home",
        "latitude": 40.7362,
        "longitude": -74.0394,
        "radius_meters": 40,
        "geog": "POINT(-74.0394 40.7362)",
    }


@pytest.mark.asyncio
async def test_find_nearby_default_uses_both_sources(client: AsyncClient, mock_db):
    mock_db.fetch.return_value = [_nearby_row("owntracks", 1), _nearby_row("garmin", 2)]

    response = await client.get("/api/v1/spatial/nearby?lat=40.7362&lon=-74.0394&radius_meters=1000&limit=2")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2

    query, *params = mock_db.fetch.await_args.args
    assert "public.locations" in query
    assert "public.garmin_track_points" in query
    assert "UNION ALL" in query
    assert params == [-74.0394, 40.7362, 1000, 2]


@pytest.mark.asyncio
async def test_find_nearby_invalid_source_returns_empty(client: AsyncClient, mock_db):
    response = await client.get("/api/v1/spatial/nearby?lat=40.7362&lon=-74.0394&source=invalid")

    assert response.status_code == 200
    assert response.json() == []
    mock_db.fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_calculate_distance(client: AsyncClient, mock_db):
    mock_db.fetchval.return_value = 5309.71

    response = await client.get(
        "/api/v1/spatial/distance?from_lat=40.7128&from_lon=-74.006&to_lat=40.758&to_lon=-73.9855"
    )

    assert response.status_code == 200
    assert response.json() == {
        "distance_meters": 5309.71,
        "from_lat": 40.7128,
        "from_lon": -74.006,
        "to_lat": 40.758,
        "to_lon": -73.9855,
    }


@pytest.mark.asyncio
async def test_within_reference_not_found(client: AsyncClient, mock_db):
    mock_db.fetchrow.return_value = None

    response = await client.get("/api/v1/spatial/within-reference/missing")

    assert response.status_code == 404
    assert response.json() == {"detail": "Reference location 'missing' not found"}


@pytest.mark.asyncio
async def test_within_reference_invalid_source_returns_empty(client: AsyncClient, mock_db):
    mock_db.fetchrow.return_value = _reference_row()

    response = await client.get("/api/v1/spatial/within-reference/home?source=invalid")

    assert response.status_code == 200
    assert response.json() == {
        "reference_name": "home",
        "radius_meters": 40,
        "total_points": 0,
        "points": [],
    }
    mock_db.fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_within_reference_success(client: AsyncClient, mock_db):
    mock_db.fetchrow.return_value = _reference_row()
    mock_db.fetch.return_value = [_nearby_row("owntracks", 1)]

    response = await client.get("/api/v1/spatial/within-reference/home?limit=5")

    assert response.status_code == 200
    data = response.json()
    assert data["reference_name"] == "home"
    assert data["radius_meters"] == 40
    assert data["total_points"] == 1
    assert len(data["points"]) == 1

    query, *params = mock_db.fetch.await_args.args
    assert "public.locations" in query
    assert "public.garmin_track_points" in query
    assert "UNION ALL" in query
    assert params == [-74.0394, 40.7362, 40, 5]
