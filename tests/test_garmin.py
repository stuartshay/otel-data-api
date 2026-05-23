"""Tests for Garmin endpoints."""

from datetime import date

import httpx
import pytest
from httpx import AsyncClient

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
        "cadence": 80,
        "temperature_c": 18,
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

    query = mock_db.fetch.await_args.args[0]
    assert "garmin_track_points" in query
    assert "ORDER BY timestamp ASC" in query


@pytest.mark.asyncio
async def test_get_chart_data_not_found(client: AsyncClient, mock_db):
    mock_db.fetchval.return_value = None

    response = await client.get("/api/v1/garmin/activities/nonexistent/chart-data")

    assert response.status_code == 404
    assert response.json() == {"detail": "Activity not found"}


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
