"""Tests for Garmin endpoints."""

import dataclasses
from datetime import date

import fastapi
import httpx
import pytest
import structlog
from httpx import ASGITransport, AsyncClient

from app import create_app
from app.auth import require_auth
from app.config import Config


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
        "hr_available": True,
        "avg_cadence": 78,
        "max_cadence": 112,
        "total_strokes": 4250,
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
        "device_id": 3444454776,
        "dev_manufacturer": "garmin",
        "dev_garmin_product": 4061,
        "dev_model": "Edge 540 Solar",
        "dev_software_version": "31.30",
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
        "hr_zone": 3,
        "respiration_rate": 22,
        "cadence": 80,
        "temperature_c": 18,
        "surface_type": "paved",
        "effort_level": "steady",
        "created_at": "2026-02-09T23:56:37+00:00",
    }


def _climb_row(activity_id: str = "20932993811") -> dict:
    return {
        "id": 1,
        "activity_id": activity_id,
        "source_split_index": 0,
        "message_index": 0,
        "split_type": None,
        "climb_type": "CLIMB_PRO_CYCLING_CLIMB",
        "start_time": "2026-03-08T19:58:56+00:00",
        "end_time": "2026-03-08T20:01:01+00:00",
        "start_time_local": "2026-03-08T15:58:56",
        "duration_seconds": 126.09,
        "elapsed_duration_seconds": 126.09,
        "moving_duration_seconds": 125.0,
        "distance_meters": 503.59,
        "elevation_gain_meters": 9.0,
        "elevation_loss_meters": 0.6,
        "start_elevation_meters": 24.2,
        "average_grade_percent": 1.79,
        "max_grade_percent": 6.43,
        "average_speed_mps": 3.994,
        "average_moving_speed_mps": 4.029,
        "max_speed_mps": 6.27,
        "average_vertical_speed_mps": 0.071,
        "average_elapsed_vertical_speed_mps": 0.072,
        "start_latitude": 40.7937,
        "start_longitude": -73.961,
        "end_latitude": 40.7901,
        "end_longitude": -73.9642,
        "climb_pro_difficulty": "NONE",
        "calories": 24.0,
        "bmr_calories": 3.0,
        "average_temperature_c": 21.0,
        "min_temperature_c": 21.0,
        "max_temperature_c": 21.0,
        "created_at": "2026-06-27T03:00:00+00:00",
        "updated_at": "2026-06-27T03:00:00+00:00",
    }


def _lap_row(activity_id: str = "20932993811", lap_index: int = 1) -> dict:
    return {
        "id": lap_index,
        "activity_id": activity_id,
        "lap_index": lap_index,
        "start_time": "2026-03-08T19:58:56+00:00",
        "end_time": "2026-03-08T20:26:13+00:00",
        "duration_seconds": 1637.0,
        "elapsed_duration_seconds": 1637.0,
        "moving_duration_seconds": 1600.0,
        "distance_meters": 8046.72,
        "paved_distance_meters": 7805.32,
        "unpaved_distance_meters": 241.4,
        "avg_speed_mps": 4.92,
        "avg_heart_rate": 130,
        "max_heart_rate": 150,
        "total_ascent_meters": 98.0,
        "total_descent_meters": 88.0,
        "calories": 210.0,
        "created_at": "2026-07-03T03:00:00+00:00",
        "updated_at": "2026-07-03T03:00:00+00:00",
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
    assert data["items"][0]["total_strokes"] == 4250

    data_query, *params = mock_db.fetch.await_args.args
    assert "ORDER BY a.start_time asc" in data_query
    assert params == ["cycling", date(2025, 11, 1), date(2025, 11, 30), 10, 3]


@pytest.mark.asyncio
async def test_list_activities_invalid_date(client: AsyncClient, mock_db):
    """Invalid date_from returns 422 with a descriptive error."""
    response = await client.get("/api/v1/garmin/activities?date_from=not-a-date")

    assert response.status_code == 422
    assert "Invalid date format" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_sports(client: AsyncClient, mock_db):
    mock_db.fetch.return_value = [{"sport": "cycling", "activity_count": 15}]

    response = await client.get("/api/v1/garmin/sports")

    assert response.status_code == 200
    assert response.json() == [{"sport": "cycling", "activity_count": 15}]


@pytest.mark.asyncio
async def test_get_device_counts(client: AsyncClient, mock_db):
    mock_db.fetch.return_value = [
        {"label": "Edge 500", "activity_count": 1237},
        {"label": "Edge 540 Solar", "activity_count": 194},
        {"label": "Manual", "activity_count": 5},
    ]

    response = await client.get("/api/v1/garmin/device-counts")

    assert response.status_code == 200
    assert response.json() == [
        {"label": "Edge 500", "activity_count": 1237},
        {"label": "Edge 540 Solar", "activity_count": 194},
        {"label": "Manual", "activity_count": 5},
    ]
    query = mock_db.fetch.await_args.args[0]
    assert "COALESCE(NULLIF(TRIM(d.model), ''), 'Manual') AS label" in query
    assert "LEFT JOIN public.garmin_devices d ON d.device_id = a.device_id" in query
    assert "GROUP BY COALESCE(NULLIF(TRIM(d.model), ''), 'Manual')" in query
    assert "activity_count DESC" in query


@pytest.mark.asyncio
async def test_activity_totals_empty(client: AsyncClient, mock_db):
    mock_db.fetch.return_value = []

    response = await client.get("/api/v1/garmin/activity-totals?period=month")

    assert response.status_code == 200
    assert response.json() == []
    query, *params = mock_db.fetch.await_args.args
    assert "DATE_TRUNC($1::text, start_time)" in query
    assert "GROUP BY period_start" in query
    assert "ORDER BY period_start ASC" in query
    assert params == ["month"]


@pytest.mark.asyncio
@pytest.mark.parametrize("period", ["week", "month", "year"])
async def test_activity_totals_returns_rows(client: AsyncClient, mock_db, period):
    mock_db.fetch.return_value = [
        {
            "period_start": date(2025, 5, 1),
            "activity_count": 12,
            "total_distance_km": 632.4,
            "total_duration_seconds": 90123.0,
            "total_ascent_m": 4521.0,
            "total_calories": 18234,
        },
        {
            "period_start": date(2025, 6, 1),
            "activity_count": 9,
            "total_distance_km": 410.5,
            "total_duration_seconds": 60000.0,
            "total_ascent_m": 2300.0,
            "total_calories": 12000,
        },
    ]

    response = await client.get(f"/api/v1/garmin/activity-totals?period={period}")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert body[0]["period_start"] == "2025-05-01"
    assert body[0]["activity_count"] == 12
    assert body[0]["total_distance_km"] == 632.4
    query, *params = mock_db.fetch.await_args.args
    assert "DATE_TRUNC($1::text, start_time)" in query
    assert params[0] == period


@pytest.mark.asyncio
async def test_activity_totals_invalid_period(client: AsyncClient, mock_db):
    response = await client.get("/api/v1/garmin/activity-totals?period=decade")

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_activity_totals_missing_period(client: AsyncClient, mock_db):
    response = await client.get("/api/v1/garmin/activity-totals")

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_activity_totals_invalid_date(client: AsyncClient, mock_db):
    response = await client.get("/api/v1/garmin/activity-totals?period=month&date_from=not-a-date")

    assert response.status_code == 422
    assert "Invalid date format" in response.json()["detail"]


@pytest.mark.asyncio
async def test_activity_totals_with_filters(client: AsyncClient, mock_db):
    mock_db.fetch.return_value = []

    response = await client.get(
        "/api/v1/garmin/activity-totals?period=week&sport=cycling&date_from=2025-05-01&date_to=2025-12-31"
    )

    assert response.status_code == 200
    query, *params = mock_db.fetch.await_args.args
    assert "DATE_TRUNC($1::text, start_time)" in query
    assert "sport = $2" in query
    assert "start_time >= $3::date" in query
    assert "start_time < ($4::date + INTERVAL '1 day')" in query
    assert params == ["week", "cycling", date(2025, 5, 1), date(2025, 12, 31)]


@pytest.mark.asyncio
async def test_get_activity_success(client: AsyncClient, mock_db):
    mock_db.fetchrow.return_value = _activity_row()

    response = await client.get("/api/v1/garmin/activities/20932993811")

    assert response.status_code == 200
    data = response.json()
    assert data["activity_id"] == "20932993811"
    assert data["sport"] == "cycling"
    assert data["hr_available"] is True
    assert data["total_strokes"] == 4250


@pytest.mark.asyncio
async def test_get_activity_includes_device(client: AsyncClient, mock_db):
    mock_db.fetchrow.return_value = _activity_row()

    response = await client.get("/api/v1/garmin/activities/20932993811")

    assert response.status_code == 200
    device = response.json()["device"]
    assert device == {
        "device_id": 3444454776,
        "manufacturer": "garmin",
        "garmin_product": 4061,
        "model": "Edge 540 Solar",
        "software_version": "31.30",
    }


@pytest.mark.asyncio
async def test_get_activity_without_device(client: AsyncClient, mock_db):
    row = _activity_row()
    # The SELECT always projects the joined device columns; when no device is
    # linked they come back as explicit NULLs (not missing keys).
    for key in (
        "device_id",
        "dev_manufacturer",
        "dev_garmin_product",
        "dev_model",
        "dev_software_version",
    ):
        row[key] = None
    mock_db.fetchrow.return_value = row

    response = await client.get("/api/v1/garmin/activities/20932993811")

    assert response.status_code == 200
    assert response.json()["device"] is None


@pytest.mark.asyncio
async def test_get_activity_logs_full_response_when_enabled(config: Config, mock_db):
    enabled_config = dataclasses.replace(config, log_garmin_activity_detail=True)
    app = create_app(enabled_config)
    app.state.db = mock_db
    mock_db.fetchrow.return_value = _activity_row()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with structlog.testing.capture_logs() as logs:
            response = await client.get("/api/v1/garmin/activities/20932993811")

    assert response.status_code == 200
    detail_logs = [entry for entry in logs if entry.get("event") == "garmin.activity.detail"]
    assert len(detail_logs) == 1
    entry = detail_logs[0]
    assert entry["garmin_activity_id"] == "20932993811"
    # The logged payload must match the full HTTP response body exactly.
    assert entry["response"] == response.json()


@pytest.mark.asyncio
async def test_get_activity_detail_logging_disabled_by_default(client: AsyncClient, mock_db):
    mock_db.fetchrow.return_value = _activity_row()

    with structlog.testing.capture_logs() as logs:
        response = await client.get("/api/v1/garmin/activities/20932993811")

    assert response.status_code == 200
    assert not [entry for entry in logs if entry.get("event") == "garmin.activity.detail"]


@pytest.mark.asyncio
async def test_get_activity_hr_availability_defaults_false(client: AsyncClient, mock_db):
    row = _activity_row()
    row["avg_heart_rate"] = None
    row["max_heart_rate"] = None
    row["hr_available"] = False
    mock_db.fetchrow.return_value = row

    response = await client.get("/api/v1/garmin/activities/20932993811")

    assert response.status_code == 200
    assert response.json()["hr_available"] is False


@pytest.mark.asyncio
async def test_get_activity_not_found(client: AsyncClient, mock_db):
    mock_db.fetchrow.return_value = None

    response = await client.get("/api/v1/garmin/activities/nonexistent")

    assert response.status_code == 404
    assert response.json() == {"detail": "Activity not found"}


@pytest.mark.asyncio
async def test_patch_activity_success(client: AsyncClient, mock_db):
    updated = _activity_row()
    updated["avg_heart_rate"] = 141
    updated["aerobic_training_effect"] = 3.2
    updated["total_strokes"] = 4300

    mock_db.fetchrow.side_effect = [{"activity_id": "20932993811"}, updated]

    response = await client.patch(
        "/api/v1/garmin/activities/20932993811",
        json={"avg_heart_rate": 141, "aerobic_training_effect": 3.2, "total_strokes": 4300},
    )

    assert response.status_code == 200
    assert response.json()["activity_id"] == "20932993811"
    assert response.json()["avg_heart_rate"] == 141
    assert response.json()["aerobic_training_effect"] == 3.2
    assert response.json()["total_strokes"] == 4300

    update_query, *update_params = mock_db.fetchrow.await_args_list[0].args
    assert "UPDATE public.garmin_activities SET" in update_query
    assert "avg_heart_rate = $1" in update_query
    assert "aerobic_training_effect = $2" in update_query
    assert "total_strokes = $3" in update_query
    assert update_params == [141, 3.2, 4300, "20932993811"]


@pytest.mark.asyncio
async def test_patch_activity_requires_body_fields(client: AsyncClient, mock_db):
    response = await client.patch("/api/v1/garmin/activities/20932993811", json={})

    assert response.status_code == 400
    assert response.json() == {"detail": "No fields to update"}


@pytest.mark.asyncio
async def test_patch_activity_not_found(client: AsyncClient, mock_db):
    mock_db.fetchrow.return_value = None

    response = await client.patch(
        "/api/v1/garmin/activities/missing",
        json={"avg_heart_rate": 141},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Activity not found"}


@pytest.mark.asyncio
async def test_patch_activity_auth_required_when_dependency_denies(client: AsyncClient, app):
    async def _deny_auth():
        raise fastapi.HTTPException(status_code=401, detail="Authentication required")

    app.dependency_overrides[require_auth] = _deny_auth
    try:
        response = await client.patch(
            "/api/v1/garmin/activities/20932993811",
            json={"avg_heart_rate": 141},
        )
    finally:
        app.dependency_overrides.pop(require_auth, None)

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


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
    assert data["items"][0]["hr_zone"] == 3
    assert data["items"][0]["respiration_rate"] == 22
    assert data["items"][0]["surface_type"] == "paved"
    assert data["items"][0]["effort_level"] == "steady"

    track_query, *params = mock_db.fetch.await_args.args
    assert "ORDER BY gtp.timestamp desc" in track_query
    assert "garmin_track_points" in track_query
    assert "LEFT JOIN public.geocoded_addresses" in track_query
    assert "ga.garmin_activity_id = gtp.activity_id" in track_query
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
    # Regression guard for #113: simplify branch must not join geocoded_addresses
    # (the join caused asyncpg statement timeouts on large activities).
    assert "geocoded_addresses" not in query
    assert params == ["20932993811", 0.00001]


@pytest.mark.asyncio
async def test_list_track_points_simplify_respects_order(client: AsyncClient, mock_db):
    mock_db.fetchval.side_effect = [1, 50]
    mock_db.fetch.return_value = [_track_row()]

    response = await client.get("/api/v1/garmin/activities/20932993811/tracks?simplify=0.0001&order=desc")

    assert response.status_code == 200
    query = mock_db.fetch.await_args.args[0]
    assert "ORDER BY m.timestamp desc" in query


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


def _chart_row() -> dict:
    return {
        "timestamp": "2025-11-08T18:21:13+00:00",
        "altitude": 12.4,
        "distance_from_start_km": 0.0,
        "speed_kmh": 24.5,
        "heart_rate": 135,
        "hr_zone": 3,
        "respiration_rate": 22,
        "cadence": 80,
        "temperature_c": 18,
        "surface_type": "paved",
        "effort_level": "steady",
        "latitude": 40.715,
        "longitude": -74.017,
    }


@pytest.mark.asyncio
async def test_get_chart_data_success(client: AsyncClient, mock_db):
    mock_db.fetchval.return_value = 1
    mock_db.fetch.return_value = [_chart_row(), _chart_row()]

    response = await client.get("/api/v1/garmin/activities/20932993811/chart-data")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0]["latitude"] == 40.715
    assert data[0]["altitude"] == 12.4
    assert data[0]["speed_kmh"] == 24.5
    assert data[0]["hr_zone"] == 3
    assert data[0]["respiration_rate"] == 22
    assert data[0]["surface_type"] == "paved"
    assert data[0]["effort_level"] == "steady"

    query = mock_db.fetch.await_args.args[0]
    assert "garmin_track_points" in query
    assert "ORDER BY timestamp ASC" in query


@pytest.mark.asyncio
async def test_get_chart_data_not_found(client: AsyncClient, mock_db):
    mock_db.fetchval.return_value = None

    response = await client.get("/api/v1/garmin/activities/nonexistent/chart-data")

    assert response.status_code == 404
    assert response.json() == {"detail": "Activity not found"}


@pytest.mark.asyncio
async def test_list_activity_climbs_success(client: AsyncClient, mock_db):
    mock_db.fetchval.return_value = 1
    mock_db.fetch.return_value = [_climb_row()]

    response = await client.get("/api/v1/garmin/activities/20932993811/climbs")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["activity_id"] == "20932993811"
    assert data[0]["climb_type"] == "CLIMB_PRO_CYCLING_CLIMB"
    assert data[0]["distance_meters"] == 503.59
    assert data[0]["elevation_gain_meters"] == 9.0
    assert data[0]["average_grade_percent"] == 1.79
    assert data[0]["climb_pro_difficulty"] == "NONE"

    query = mock_db.fetch.await_args.args[0]
    assert "public.garmin_activity_climbs" in query
    assert "ORDER BY source_split_index ASC" in query


@pytest.mark.asyncio
async def test_list_activity_climbs_not_found(client: AsyncClient, mock_db):
    mock_db.fetchval.return_value = None

    response = await client.get("/api/v1/garmin/activities/nonexistent/climbs")

    assert response.status_code == 404
    assert response.json() == {"detail": "Activity not found"}


@pytest.mark.asyncio
async def test_list_activity_laps_success(client: AsyncClient, mock_db):
    mock_db.fetchval.return_value = 1
    mock_db.fetch.return_value = [_lap_row(lap_index=1), _lap_row(lap_index=2)]

    response = await client.get("/api/v1/garmin/activities/20932993811/laps")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["activity_id"] == "20932993811"
    assert data[0]["lap_index"] == 1
    assert data[0]["distance_meters"] == 8046.72
    assert data[0]["avg_heart_rate"] == 130
    assert data[0]["max_heart_rate"] == 150
    assert data[0]["total_ascent_meters"] == 98.0

    query = mock_db.fetch.await_args.args[0]
    assert "public.garmin_activity_laps" in query
    assert "ORDER BY lap_index ASC" in query


@pytest.mark.asyncio
async def test_list_activity_laps_empty_for_existing_activity(client: AsyncClient, mock_db):
    mock_db.fetchval.return_value = 1
    mock_db.fetch.return_value = []

    response = await client.get("/api/v1/garmin/activities/20932993811/laps")

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_activity_laps_not_found(client: AsyncClient, mock_db):
    mock_db.fetchval.return_value = None

    response = await client.get("/api/v1/garmin/activities/nonexistent/laps")

    assert response.status_code == 404
    assert response.json() == {"detail": "Activity not found"}


def _laps_activity_row(activity_id: str = "20932993811") -> dict:
    return {
        "activity_id": activity_id,
        "sport": "cycling",
        "sub_sport": "road",
        "start_time": "2026-03-08T19:58:56+00:00",
        "distance_km": 52.35,
        "duration_seconds": 11045.0,
        "avg_speed_kmh": 17.1,
        "avg_heart_rate": 118,
        "max_heart_rate": 149,
        "total_ascent_m": 191.0,
    }


@pytest.mark.asyncio
async def test_list_laps_batch_success(client: AsyncClient, mock_db):
    mock_db.fetchval.return_value = 2
    mock_db.fetch.side_effect = [
        [_laps_activity_row("111"), _laps_activity_row("222")],
        [
            _lap_row(activity_id="111", lap_index=1),
            _lap_row(activity_id="111", lap_index=2),
            _lap_row(activity_id="222", lap_index=1),
        ],
    ]

    response = await client.get("/api/v1/garmin/laps")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert data["limit"] == 50
    assert data["offset"] == 0
    assert len(data["items"]) == 2

    first = data["items"][0]
    assert first["activity"]["activity_id"] == "111"
    assert first["activity"]["sport"] == "cycling"
    assert [lap["lap_index"] for lap in first["laps"]] == [1, 2]

    second = data["items"][1]
    assert second["activity"]["activity_id"] == "222"
    assert len(second["laps"]) == 1

    activity_query = mock_db.fetch.await_args_list[0].args[0]
    assert "EXISTS (SELECT 1 FROM public.garmin_activity_laps" in activity_query
    assert "ORDER BY a.start_time DESC" in activity_query

    laps_query = mock_db.fetch.await_args_list[1].args[0]
    assert "activity_id = ANY($1::text[])" in laps_query
    assert "ORDER BY lap_index ASC" in laps_query


@pytest.mark.asyncio
async def test_list_laps_batch_sport_and_date_filters(client: AsyncClient, mock_db):
    mock_db.fetchval.return_value = 1
    mock_db.fetch.side_effect = [
        [_laps_activity_row("111")],
        [_lap_row(activity_id="111", lap_index=1)],
    ]

    response = await client.get(
        "/api/v1/garmin/laps",
        params={"sport": "cycling", "date_from": "2026-01-01", "date_to": "2026-06-30"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1

    count_query = mock_db.fetchval.await_args.args[0]
    assert "a.sport = $1" in count_query
    assert "a.start_time >= $2::date" in count_query
    assert "a.start_time < ($3::date + INTERVAL '1 day')" in count_query


@pytest.mark.asyncio
async def test_list_laps_batch_empty(client: AsyncClient, mock_db):
    mock_db.fetchval.return_value = 0
    mock_db.fetch.side_effect = [[]]

    response = await client.get("/api/v1/garmin/laps")

    assert response.status_code == 200
    data = response.json()
    assert data == {"items": [], "total": 0, "limit": 50, "offset": 0}

    # Laps query must be skipped when no activities match.
    assert mock_db.fetch.await_count == 1


@pytest.mark.asyncio
async def test_list_laps_batch_invalid_date(client: AsyncClient, mock_db):
    response = await client.get("/api/v1/garmin/laps", params={"date_from": "not-a-date"})

    assert response.status_code == 422


class _FakeSyncResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


@pytest.mark.asyncio
async def test_trigger_sync_window_hours_passthrough(
    client: AsyncClient, config: Config, monkeypatch: pytest.MonkeyPatch
):
    captured: dict = {}

    class _FakeClient:
        def __init__(self, *, base_url: str, timeout: float):
            captured["base_url"] = base_url
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, path: str, params=None, headers=None):
            captured["path"] = path
            captured["params"] = params
            captured["headers"] = headers
            return _FakeSyncResponse(
                202,
                {
                    "status": "accepted",
                    "message": "Sync started",
                    "triggered_at": "2026-03-12T01:00:00Z",
                    "window_hours": 48,
                },
            )

    monkeypatch.setattr("app.routers.garmin.httpx.AsyncClient", _FakeClient)

    response = await client.post("/api/v1/garmin/sync?window_hours=48")

    assert response.status_code == 202
    assert response.json()["status"] == "accepted"
    assert response.json()["window_hours"] == 48
    assert captured["path"] == "/api/v1/sync"
    assert captured["params"] == {"window_hours": 48}
    assert captured["base_url"] == config.garmin_sync_base_url
    assert captured["timeout"] == config.garmin_sync_timeout_seconds
    assert "X-Garmin-Sync-Id" in captured["headers"]


@pytest.mark.asyncio
async def test_trigger_sync_lookback_passthrough(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    captured: dict = {}

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def __init__(self, *, base_url: str, timeout: float):
            captured["base_url"] = base_url
            captured["timeout"] = timeout

        async def post(self, path: str, params=None, headers=None):
            captured["path"] = path
            captured["params"] = params
            captured["headers"] = headers
            return _FakeSyncResponse(
                202,
                {
                    "status": "accepted",
                    "message": "Sync started",
                    "triggered_at": "2026-03-12T01:00:00Z",
                    "lookback": 7,
                },
            )

    monkeypatch.setattr("app.routers.garmin.httpx.AsyncClient", _FakeClient)

    response = await client.post("/api/v1/garmin/sync?lookback=7")

    assert response.status_code == 202
    assert response.json()["lookback"] == 7
    assert captured["path"] == "/api/v1/sync"
    assert captured["params"] == {"lookback": 7}
    assert "X-Garmin-Sync-Id" in captured["headers"]


@pytest.mark.asyncio
async def test_trigger_sync_passthrough_resync_and_activity_filters(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    captured: dict = {}

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def __init__(self, *, base_url: str, timeout: float):
            captured["base_url"] = base_url
            captured["timeout"] = timeout

        async def post(self, path: str, params=None, headers=None):
            captured["path"] = path
            captured["params"] = params
            captured["headers"] = headers
            return _FakeSyncResponse(
                202,
                {
                    "status": "accepted",
                    "message": "Sync started",
                    "triggered_at": "2026-03-12T01:00:00Z",
                    "resync_existing": True,
                    "activity_ids": ["23157610603", "23157610604"],
                },
            )

    monkeypatch.setattr("app.routers.garmin.httpx.AsyncClient", _FakeClient)

    response = await client.post(
        "/api/v1/garmin/sync?resync_existing=true&activity_id=23157610603&activity_ids=23157610604"
    )

    assert response.status_code == 202
    assert response.json()["status"] == "accepted"
    assert captured["path"] == "/api/v1/sync"
    assert captured["params"] == {
        "resync_existing": "true",
        "activity_id": ["23157610603"],
        "activity_ids": ["23157610604"],
    }
    assert "X-Garmin-Sync-Id" in captured["headers"]


@pytest.mark.asyncio
async def test_trigger_sync_conflict_passthrough(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    class _FakeClient:
        def __init__(self, *, base_url: str, timeout: float):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, path: str, params=None, headers=None):
            return _FakeSyncResponse(
                409,
                {
                    "status": "conflict",
                    "message": "Sync already in progress",
                    "started_at": "2026-03-12T01:01:00Z",
                },
            )

    monkeypatch.setattr("app.routers.garmin.httpx.AsyncClient", _FakeClient)

    response = await client.post("/api/v1/garmin/sync")

    assert response.status_code == 409
    assert response.json()["status"] == "conflict"
    assert "started_at" in response.json()


@pytest.mark.asyncio
async def test_trigger_sync_rejects_mutually_exclusive_args(client: AsyncClient):
    response = await client.post("/api/v1/garmin/sync?lookback=1&window_hours=24")
    assert response.status_code == 400
    assert response.json()["status"] == "bad_request"
    assert response.json()["message"] == "lookback and window_hours cannot be combined"


@pytest.mark.asyncio
async def test_trigger_sync_timeout_maps_to_504(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    class _FakeClient:
        def __init__(self, *, base_url: str, timeout: float):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, path: str, params=None, headers=None):
            raise httpx.TimeoutException("timed out")

    monkeypatch.setattr("app.routers.garmin.httpx.AsyncClient", _FakeClient)

    response = await client.post("/api/v1/garmin/sync")
    assert response.status_code == 504
    assert response.json()["status"] == "error"
    assert response.json()["message"] == "Garmin sync service timed out"


@pytest.mark.asyncio
async def test_trigger_sync_unavailable_maps_to_503(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    class _FakeClient:
        def __init__(self, *, base_url: str, timeout: float):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, path: str, params=None, headers=None):
            raise httpx.HTTPError("connection failed")

    monkeypatch.setattr("app.routers.garmin.httpx.AsyncClient", _FakeClient)

    response = await client.post("/api/v1/garmin/sync")
    assert response.status_code == 503
    assert response.json()["status"] == "error"
    assert response.json()["message"] == "Garmin sync service unavailable"


@pytest.mark.asyncio
async def test_trigger_sync_invalid_upstream_json_maps_to_502(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    class _FakeClient:
        def __init__(self, *, base_url: str, timeout: float):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, path: str, params=None, headers=None):
            return _FakeSyncResponse(202, ValueError("invalid json"))

    monkeypatch.setattr("app.routers.garmin.httpx.AsyncClient", _FakeClient)

    response = await client.post("/api/v1/garmin/sync")
    assert response.status_code == 502
    assert response.json()["status"] == "error"
    assert response.json()["message"] == "Invalid response from Garmin sync service"


@pytest.mark.asyncio
async def test_trigger_sync_upstream_error_maps_to_502(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    class _FakeClient:
        def __init__(self, *, base_url: str, timeout: float):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, path: str, params=None, headers=None):
            return _FakeSyncResponse(500, {"status": "error", "message": "internal error"})

    monkeypatch.setattr("app.routers.garmin.httpx.AsyncClient", _FakeClient)

    response = await client.post("/api/v1/garmin/sync")
    assert response.status_code == 502
    assert response.json()["status"] == "error"
    assert response.json()["message"] == "Garmin sync service error"


@pytest.mark.asyncio
async def test_trigger_sync_generates_sync_id_when_no_header(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    """sync_id is auto-generated as UUID when X-Garmin-Sync-Id header is absent."""
    captured: dict = {}

    class _FakeClient:
        def __init__(self, *, base_url: str, timeout: float):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, path: str, params=None, headers=None):
            captured["headers"] = headers
            return _FakeSyncResponse(
                202,
                {"status": "accepted", "message": "Sync started", "triggered_at": "2026-03-12T01:00:00Z"},
            )

    monkeypatch.setattr("app.routers.garmin.httpx.AsyncClient", _FakeClient)

    response = await client.post("/api/v1/garmin/sync")

    assert response.status_code == 202
    sync_id = captured["headers"]["X-Garmin-Sync-Id"]
    # Validate it's a valid UUID (36 chars with dashes)
    assert len(sync_id) == 36
    assert sync_id.count("-") == 4


@pytest.mark.asyncio
async def test_trigger_sync_forwards_provided_sync_id(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    """When X-Garmin-Sync-Id header is provided, it is forwarded to upstream."""
    captured: dict = {}

    class _FakeClient:
        def __init__(self, *, base_url: str, timeout: float):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, path: str, params=None, headers=None):
            captured["headers"] = headers
            return _FakeSyncResponse(
                202,
                {"status": "accepted", "message": "Sync started", "triggered_at": "2026-03-12T01:00:00Z"},
            )

    monkeypatch.setattr("app.routers.garmin.httpx.AsyncClient", _FakeClient)

    provided_id = "my-custom-sync-id-123"
    response = await client.post(
        "/api/v1/garmin/sync",
        headers={"X-Garmin-Sync-Id": provided_id},
    )

    assert response.status_code == 202
    assert captured["headers"]["X-Garmin-Sync-Id"] == provided_id


@pytest.mark.asyncio
async def test_garmin_date_range_returns_min_max(client: AsyncClient, mock_db):
    mock_db.fetchrow.return_value = {
        "min_date": "2025-11-08T18:21:13+00:00",
        "max_date": "2026-04-06T20:00:00+00:00",
    }

    response = await client.get("/api/v1/garmin/date-range")

    assert response.status_code == 200
    data = response.json()
    assert "min_date" in data
    assert "max_date" in data
    assert "2025-11-08" in data["min_date"]
    assert "2026-04-06" in data["max_date"]
    query = mock_db.fetchrow.await_args.args[0]
    assert "MIN(start_time)" in query
    assert "MAX(start_time)" in query
    assert "FROM public.garmin_activities" in query


@pytest.mark.asyncio
async def test_garmin_date_range_empty_database(client: AsyncClient, mock_db):
    mock_db.fetchrow.return_value = {"min_date": None, "max_date": None}

    response = await client.get("/api/v1/garmin/date-range")

    assert response.status_code == 404
    assert response.json() == {"detail": "No Garmin activity data found"}
    query = mock_db.fetchrow.await_args.args[0]
    assert "MIN(start_time)" in query
    assert "MAX(start_time)" in query
    assert "FROM public.garmin_activities" in query


# ---------------------------------------------------------------------------
# Address-aware track points + per-activity addresses endpoint
# ---------------------------------------------------------------------------


def _track_row_with_address(activity_id: str = "20932993811") -> dict:
    base = _track_row(activity_id)
    base.update(
        {
            "display_address": "Pier 13, Hoboken, NJ",
            "street": "Sinatra Drive",
            "housenumber": "1301",
            "neighbourhood": "Waterfront",
            "locality": "Hoboken",
            "region": "New Jersey",
            "country": "United States",
            "postalcode": "07030",
            "confidence": 0.92,
            "waypoint_kind": "start",
            "address_status": "success",
            "geocoded_at": "2026-02-12T08:10:55+00:00",
        }
    )
    return base


@pytest.mark.asyncio
async def test_list_track_points_includes_address_when_present(client: AsyncClient, mock_db):
    mock_db.fetchval.side_effect = [1, 1]
    mock_db.fetch.return_value = [_track_row_with_address()]

    response = await client.get("/api/v1/garmin/activities/20932993811/tracks")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["address"] is not None
    assert item["address"]["display_address"] == "Pier 13, Hoboken, NJ"
    assert item["address"]["street"] == "Sinatra Drive"
    assert item["address"]["housenumber"] == "1301"
    assert item["address"]["neighbourhood"] == "Waterfront"
    assert item["address"]["postalcode"] == "07030"
    assert item["address"]["confidence"] == 0.92
    assert item["address"]["waypoint_kind"] == "start"
    assert item["address"]["status"] == "success"
    assert item["address"]["geocoded_at"] == "2026-02-12T08:10:55Z"


@pytest.mark.asyncio
async def test_list_track_points_address_null_when_missing(client: AsyncClient, mock_db):
    mock_db.fetchval.side_effect = [1, 1]
    mock_db.fetch.return_value = [_track_row()]

    response = await client.get("/api/v1/garmin/activities/20932993811/tracks")

    assert response.status_code == 200
    assert response.json()["items"][0]["address"] is None


@pytest.mark.asyncio
async def test_list_activity_addresses_returns_ordered_list(client: AsyncClient, mock_db):
    mock_db.fetchval.return_value = 1
    mock_db.fetch.return_value = [
        {
            "track_point_id": 1,
            "activity_id": "20932993811",
            "waypoint_kind": "start",
            "timestamp": "2025-11-08T18:21:13+00:00",
            "latitude": 40.715,
            "longitude": -74.017,
            "display_address": "Start Plaza",
            "street": "Main St",
            "housenumber": "1",
            "neighbourhood": "Downtown",
            "locality": "Hoboken",
            "region": "New Jersey",
            "country": "United States",
            "postalcode": "07030",
            "confidence": 0.9,
            "status": "success",
            "geocoded_at": "2026-02-12T08:10:55+00:00",
        },
        {
            "track_point_id": 99,
            "activity_id": "20932993811",
            "waypoint_kind": "end",
            "timestamp": "2025-11-08T19:00:00+00:00",
            "latitude": 40.72,
            "longitude": -74.02,
            "display_address": "End Plaza",
            "street": None,
            "housenumber": None,
            "neighbourhood": None,
            "locality": "Hoboken",
            "region": "New Jersey",
            "country": "United States",
            "postalcode": None,
            "confidence": None,
            "status": "success",
            "geocoded_at": "2026-02-12T08:11:00+00:00",
        },
    ]

    response = await client.get("/api/v1/garmin/activities/20932993811/addresses")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert body[0]["waypoint_kind"] == "start"
    assert body[1]["waypoint_kind"] == "end"
    query = mock_db.fetch.await_args.args[0]
    assert "ga.source = 'garmin'" in query
    # Addresses are ordered by waypoint kind (start, waypoint, end), then timestamp.
    assert "CASE ga.waypoint_kind" in query
    assert "'start' THEN 0" in query
    assert "'waypoint' THEN 1" in query
    assert "'end' THEN 2" in query
    assert "gtp.timestamp ASC" in query


@pytest.mark.asyncio
async def test_list_activity_addresses_not_found(client: AsyncClient, mock_db):
    mock_db.fetchval.return_value = None

    response = await client.get("/api/v1/garmin/activities/missing/addresses")

    assert response.status_code == 404
    assert response.json() == {"detail": "Activity not found"}


# ---------------------------------------------------------------------------
# Dense per-point cell address (geocoded_point_cells) — cell-first precedence
# ---------------------------------------------------------------------------


def _track_row_with_cell_address(activity_id: str = "20932993811") -> dict:
    """Row with only the dense-cell address columns populated (no waypoint row)."""
    base = _track_row(activity_id)
    base.update(
        {
            # No waypoint join match -> all NULL
            "display_address": None,
            "street": None,
            "housenumber": None,
            "neighbourhood": None,
            "locality": None,
            "region": None,
            "country": None,
            "postalcode": None,
            "confidence": None,
            "waypoint_kind": None,
            "address_status": None,
            "geocoded_at": None,
            # Dense cell join match
            "cell_display_address": "501 Sinatra Dr, Hoboken, NJ",
            "cell_street": "Sinatra Drive",
            "cell_housenumber": "501",
            "cell_neighbourhood": "Waterfront",
            "cell_locality": "Hoboken",
            "cell_region": "New Jersey",
            "cell_country": "United States",
            "cell_postalcode": "07030",
            "cell_confidence": 0.88,
            "cell_status": "success",
            "cell_geocoded_at": "2026-02-13T09:00:00+00:00",
        }
    )
    return base


@pytest.mark.asyncio
async def test_list_track_points_uses_cell_address_when_present(client: AsyncClient, mock_db):
    mock_db.fetchval.side_effect = [1, 1]
    mock_db.fetch.return_value = [_track_row_with_cell_address()]

    response = await client.get("/api/v1/garmin/activities/20932993811/tracks")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["address"] is not None
    assert item["address"]["display_address"] == "501 Sinatra Dr, Hoboken, NJ"
    assert item["address"]["status"] == "success"
    # Cell-source addresses never carry a waypoint_kind.
    assert item["address"]["waypoint_kind"] is None
    assert item["address"]["geocoded_at"] == "2026-02-13T09:00:00Z"
    # Query must include the dense cell LEFT JOIN.
    query = mock_db.fetch.await_args.args[0]
    assert "geocoded_point_cells" in query
    assert "ROUND(gtp.latitude * 10000)" in query


@pytest.mark.asyncio
async def test_cell_overrides_waypoint_when_both_present(client: AsyncClient, mock_db):
    """When both cell and waypoint rows exist, cell wins (denser source)."""
    row = _track_row_with_address()  # has waypoint_kind='start' + display_address
    row.update(
        {
            "cell_display_address": "Cell Address Wins",
            "cell_street": None,
            "cell_housenumber": None,
            "cell_neighbourhood": None,
            "cell_locality": None,
            "cell_region": None,
            "cell_country": None,
            "cell_postalcode": None,
            "cell_confidence": 0.5,
            "cell_status": "success",
            "cell_geocoded_at": "2026-02-13T09:00:00+00:00",
        }
    )
    mock_db.fetchval.side_effect = [1, 1]
    mock_db.fetch.return_value = [row]

    response = await client.get("/api/v1/garmin/activities/20932993811/tracks")

    assert response.status_code == 200
    addr = response.json()["items"][0]["address"]
    assert addr["display_address"] == "Cell Address Wins"
    # waypoint_kind from the waypoint row is dropped because cell wins.
    assert addr["waypoint_kind"] is None


@pytest.mark.asyncio
async def test_pending_cell_does_not_hide_waypoint_address(client: AsyncClient, mock_db):
    """A non-success cell row (pending/error/no_coverage) must not hide a successful waypoint address."""
    row = _track_row_with_address()  # waypoint_kind='start', display_address set, status='success'
    row.update(
        {
            "cell_display_address": None,
            "cell_street": None,
            "cell_housenumber": None,
            "cell_neighbourhood": None,
            "cell_locality": None,
            "cell_region": None,
            "cell_country": None,
            "cell_postalcode": None,
            "cell_confidence": None,
            "cell_status": "pending",
            "cell_geocoded_at": None,
        }
    )
    mock_db.fetchval.side_effect = [1, 1]
    mock_db.fetch.return_value = [row]

    response = await client.get("/api/v1/garmin/activities/20932993811/tracks")

    assert response.status_code == 200
    addr = response.json()["items"][0]["address"]
    # Waypoint address survives because cell is not 'success'.
    assert addr["display_address"] == row["display_address"]
    assert addr["waypoint_kind"] == "start"
    assert addr["status"] == "success"
