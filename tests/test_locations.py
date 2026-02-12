"""Tests for OwnTracks location endpoints."""

import json

import pytest
from httpx import AsyncClient


def _location_row(*, location_id: int = 1, raw_payload: str | dict | None = None) -> dict:
    return {
        "id": location_id,
        "device_id": "phone",
        "tid": "p1",
        "latitude": 40.7128,
        "longitude": -74.0060,
        "accuracy": 10,
        "altitude": None,
        "velocity": None,
        "battery": 85,
        "battery_status": None,
        "connection_type": None,
        "trigger": None,
        "timestamp": "2025-01-01T00:00:00+00:00",
        "created_at": "2025-01-01T00:00:00+00:00",
        "raw_payload": raw_payload,
    }


@pytest.mark.asyncio
async def test_list_locations_empty(client: AsyncClient, mock_db):
    mock_db.fetch.return_value = []
    mock_db.fetchval.return_value = 0

    response = await client.get("/api/v1/locations")

    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0
    assert data["limit"] == 50
    assert data["offset"] == 0


@pytest.mark.asyncio
async def test_list_locations_filters_and_invalid_sort_falls_back(client: AsyncClient, mock_db):
    mock_db.fetchval.return_value = 1
    mock_db.fetch.return_value = [_location_row()]

    response = await client.get(
        "/api/v1/locations?device_id=phone&date_from=2025-01-01&date_to=2025-01-02"
        "&limit=10&offset=5&sort=bad_column&order=asc"
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["limit"] == 10
    assert data["offset"] == 5
    assert len(data["items"]) == 1

    count_query = mock_db.fetchval.await_args.args[0]
    assert "device_id = $1" in count_query
    assert "created_at >= $2::date" in count_query
    assert "created_at < ($3::date + INTERVAL '1 day')" in count_query

    data_query, *params = mock_db.fetch.await_args.args
    assert "ORDER BY created_at asc" in data_query
    assert params == ["phone", "2025-01-01", "2025-01-02", 10, 5]


@pytest.mark.asyncio
async def test_get_devices(client: AsyncClient, mock_db):
    mock_db.fetch.return_value = [{"device_id": "phone"}, {"device_id": "watch"}]

    response = await client.get("/api/v1/locations/devices")

    assert response.status_code == 200
    assert response.json() == [{"device_id": "phone"}, {"device_id": "watch"}]


@pytest.mark.asyncio
async def test_location_count_with_filters(client: AsyncClient, mock_db):
    mock_db.fetchval.return_value = 42

    response = await client.get("/api/v1/locations/count?date=2025-01-01&device_id=phone")

    assert response.status_code == 200
    assert response.json() == {"count": 42, "date": "2025-01-01", "device_id": "phone"}

    count_query, *params = mock_db.fetchval.await_args.args
    assert "DATE(created_at) = $1::date" in count_query
    assert "device_id = $2" in count_query
    assert params == ["2025-01-01", "phone"]


@pytest.mark.asyncio
async def test_get_location_success_parses_raw_payload_string(client: AsyncClient, mock_db):
    raw_payload = json.dumps({"_type": "location", "lat": 40.7128})
    mock_db.fetchrow.return_value = _location_row(raw_payload=raw_payload)

    response = await client.get("/api/v1/locations/1")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == 1
    assert data["raw_payload"] == {"_type": "location", "lat": 40.7128}


@pytest.mark.asyncio
async def test_get_location_not_found(client: AsyncClient, mock_db):
    mock_db.fetchrow.return_value = None

    response = await client.get("/api/v1/locations/99999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Location not found"}
