"""Tests for locations endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_locations_empty(client: AsyncClient, mock_db):
    mock_db.fetch.return_value = []
    mock_db.fetchval.return_value = 0
    response = await client.get("/api/v1/locations")
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_list_locations_pagination(client: AsyncClient, mock_db):
    mock_db.fetchval.return_value = 100
    mock_db.fetch.return_value = [
        {
            "id": 1,
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
        }
    ]
    response = await client.get("/api/v1/locations?limit=10&offset=0")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 100
    assert data["limit"] == 10
    assert data["offset"] == 0
    assert len(data["items"]) == 1


@pytest.mark.asyncio
async def test_get_devices(client: AsyncClient, mock_db):
    mock_db.fetch.return_value = [
        {"device_id": "phone", "first_seen": "2025-01-01T00:00:00+00:00", "last_seen": "2025-06-01T00:00:00+00:00", "location_count": 5000}
    ]
    response = await client.get("/api/v1/locations/devices")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["device_id"] == "phone"


@pytest.mark.asyncio
async def test_get_location_not_found(client: AsyncClient, mock_db):
    mock_db.fetchrow.return_value = None
    response = await client.get("/api/v1/locations/99999")
    assert response.status_code == 404
