"""Tests for Garmin endpoints."""

import dataclasses
from datetime import UTC, date, datetime, timedelta

import fastapi
import httpx
import pytest
import structlog
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError as PydanticValidationError

from app import create_app
from app.auth import require_auth
from app.config import Config
from app.models.garmin import SegmentEffortSeriesBin, SegmentEffortSeriesResponse


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


def _weather_row(activity_id: str = "20932993811", *, is_provisional: bool = False) -> dict:
    return {
        "activity_id": activity_id,
        "observed_at": "2026-03-08T20:00:00+00:00",
        "latitude": 40.7937,
        "longitude": -73.961,
        "temperature_c": 18.4,
        "apparent_temperature_c": 17.0,
        "relative_humidity_pct": 55.0,
        "precipitation_mm": 0.0,
        "rain_mm": 0.0,
        "snowfall_cm": 0.0,
        "cloud_cover_pct": 20.0,
        "wind_speed_kmh": 12.0,
        "wind_gusts_kmh": 20.0,
        "wind_direction_deg": 270.0,
        "surface_pressure_hpa": 1013.0,
        "weather_code": 1,
        "source": "forecast" if is_provisional else "archive",
        "is_provisional": is_provisional,
        "created_at": "2026-03-09T03:00:00+00:00",
        "updated_at": "2026-03-09T03:00:00+00:00",
    }


def _weather_hourly_row(activity_id: str = "20932993811", hour_index: int = 0, *, is_provisional: bool = False) -> dict:
    return {
        "activity_id": activity_id,
        "hour_index": hour_index,
        "observed_at": "2026-03-08T20:00:00+00:00",
        "latitude": 40.7937,
        "longitude": -73.961,
        "temperature_c": 18.4,
        "apparent_temperature_c": 17.0,
        "relative_humidity_pct": 55.0,
        "precipitation_mm": 0.0,
        "rain_mm": 0.0,
        "snowfall_cm": 0.0,
        "cloud_cover_pct": 20.0,
        "wind_speed_kmh": 12.0,
        "wind_gusts_kmh": 20.0,
        "wind_direction_deg": 270.0,
        "surface_pressure_hpa": 1013.0,
        "weather_code": 1,
        "source": "forecast" if is_provisional else "archive",
        "is_provisional": is_provisional,
        "created_at": "2026-03-09T03:00:00+00:00",
        "updated_at": "2026-03-09T03:00:00+00:00",
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


def _sensor_row(activity_id: str = "20932993811", device_index: int = 0) -> dict:
    return {
        "id": device_index + 1,
        "activity_id": activity_id,
        "device_index": device_index,
        "is_primary": device_index == 0,
        "device_type": "heart_rate" if device_index else None,
        "manufacturer": "garmin",
        "garmin_product": 4061 if device_index == 0 else None,
        "product_name": "Edge 540 Solar" if device_index == 0 else None,
        "serial_number": 3444454776 if device_index == 0 else 123456,
        "software_version": "27.14" if device_index == 0 else None,
        "hardware_version": None,
        "battery_status": "low" if device_index else None,
        "battery_voltage": 2.95 if device_index else None,
        "ant_network": "antplus" if device_index else None,
        "source_type": "antplus" if device_index else None,
        "created_at": "2026-07-19T03:00:00+00:00",
        "updated_at": "2026-07-19T03:00:00+00:00",
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
    """Invalid date_from returns FastAPI query validation error."""
    response = await client.get("/api/v1/garmin/activities?date_from=not-a-date")

    assert response.status_code == 422
    detail = response.json()["detail"][0]
    assert detail["loc"] == ["query", "date_from"]
    assert "valid date" in detail["msg"]


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
    detail = response.json()["detail"][0]
    assert detail["loc"] == ["query", "date_from"]
    assert "valid date" in detail["msg"]


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


@pytest.mark.asyncio
async def test_list_activity_sensors_success(client: AsyncClient, mock_db):
    mock_db.fetchval.return_value = 1
    mock_db.fetch.return_value = [_sensor_row(device_index=0), _sensor_row(device_index=1)]

    response = await client.get("/api/v1/garmin/activities/20932993811/sensors")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["activity_id"] == "20932993811"
    assert data[0]["device_index"] == 0
    assert data[0]["is_primary"] is True
    assert data[0]["product_name"] == "Edge 540 Solar"
    assert data[1]["is_primary"] is False
    assert data[1]["device_type"] == "heart_rate"
    assert data[1]["battery_status"] == "low"
    assert data[1]["battery_voltage"] == 2.95

    query = mock_db.fetch.await_args.args[0]
    assert "public.garmin_activity_sensors" in query
    assert "ORDER BY device_index ASC" in query


@pytest.mark.asyncio
async def test_list_activity_sensors_empty_for_existing_activity(client: AsyncClient, mock_db):
    mock_db.fetchval.return_value = 1
    mock_db.fetch.return_value = []

    response = await client.get("/api/v1/garmin/activities/20932993811/sensors")

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_activity_sensors_not_found(client: AsyncClient, mock_db):
    mock_db.fetchval.return_value = None

    response = await client.get("/api/v1/garmin/activities/nonexistent/sensors")

    assert response.status_code == 404
    assert response.json() == {"detail": "Activity not found"}


@pytest.mark.asyncio
async def test_get_activity_weather_success(client: AsyncClient, mock_db):
    mock_db.fetchval.return_value = 1
    mock_db.fetchrow.return_value = _weather_row()

    response = await client.get("/api/v1/garmin/activities/20932993811/weather")

    assert response.status_code == 200
    data = response.json()
    assert data["activity_id"] == "20932993811"
    assert data["temperature_c"] == 18.4
    assert data["wind_speed_kmh"] == 12.0
    assert data["weather_code"] == 1
    assert data["source"] == "archive"
    assert data["is_provisional"] is False

    query = mock_db.fetchrow.await_args.args[0]
    assert "public.garmin_activity_weather" in query


@pytest.mark.asyncio
async def test_get_activity_weather_provisional(client: AsyncClient, mock_db):
    mock_db.fetchval.return_value = 1
    mock_db.fetchrow.return_value = _weather_row(is_provisional=True)

    response = await client.get("/api/v1/garmin/activities/20932993811/weather")

    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "forecast"
    assert data["is_provisional"] is True


@pytest.mark.asyncio
async def test_get_activity_weather_not_backfilled_yet(client: AsyncClient, mock_db):
    mock_db.fetchval.return_value = 1
    mock_db.fetchrow.return_value = None

    response = await client.get("/api/v1/garmin/activities/20932993811/weather")

    assert response.status_code == 200
    assert response.json() is None


@pytest.mark.asyncio
async def test_get_activity_weather_not_found(client: AsyncClient, mock_db):
    mock_db.fetchval.return_value = None

    response = await client.get("/api/v1/garmin/activities/nonexistent/weather")

    assert response.status_code == 404
    assert response.json() == {"detail": "Activity not found"}


@pytest.mark.asyncio
async def test_list_activity_weather_hourly_success(client: AsyncClient, mock_db):
    mock_db.fetchval.return_value = 1
    mock_db.fetch.return_value = [
        _weather_hourly_row(hour_index=0),
        _weather_hourly_row(hour_index=1, is_provisional=True),
    ]

    response = await client.get("/api/v1/garmin/activities/20932993811/weather-hourly")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["hour_index"] == 0
    assert data[0]["source"] == "archive"
    assert data[1]["hour_index"] == 1
    assert data[1]["is_provisional"] is True

    query = mock_db.fetch.await_args.args[0]
    assert "public.garmin_activity_weather_hourly" in query
    assert "ORDER BY hour_index ASC" in query


@pytest.mark.asyncio
async def test_list_activity_weather_hourly_empty_for_existing_activity(client: AsyncClient, mock_db):
    mock_db.fetchval.return_value = 1
    mock_db.fetch.return_value = []

    response = await client.get("/api/v1/garmin/activities/20932993811/weather-hourly")

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_activity_weather_hourly_not_found(client: AsyncClient, mock_db):
    mock_db.fetchval.return_value = None

    response = await client.get("/api/v1/garmin/activities/nonexistent/weather-hourly")

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


def _segment_effort_row(activity_id: str, elapsed: float) -> dict:
    effort_start = datetime(2026, 7, 5, 10, 30, 0)
    return {
        "activity_id": activity_id,
        "sport": "cycling",
        "activity_start_time": datetime(2026, 7, 5, 10, 0, 0),
        "effort_start": effort_start,
        "effort_end": effort_start + timedelta(seconds=elapsed),
        "elapsed_seconds": elapsed,
        "distance_km": 0.51,
        "avg_speed_kmh": 18.2,
        "avg_heart_rate": 128,
        "max_heart_rate": 150,
    }


@pytest.mark.asyncio
async def test_segment_efforts_returns_ranked(client: AsyncClient, mock_db):
    mock_db.fetch.return_value = [
        _segment_effort_row("a-fast", 89.0),
        _segment_effort_row("a-slow", 130.0),
    ]

    response = await client.get(
        "/api/v1/garmin/segment-efforts"
        "?start_lat=40.79366846&start_lon=-73.96104321"
        "&end_lat=40.79002409&end_lon=-73.96422816"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["segment"] == {
        "start_lat": 40.79366846,
        "start_lon": -73.96104321,
        "end_lat": 40.79002409,
        "end_lon": -73.96422816,
        "tolerance_meters": 35,
    }
    assert [e["rank"] for e in body["items"]] == [1, 2]
    assert [e["activity_id"] for e in body["items"]] == ["a-fast", "a-slow"]
    assert body["items"][0]["elapsed_seconds"] == 89.0


@pytest.mark.asyncio
async def test_segment_efforts_keeps_multiple_laps_from_one_activity(client: AsyncClient, mock_db):
    """A single ride that laps the segment twice should surface as two efforts.

    Guards against the response layer collapsing rows by activity_id -- the
    SQL itself (not tested here, see live-DB verification) is what collapses
    GPS-ping bursts down to one row per real crossing while still returning
    every distinct lap.
    """
    mock_db.fetch.return_value = [
        _segment_effort_row("multi-lap-ride", 1098.0),
        _segment_effort_row("multi-lap-ride", 1199.0),
    ]

    response = await client.get(
        "/api/v1/garmin/segment-efforts"
        "?start_lat=40.79366846&start_lon=-73.96104321"
        "&end_lat=40.79002409&end_lon=-73.96422816"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert [e["activity_id"] for e in body["items"]] == ["multi-lap-ride", "multi-lap-ride"]
    assert [e["elapsed_seconds"] for e in body["items"]] == [1098.0, 1199.0]


@pytest.mark.asyncio
async def test_segment_efforts_query_and_params(client: AsyncClient, mock_db):
    mock_db.fetch.return_value = []

    response = await client.get(
        "/api/v1/garmin/segment-efforts"
        "?start_lat=40.79366846&start_lon=-73.96104321"
        "&end_lat=40.79002409&end_lon=-73.96422816"
        "&tolerance_meters=40&date_from=2024-01-01&date_to=2026-06-30&limit=25"
    )

    assert response.status_code == 200
    assert response.json() == {
        "segment": {
            "start_lat": 40.79366846,
            "start_lon": -73.96104321,
            "end_lat": 40.79002409,
            "end_lon": -73.96422816,
            "tolerance_meters": 40,
        },
        "total": 0,
        "items": [],
    }

    query, *params = mock_db.fetch.await_args.args
    assert "ST_DWithin(t.geog, seg.start_pt, seg.tol)" in query
    assert "ST_DWithin(t.geog, seg.end_pt, seg.tol)" in query
    # same-direction enforcement: the nearest later is_end crossing is found via
    # an ordered window pass (ROWS 1 FOLLOWING..UNBOUNDED, ORDER BY c_ts), not a
    # crossings-JOIN-crossings self-join (no index to drive it -- quadratic in
    # the number of crossings for segments crossed by many activities/laps)
    assert "ROWS BETWEEN 1 FOLLOWING AND UNBOUNDED FOLLOWING" in query
    assert "MIN(c_ts) FILTER (WHERE is_end)" in query
    assert "WHERE s.is_start" in query
    # a new crossing must start on a direct start-only -> end-only flip (and
    # the reverse), not just a >2min time gap -- otherwise a short/fast
    # point-to-point segment (start and end corridors far enough apart that
    # they never overlap, but close enough to finish in well under 2 minutes)
    # would have its start and end hits merged into one crossing, leaving no
    # separate start/end row to pair and silently dropping the effort
    assert "prev_is_start AND NOT prev_is_end AND is_end AND NOT is_start" in query
    assert "prev_is_end AND NOT prev_is_start AND is_start AND NOT is_end" in query
    # the "left both corridors in between" guarantee comes from the >2min gap
    # used to cluster crossings, not a per-pair check against the full track
    # (a correlated EXISTS re-scanning track_points was too slow in production)
    assert "EXISTS" not in query
    # stateless endpoint has no reference activity to compare direction
    # against, so the bearing CTE/join is omitted rather than computed unused
    assert "start_bearings" not in query
    # every qualifying lap is returned (not just the fastest per activity), so
    # repeated laps of a loop in one activity all show up
    assert "DISTINCT ON (activity_id)" not in query
    assert "DISTINCT ON (activity_id, crossing)" in query  # collapses GPS-ping bursts into one row per crossing
    assert "ORDER BY m.elapsed_seconds ASC" in query
    # $1..$5 = start_lon, start_lat, end_lon, end_lat, tolerance
    assert params[:5] == [-73.96104321, 40.79366846, -73.96422816, 40.79002409, 40]
    # default sport filter applied, then date range, then max_effort + limit
    assert "a.sport = $6" in query
    assert params[5] == "cycling"
    assert params[6] == date(2024, 1, 1)
    assert params[7] == date(2026, 6, 30)
    assert params[-1] == 25  # limit is the last bound parameter


@pytest.mark.asyncio
async def test_segment_efforts_all_sports_when_blank(client: AsyncClient, mock_db):
    mock_db.fetch.return_value = []

    response = await client.get(
        "/api/v1/garmin/segment-efforts?start_lat=40.79&start_lon=-73.96&end_lat=40.79&end_lon=-73.964&sport="
    )

    assert response.status_code == 200
    query, *params = mock_db.fetch.await_args.args
    assert "a.sport =" not in query
    assert "cycling" not in params


@pytest.mark.asyncio
async def test_segment_efforts_invalid_date(client: AsyncClient, mock_db):
    response = await client.get(
        "/api/v1/garmin/segment-efforts?start_lat=40.79&start_lon=-73.96&end_lat=40.79&end_lon=-73.964&date_from=nope"
    )

    assert response.status_code == 422
    detail = response.json()["detail"][0]
    assert detail["loc"] == ["query", "date_from"]
    assert "valid date" in detail["msg"]


@pytest.mark.asyncio
async def test_segment_efforts_requires_coordinates(client: AsyncClient, mock_db):
    response = await client.get("/api/v1/garmin/segment-efforts?start_lat=40.79")

    assert response.status_code == 422


def _segment_row(segment_id: int = 1, route: list[list[float]] | None = None) -> dict:
    return {
        "id": segment_id,
        "name": "Harlem Hill",
        "sport": "cycling",
        "start_latitude": 40.79366846,
        "start_longitude": -73.96104321,
        "end_latitude": 40.79002409,
        "end_longitude": -73.96422816,
        "distance_meters": 508.1,
        "match_tolerance_meters": 35.0,
        "source_activity_id": "23493313338",
        "source_lap_index": None,
        "source_climb_index": 0,
        "created_at": datetime(2026, 7, 6, 12, 0, 0),
        "updated_at": datetime(2026, 7, 6, 12, 0, 0),
        "route": route,
    }


@pytest.mark.asyncio
async def test_create_segment(client: AsyncClient, mock_db):
    mock_db.fetchrow.return_value = _segment_row(7)

    response = await client.post(
        "/api/v1/garmin/segments",
        json={
            "name": "Harlem Hill",
            "start_latitude": 40.79366846,
            "start_longitude": -73.96104321,
            "end_latitude": 40.79002409,
            "end_longitude": -73.96422816,
            "source_activity_id": "23493313338",
            "source_climb_index": 0,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == 7
    assert body["name"] == "Harlem Hill"
    assert body["match_tolerance_meters"] == 35.0
    query, *params = mock_db.fetchrow.await_args.args
    assert "INSERT INTO public.garmin_segments" in query
    assert params[0] == "Harlem Hill"


@pytest.mark.asyncio
async def test_list_segments(client: AsyncClient, mock_db):
    mock_db.fetch.return_value = [_segment_row(1), _segment_row(2)]

    response = await client.get("/api/v1/garmin/segments?sport=cycling")

    assert response.status_code == 200
    assert len(response.json()) == 2
    query, *params = mock_db.fetch.await_args.args
    assert "FROM public.garmin_segments" in query
    assert "garmin_sync_status IS DISTINCT FROM 'delete_pending'" in query
    assert "sport = $1" in query
    assert "ORDER BY created_at DESC" in query
    assert params == ["cycling"]


@pytest.mark.asyncio
async def test_list_segments_returns_route(client: AsyncClient, mock_db):
    route = [
        [40.79366846, -73.96104321],
        [40.79200000, -73.96250000],
        [40.79002409, -73.96422816],
    ]
    mock_db.fetch.return_value = [_segment_row(1, route=route)]

    response = await client.get("/api/v1/garmin/segments")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["route"] == route
    query, *_ = mock_db.fetch.await_args.args
    # Route is recovered server-side via a PostGIS LATERAL corridor slice.
    assert "LEFT JOIN LATERAL" in query
    assert "ST_DWithin" in query
    assert "ST_Simplify" in query


@pytest.mark.asyncio
async def test_segment_route_lateral_prefers_lap_boundaries(client: AsyncClient, mock_db):
    """Loop segments (start ~= end) must not collapse the route to a sliver.

    When the segment was saved from a recorded lap, the lap's own
    start_time/duration_seconds give exact slice boundaries -- no proximity
    matching, so no ambiguity for a loop where the start and end points are
    the same physical spot. Falls back to proximity-based crossing detection
    (clustered the same way _fetch_segment_efforts is) only when there's no
    lap index.
    """
    mock_db.fetch.return_value = [_segment_row(1)]

    response = await client.get("/api/v1/garmin/segments")

    assert response.status_code == 200
    query, *_ = mock_db.fetch.await_args.args
    assert "garmin_activity_laps" in query
    assert "al.lap_index = s.source_lap_index + 1" in query
    assert "make_interval(secs => al.duration_seconds" in query
    assert "COALESCE(lap_bounds.s_ts, proximity_bounds.s_ts)" in query
    # lap_bounds must not surface a row with a NULL boundary (which would
    # otherwise mix an exact lap start with a proximity-derived end, or drop
    # the slice even though the proximity fallback could have supplied one)
    assert "al.start_time IS NOT NULL" in query
    assert "al.duration_seconds IS NOT NULL" in query
    # proximity matching only kicks in when there's no usable lap boundary,
    # both for correctness (it's meant as a fallback, not a second opinion)
    # and to avoid the ST_DWithin scan entirely for lap-derived segments
    assert "WHERE NOT EXISTS (SELECT 1 FROM lap_bounds)" in query
    # the proximity fallback must cluster hits, not just take the first/MIN
    # start and MIN end proximity hit (that's what previously collapsed a
    # loop's start and end into a same-instant sliver)
    assert "prev_is_start AND NOT prev_is_end AND is_end AND NOT is_start" in query


@pytest.mark.asyncio
async def test_list_segments_null_route(client: AsyncClient, mock_db):
    mock_db.fetch.return_value = [_segment_row(1, route=None)]

    response = await client.get("/api/v1/garmin/segments")

    assert response.status_code == 200
    assert response.json()[0]["route"] is None


@pytest.mark.asyncio
async def test_get_segment_success(client: AsyncClient, mock_db):
    mock_db.fetchrow.return_value = _segment_row(3)

    response = await client.get("/api/v1/garmin/segments/3")

    assert response.status_code == 200
    assert response.json()["id"] == 3


@pytest.mark.asyncio
async def test_get_segment_returns_route(client: AsyncClient, mock_db):
    route = [[40.79366846, -73.96104321], [40.79002409, -73.96422816]]
    mock_db.fetchrow.return_value = _segment_row(3, route=route)

    response = await client.get("/api/v1/garmin/segments/3")

    assert response.status_code == 200
    assert response.json()["route"] == route
    query, *_ = mock_db.fetchrow.await_args.args
    assert "LEFT JOIN LATERAL" in query


@pytest.mark.asyncio
async def test_get_segment_not_found(client: AsyncClient, mock_db):
    mock_db.fetchrow.return_value = None

    response = await client.get("/api/v1/garmin/segments/999")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_segment_never_synced_hard_deletes(client: AsyncClient, mock_db):
    mock_db.fetchrow.return_value = {"garmin_segment_uuid": None}

    response = await client.delete("/api/v1/garmin/segments/3")

    assert response.status_code == 204
    executed = [call.args[0] for call in mock_db.execute.await_args_list]
    assert any("DELETE FROM public.garmin_segments" in sql for sql in executed)
    assert not any("delete_pending" in sql for sql in executed)


@pytest.mark.asyncio
async def test_delete_segment_synced_marks_delete_pending(client: AsyncClient, mock_db):
    mock_db.fetchrow.return_value = {"garmin_segment_uuid": "abc-uuid"}

    response = await client.delete("/api/v1/garmin/segments/1")

    assert response.status_code == 204
    executed = [call.args[0] for call in mock_db.execute.await_args_list]
    assert any("delete_pending" in sql for sql in executed)
    assert not any("DELETE FROM public.garmin_segments" in sql for sql in executed)


@pytest.mark.asyncio
async def test_delete_segment_not_found(client: AsyncClient, mock_db):
    mock_db.fetchrow.return_value = None

    response = await client.delete("/api/v1/garmin/segments/999")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_segment_efforts_uses_saved_coords(client: AsyncClient, mock_db):
    mock_db.fetchrow.return_value = {
        "sport": "cycling",
        "start_latitude": 40.79366846,
        "start_longitude": -73.96104321,
        "end_latitude": 40.79002409,
        "end_longitude": -73.96422816,
        "match_tolerance_meters": 40.0,
        "source_activity_id": None,
        "distance_meters": None,
    }
    mock_db.fetch.return_value = [
        _segment_effort_row("a-fast", 79.0),
        _segment_effort_row("a-slow", 130.0),
    ]

    response = await client.get("/api/v1/garmin/segments/5/efforts")

    assert response.status_code == 200
    body = response.json()
    assert body["segment"]["tolerance_meters"] == 40
    assert [e["rank"] for e in body["items"]] == [1, 2]
    efforts_query, *efforts_params = mock_db.fetch.await_args.args
    assert "ST_DWithin(t.geog, seg.start_pt, seg.tol)" in efforts_query
    # matching used the saved segment's coordinates and tolerance
    assert efforts_params[:5] == [-73.96104321, 40.79366846, -73.96422816, 40.79002409, 40.0]


@pytest.mark.asyncio
async def test_get_segment_efforts_applies_min_distance_from_saved_segment(client: AsyncClient, mock_db):
    """A loop segment's start and end corridors sit at the same physical spot,
    so a brief stop or pass-by near the trailhead alone satisfies the crossing
    pair despite covering almost none of the route. Filter those out using
    the segment's own recorded distance."""
    mock_db.fetchrow.return_value = {
        "sport": "cycling",
        "start_latitude": 40.79366846,
        "start_longitude": -73.96104321,
        "end_latitude": 40.79002409,
        "end_longitude": -73.96422816,
        "match_tolerance_meters": 40.0,
        "source_activity_id": None,
        "distance_meters": 6070.0,
    }
    mock_db.fetch.return_value = [_segment_effort_row("a-real-lap", 900.0)]

    response = await client.get("/api/v1/garmin/segments/5/efforts")

    assert response.status_code == 200
    efforts_query, *efforts_params = mock_db.fetch.await_args.args
    assert "m.distance_km >= " in efforts_query
    # 6070m * 0.7 (MIN_SEGMENT_DISTANCE_RATIO) = 4.249 km
    assert efforts_params[-2] == pytest.approx(4.249)


@pytest.mark.asyncio
async def test_get_segment_efforts_skips_min_distance_without_recorded_distance(client: AsyncClient, mock_db):
    """Segments saved before distance_meters was recorded (or without a
    resolvable route) must not have every effort rejected outright."""
    mock_db.fetchrow.return_value = {
        "sport": "cycling",
        "start_latitude": 40.79366846,
        "start_longitude": -73.96104321,
        "end_latitude": 40.79002409,
        "end_longitude": -73.96422816,
        "match_tolerance_meters": 40.0,
        "source_activity_id": None,
        "distance_meters": None,
    }
    mock_db.fetch.return_value = [_segment_effort_row("a-real-lap", 900.0)]

    response = await client.get("/api/v1/garmin/segments/5/efforts")

    assert response.status_code == 200
    efforts_query, *_efforts_params = mock_db.fetch.await_args.args
    assert "m.distance_km >= " not in efforts_query


@pytest.mark.asyncio
async def test_get_segment_efforts_rejects_reverse_direction(client: AsyncClient, mock_db):
    """Loop segments (start ~= end) must reject laps ridden the opposite way.

    The segment's own source_activity_id supplies the canonical direction of
    travel through the start corridor; efforts whose bearing differs by 90
    degrees or more are filtered out in the SQL, not merely deduplicated.
    """
    mock_db.fetchrow.side_effect = [
        {
            "sport": "cycling",
            "start_latitude": 40.707439882680774,
            "start_longitude": -74.03477042913437,
            "end_latitude": 40.707470728084445,
            "end_longitude": -74.03477034531534,
            "match_tolerance_meters": 35.0,
            "source_activity_id": "23541736805",
            "distance_meters": None,
        },
        {"bearing_deg": 197.5},
    ]
    mock_db.fetch.return_value = []

    response = await client.get("/api/v1/garmin/segments/7/efforts")

    assert response.status_code == 200
    bearing_query, *bearing_params = mock_db.fetchrow.await_args_list[1].args
    assert bearing_params[0] == "23541736805"

    efforts_query, *efforts_params = mock_db.fetch.await_args.args
    assert "start_bearings" in efforts_query
    assert "LEAST(" in efforts_query
    assert efforts_params[-1] == 197.5


@pytest.mark.asyncio
async def test_get_segment_efforts_skips_bearing_lookup_without_source_activity(client: AsyncClient, mock_db):
    mock_db.fetchrow.return_value = {
        "sport": "cycling",
        "start_latitude": 40.79366846,
        "start_longitude": -73.96104321,
        "end_latitude": 40.79002409,
        "end_longitude": -73.96422816,
        "match_tolerance_meters": 40.0,
        "source_activity_id": None,
        "distance_meters": None,
    }
    mock_db.fetch.return_value = []

    response = await client.get("/api/v1/garmin/segments/5/efforts")

    assert response.status_code == 200
    assert mock_db.fetchrow.await_count == 1  # no reference-bearing lookup fired
    efforts_query, *efforts_params = mock_db.fetch.await_args.args
    # no reference bearing to compare against, so the CTE (and its per-start
    # LATERAL lookup) is omitted rather than computed and ignored
    assert "start_bearings" not in efforts_query
    assert efforts_params[-1] == 100  # last param is still the limit, no bearing appended


@pytest.mark.asyncio
async def test_get_segment_efforts_not_found(client: AsyncClient, mock_db):
    mock_db.fetchrow.return_value = None

    response = await client.get("/api/v1/garmin/segments/999/efforts")

    assert response.status_code == 404


def _effort_series_bin_row(index: int, bins: int = 100, speed: float | None = 18.4, hr: int | None = 132) -> dict:
    return {
        "index": index,
        "fraction": (index + 0.5) / bins,
        "speed_kmh": speed,
        "heart_rate": hr,
    }


def _effort_series_batch_row(request_index: int, index: int, bins: int = 10) -> dict:
    return {
        "request_index": request_index,
        **_effort_series_bin_row(index, bins=bins),
    }


@pytest.mark.asyncio
async def test_effort_series_returns_gap_filled_bins(client: AsyncClient, mock_db):
    mock_db.fetchval.return_value = 1
    rows = [_effort_series_bin_row(index) for index in range(100)]
    rows[1] = _effort_series_bin_row(1, speed=None, hr=None)  # GPS gap bin survives as nulls
    rows[2] = _effort_series_bin_row(2, speed=19.1, hr=140)
    mock_db.fetch.return_value = rows

    response = await client.get(
        "/api/v1/garmin/segments/5/effort-series"
        "?activity_id=20932993811"
        "&effort_start=2026-07-05T10:30:00"
        "&effort_end=2026-07-05T10:32:00"
        "&bins=100"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["activity_id"] == "20932993811"
    assert body["bin_count"] == 100
    assert len(body["bins"]) == body["bin_count"]
    assert [b["index"] for b in body["bins"]] == list(range(100))
    assert body["bins"][0]["fraction"] == 0.005
    assert body["bins"][-1]["fraction"] == 0.995
    assert body["bins"][1]["speed_kmh"] is None
    assert body["bins"][1]["heart_rate"] is None
    assert body["bins"][2]["heart_rate"] == 140

    series_query, *series_params = mock_db.fetch.await_args.args
    assert "WIDTH_BUCKET" in series_query
    assert "GENERATE_SERIES" in series_query
    assert series_params == [
        "20932993811",
        datetime(2026, 7, 5, 10, 30, 0, tzinfo=UTC),
        datetime(2026, 7, 5, 10, 32, 0, tzinfo=UTC),
        100,
    ]


@pytest.mark.asyncio
async def test_effort_series_normalizes_timestamps_to_aware_utc(client: AsyncClient, mock_db):
    """Effort boundaries must bind as timezone-aware UTC datetimes.

    garmin_track_points.timestamp is TIMESTAMPTZ in the live database, and
    asyncpg interprets naive datetimes against the server session timezone,
    silently shifting the window. Naive inputs are UTC by convention;
    offset-bearing inputs are converted.
    """
    mock_db.fetchval.return_value = 1
    mock_db.fetch.return_value = []

    response = await client.get(
        "/api/v1/garmin/segments/5/effort-series"
        "?activity_id=20932993811"
        "&effort_start=2026-07-05T10:30:00"
        "&effort_end=2026-07-05T06:32:00-04:00"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["effort_start"] == "2026-07-05T10:30:00Z"
    assert body["effort_end"] == "2026-07-05T10:32:00Z"
    _, _, bound_start, bound_end, _ = mock_db.fetch.await_args.args
    assert bound_start == datetime(2026, 7, 5, 10, 30, 0, tzinfo=UTC)
    assert bound_end == datetime(2026, 7, 5, 10, 32, 0, tzinfo=UTC)
    assert bound_end.utcoffset() == timedelta(0)


@pytest.mark.asyncio
async def test_effort_series_distinguishes_laps_by_effort_start(client: AsyncClient, mock_db):
    """Two efforts from one activity (loop laps) must produce distinct queries."""
    mock_db.fetchval.return_value = 1
    mock_db.fetch.return_value = []

    for start, end in (
        ("2026-07-05T10:30:00", "2026-07-05T10:32:00"),
        ("2026-07-05T11:00:00", "2026-07-05T11:02:30"),
    ):
        response = await client.get(
            f"/api/v1/garmin/segments/5/effort-series?activity_id=multi-lap-ride&effort_start={start}&effort_end={end}"
        )
        assert response.status_code == 200

    first_args = mock_db.fetch.await_args_list[0].args
    second_args = mock_db.fetch.await_args_list[1].args
    assert first_args[1] == second_args[1] == "multi-lap-ride"
    assert first_args[2] != second_args[2]
    assert first_args[3] != second_args[3]


@pytest.mark.asyncio
async def test_effort_series_segment_not_found(client: AsyncClient, mock_db):
    mock_db.fetchval.return_value = None

    response = await client.get(
        "/api/v1/garmin/segments/999/effort-series"
        "?activity_id=20932993811"
        "&effort_start=2026-07-05T10:30:00"
        "&effort_end=2026-07-05T10:32:00"
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_effort_series_rejects_invalid_windows_and_bins(client: AsyncClient, mock_db):
    mock_db.fetchval.return_value = 1

    reversed_window = await client.get(
        "/api/v1/garmin/segments/5/effort-series"
        "?activity_id=20932993811"
        "&effort_start=2026-07-05T10:32:00"
        "&effort_end=2026-07-05T10:30:00"
    )
    assert reversed_window.status_code == 422

    bins_too_large = await client.get(
        "/api/v1/garmin/segments/5/effort-series"
        "?activity_id=20932993811"
        "&effort_start=2026-07-05T10:30:00"
        "&effort_end=2026-07-05T10:32:00&bins=1000"
    )
    assert bins_too_large.status_code == 422

    missing_activity = await client.get(
        "/api/v1/garmin/segments/5/effort-series?effort_start=2026-07-05T10:30:00&effort_end=2026-07-05T10:32:00"
    )
    assert missing_activity.status_code == 422


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("index", -1),
        ("fraction", 0),
        ("fraction", 1),
        ("speed_kmh", -0.1),
        ("heart_rate", 0),
    ],
)
def test_effort_series_bin_rejects_values_outside_contract(field: str, value: int | float):
    values = _effort_series_bin_row(0)
    values[field] = value

    with pytest.raises(PydanticValidationError):
        SegmentEffortSeriesBin(**values)


@pytest.mark.parametrize("bin_count", [9, 401])
def test_effort_series_response_rejects_bin_count_outside_contract(bin_count: int):
    with pytest.raises(PydanticValidationError):
        SegmentEffortSeriesResponse(
            activity_id="activity-1",
            effort_start=datetime(2026, 7, 5, 10, 30, tzinfo=UTC),
            effort_end=datetime(2026, 7, 5, 10, 32, tzinfo=UTC),
            bin_count=bin_count,
            bins=[],
        )


@pytest.mark.asyncio
async def test_effort_series_batch_returns_request_order_with_one_query(client: AsyncClient, mock_db):
    mock_db.fetchval.return_value = 1
    mock_db.fetch.return_value = [
        _effort_series_batch_row(request_index, index) for request_index in range(2) for index in range(10)
    ]

    response = await client.post(
        "/api/v1/garmin/segments/5/effort-series/batch",
        json={
            "bins": 10,
            "efforts": [
                {
                    "activity_id": "activity-a",
                    "effort_start": "2026-07-05T10:30:00",
                    "effort_end": "2026-07-05T10:32:00",
                },
                {
                    "activity_id": "activity-b",
                    "effort_start": "2026-07-05T07:00:00-04:00",
                    "effort_end": "2026-07-05T07:03:00-04:00",
                },
            ],
        },
    )

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["activity_id"] for item in items] == ["activity-a", "activity-b"]
    assert [len(item["bins"]) for item in items] == [10, 10]
    assert items[0]["effort_start"] == "2026-07-05T10:30:00Z"
    assert items[1]["effort_start"] == "2026-07-05T11:00:00Z"

    series_query, activity_ids, starts, ends, bins = mock_db.fetch.await_args.args
    assert "UNNEST" in series_query
    assert "GENERATE_SERIES" in series_query
    assert activity_ids == ["activity-a", "activity-b"]
    assert starts == [
        datetime(2026, 7, 5, 10, 30, tzinfo=UTC),
        datetime(2026, 7, 5, 11, 0, tzinfo=UTC),
    ]
    assert ends == [
        datetime(2026, 7, 5, 10, 32, tzinfo=UTC),
        datetime(2026, 7, 5, 11, 3, tzinfo=UTC),
    ]
    assert bins == 10
    assert mock_db.fetch.await_count == 1


@pytest.mark.asyncio
async def test_effort_series_batch_rejects_invalid_requests(client: AsyncClient, mock_db):
    empty = await client.post(
        "/api/v1/garmin/segments/5/effort-series/batch",
        json={"efforts": []},
    )
    assert empty.status_code == 422

    too_many = await client.post(
        "/api/v1/garmin/segments/5/effort-series/batch",
        json={
            "efforts": [
                {
                    "activity_id": f"activity-{index}",
                    "effort_start": "2026-07-05T10:30:00Z",
                    "effort_end": "2026-07-05T10:32:00Z",
                }
                for index in range(51)
            ]
        },
    )
    assert too_many.status_code == 422

    reversed_window = await client.post(
        "/api/v1/garmin/segments/5/effort-series/batch",
        json={
            "efforts": [
                {
                    "activity_id": "activity-a",
                    "effort_start": "2026-07-05T10:32:00Z",
                    "effort_end": "2026-07-05T10:30:00Z",
                }
            ]
        },
    )
    assert reversed_window.status_code == 422
    assert reversed_window.json()["detail"] == "efforts[0].effort_end must be after effort_start"
    mock_db.fetchval.assert_not_awaited()
    mock_db.fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_effort_series_batch_segment_not_found(client: AsyncClient, mock_db):
    mock_db.fetchval.return_value = None

    response = await client.post(
        "/api/v1/garmin/segments/999/effort-series/batch",
        json={
            "efforts": [
                {
                    "activity_id": "activity-a",
                    "effort_start": "2026-07-05T10:30:00Z",
                    "effort_end": "2026-07-05T10:32:00Z",
                }
            ]
        },
    )

    assert response.status_code == 404
    mock_db.fetch.assert_not_awaited()
