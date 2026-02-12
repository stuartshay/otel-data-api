"""Tests for garmin endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_activities_empty(client: AsyncClient, mock_db):
    mock_db.fetch.return_value = []
    mock_db.fetchval.return_value = 0
    response = await client.get("/api/v1/garmin/activities")
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_get_sports(client: AsyncClient, mock_db):
    mock_db.fetch.return_value = [{"sport": "cycling", "activity_count": 15}]
    response = await client.get("/api/v1/garmin/sports")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["sport"] == "cycling"


@pytest.mark.asyncio
async def test_get_activity_not_found(client: AsyncClient, mock_db):
    mock_db.fetchrow.return_value = None
    response = await client.get("/api/v1/garmin/activities/nonexistent")
    assert response.status_code == 404
