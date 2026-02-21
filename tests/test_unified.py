"""Tests for unified GPS view endpoints."""

import pytest
from httpx import AsyncClient


def _unified_row() -> dict:
    return {
        "source": "owntracks",
        "identifier": "iphone_stuart",
        "latitude": 40.736238,
        "longitude": -74.039405,
        "timestamp": "2026-02-12T08:11:55+00:00",
        "accuracy": 7,
        "battery": 100,
        "speed_kmh": None,
        "heart_rate": None,
        "created_at": "2026-02-12T08:11:55+00:00",
    }


def _daily_summary_row() -> dict:
    return {
        "activity_date": "2026-02-11",
        "owntracks_device": "iphone_stuart",
        "owntracks_points": 1429,
        "min_battery": 64,
        "max_battery": 100,
        "avg_accuracy": 4.89,
        "garmin_sport": "cycling",
        "garmin_activities": 1,
        "total_distance_km": 50.6,
        "total_duration_seconds": 6932,
        "avg_heart_rate": 142.0,
        "total_calories": 1689,
    }


@pytest.mark.asyncio
async def test_list_unified_gps_empty(client: AsyncClient, mock_db):
    mock_db.fetchval.return_value = 0
    mock_db.fetch.return_value = []

    response = await client.get("/api/v1/gps/unified")

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "limit": 100, "offset": 0}


@pytest.mark.asyncio
async def test_list_unified_gps_with_filters(client: AsyncClient, mock_db):
    mock_db.fetchval.return_value = 1
    mock_db.fetch.return_value = [_unified_row()]

    response = await client.get(
        "/api/v1/gps/unified?source=owntracks&date_from=2026-02-01&date_to=2026-02-12&limit=25&offset=10&order=asc"
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["limit"] == 25
    assert data["offset"] == 10
    assert len(data["items"]) == 1

    count_query = mock_db.fetchval.await_args.args[0]
    assert "source = $1" in count_query
    assert "timestamp >= $2::date" in count_query
    assert "timestamp < ($3::date + INTERVAL '1 day')" in count_query

    data_query, *params = mock_db.fetch.await_args.args
    assert "ORDER BY timestamp asc" in data_query
    assert params == ["owntracks", "2026-02-01", "2026-02-12", 25, 10]


@pytest.mark.asyncio
async def test_daily_summary_with_filters(client: AsyncClient, mock_db):
    mock_db.fetch.return_value = [_daily_summary_row()]

    response = await client.get("/api/v1/gps/daily-summary?date_from=2026-02-01&date_to=2026-02-12&limit=7")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["activity_date"] == "2026-02-11"
    assert data[0]["garmin_sport"] == "cycling"

    query, *params = mock_db.fetch.await_args.args
    assert "activity_date >= $1::date" in query
    assert "activity_date <= $2::date" in query
    assert params == ["2026-02-01", "2026-02-12", 7]
