"""Tests for Garmin endpoints."""

import pytest
from httpx import AsyncClient


def _activity_row(activity_id: str = "20932993811") -> dict:
    return {
        "activity_id": activity_id,
        "sport": "cycling",
        "sub_sport": "road",
        "start_time": "2025-11-08T18:21:13+00:00",
        "end_time": "2025-11-08T20:16:45+00:00",
        "distance_km": 50.6,
        "duration_seconds": 6932,
        "avg_heart_rate": 142,
        "max_heart_rate": 178,
        "avg_cadence": 78,
        "max_cadence": 112,
        "calories": 1689,
        "avg_speed_kmh": 26.3,
        "max_speed_kmh": 48.7,
        "total_ascent_m": 385,
        "total_descent_m": 380,
        "total_distance": 50598.95,
        "avg_pace": 3.51,
        "device_manufacturer": "garmin",
        "avg_temperature_c": 18,
        "min_temperature_c": 14,
        "max_temperature_c": 22,
        "total_elapsed_time": 7200.5,
        "total_timer_time": 6932.1,
        "created_at": "2026-02-09T23:56:37+00:00",
        "uploaded_at": "2026-02-09T23:56:37+00:00",
        "track_point_count": 10707,
    }


def _track_row(activity_id: str = "20932993811") -> dict:
    return {
        "id": 1,
        "activity_id": activity_id,
        "latitude": 40.715,
        "longitude": -74.017,
        "timestamp": "2025-11-08T18:21:13+00:00",
        "altitude": 12.4,
        "distance_from_start_km": 0.0,
        "speed_kmh": 24.5,
        "heart_rate": 135,
        "cadence": 80,
        "temperature_c": 18,
        "created_at": "2026-02-09T23:56:37+00:00",
    }


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
async def test_list_activities_filters_and_invalid_sort_falls_back(client: AsyncClient, mock_db):
    mock_db.fetchval.return_value = 1
    mock_db.fetch.return_value = [_activity_row()]

    response = await client.get(
        "/api/v1/garmin/activities?sport=cycling&date_from=2025-11-01&date_to=2025-11-30"
        "&limit=10&offset=3&sort=bad_column&order=asc"
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["limit"] == 10
    assert data["offset"] == 3
    assert len(data["items"]) == 1

    data_query, *params = mock_db.fetch.await_args.args
    assert "ORDER BY a.start_time asc" in data_query
    assert params == ["cycling", "2025-11-01", "2025-11-30", 10, 3]


@pytest.mark.asyncio
async def test_get_sports(client: AsyncClient, mock_db):
    mock_db.fetch.return_value = [{"sport": "cycling", "activity_count": 15}]

    response = await client.get("/api/v1/garmin/sports")

    assert response.status_code == 200
    assert response.json() == [{"sport": "cycling", "activity_count": 15}]


@pytest.mark.asyncio
async def test_get_activity_success(client: AsyncClient, mock_db):
    mock_db.fetchrow.return_value = _activity_row()

    response = await client.get("/api/v1/garmin/activities/20932993811")

    assert response.status_code == 200
    data = response.json()
    assert data["activity_id"] == "20932993811"
    assert data["sport"] == "cycling"


@pytest.mark.asyncio
async def test_get_activity_not_found(client: AsyncClient, mock_db):
    mock_db.fetchrow.return_value = None

    response = await client.get("/api/v1/garmin/activities/nonexistent")

    assert response.status_code == 404
    assert response.json() == {"detail": "Activity not found"}


@pytest.mark.asyncio
async def test_list_track_points_success_and_invalid_sort_falls_back(client: AsyncClient, mock_db):
    mock_db.fetchval.side_effect = [1, 2]
    mock_db.fetch.return_value = [_track_row()]

    response = await client.get(
        "/api/v1/garmin/activities/20932993811/tracks?sort=bad_column&order=desc&limit=5&offset=1"
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert data["limit"] == 5
    assert data["offset"] == 1
    assert len(data["items"]) == 1

    track_query, *params = mock_db.fetch.await_args.args
    assert "ORDER BY timestamp desc" in track_query
    assert params == ["20932993811", 5, 1]


@pytest.mark.asyncio
async def test_list_track_points_activity_not_found(client: AsyncClient, mock_db):
    mock_db.fetchval.return_value = None

    response = await client.get("/api/v1/garmin/activities/missing/tracks")

    assert response.status_code == 404
    assert response.json() == {"detail": "Activity not found"}


@pytest.mark.asyncio
async def test_list_track_points_simplify(client: AsyncClient, mock_db):
    mock_db.fetchval.side_effect = [1, 100]
    mock_db.fetch.return_value = [_track_row(), _track_row()]

    response = await client.get("/api/v1/garmin/activities/20932993811/tracks?simplify=0.00001")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 100
    assert data["limit"] == 2
    assert data["offset"] == 0
    assert len(data["items"]) == 2

    query, *params = mock_db.fetch.await_args.args
    assert "ST_Simplify" in query
    assert "gtp.longitude = sc.lng AND gtp.latitude = sc.lat" in query
    assert "rn = 1" in query
    assert "gtp.timestamp, (gtp.altitude IS NOT NULL) DESC, gtp.id" in query
    assert params == ["20932993811", 0.00001]


@pytest.mark.asyncio
async def test_list_track_points_simplify_respects_order(client: AsyncClient, mock_db):
    mock_db.fetchval.side_effect = [1, 50]
    mock_db.fetch.return_value = [_track_row()]

    response = await client.get("/api/v1/garmin/activities/20932993811/tracks?simplify=0.0001&order=desc")

    assert response.status_code == 200
    query = mock_db.fetch.await_args.args[0]
    assert "ORDER BY timestamp desc" in query


@pytest.mark.asyncio
async def test_list_track_points_simplify_not_found(client: AsyncClient, mock_db):
    mock_db.fetchval.return_value = None

    response = await client.get("/api/v1/garmin/activities/missing/tracks?simplify=0.00001")

    assert response.status_code == 404
    assert response.json() == {"detail": "Activity not found"}


@pytest.mark.asyncio
async def test_list_track_points_simplify_validation(client: AsyncClient, mock_db):
    response = await client.get("/api/v1/garmin/activities/20932993811/tracks?simplify=0.1")
    assert response.status_code == 422

    response = await client.get("/api/v1/garmin/activities/20932993811/tracks?simplify=0.0000001")
    assert response.status_code == 422
