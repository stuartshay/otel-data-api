"""Tests for the geocoding management endpoints."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from starlette import status as http_status

from app import create_app
from app.auth import require_auth
from app.config import Config


@pytest.mark.asyncio
async def test_geocoding_status(client: AsyncClient, mock_db: AsyncMock):
    # Order: total, geocoded, ot_success, ot_pending, ot_no_coverage, ot_errors,
    # g_success, g_pending, g_no_coverage, g_errors, activities_total, activities_geocoded
    mock_db.fetchval.side_effect = [1000, 600, 550, 30, 10, 10, 80, 5, 4, 1, 25, 12]

    response = await client.get("/api/v1/geocoding/status")

    assert response.status_code == 200
    body = response.json()
    assert body["total_locations"] == 1000
    assert body["geocoded"] == 600
    assert body["success"] == 550
    assert body["pending"] == 30
    assert body["no_coverage"] == 10
    assert body["errors"] == 10
    assert body["coverage_percent"] == 60.0
    assert body["by_source"]["owntracks"]["success"] == 550
    assert body["by_source"]["owntracks"]["total"] == 600
    assert body["by_source"]["garmin"]["success"] == 80
    assert body["by_source"]["garmin"]["total"] == 90
    assert body["by_source"]["garmin_activities_total"] == 25
    assert body["by_source"]["garmin_activities_geocoded"] == 12
    assert body["by_source"]["garmin_coverage_percent"] == 48.0


@pytest.mark.asyncio
async def test_geocoding_status_empty_database(client: AsyncClient, mock_db: AsyncMock):
    mock_db.fetchval.side_effect = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]

    response = await client.get("/api/v1/geocoding/status")

    assert response.status_code == 200
    body = response.json()
    assert body["total_locations"] == 0
    assert body["coverage_percent"] == 0.0
    assert body["by_source"]["garmin_coverage_percent"] == 0.0


@pytest.mark.asyncio
async def test_trigger_geocoding_no_pending(client: AsyncClient, mock_db: AsyncMock):
    mock_db.fetch.return_value = []
    mock_db.fetchval.return_value = 0

    response = await client.post("/api/v1/geocoding/trigger")

    assert response.status_code == 200
    body = response.json()
    assert body["processed"] == 0
    assert body["remaining"] == 0
    assert body["skipped_dedup"] == 0


@pytest.mark.asyncio
async def test_trigger_geocoding_pelias_success(client: AsyncClient, mock_db: AsyncMock):
    mock_db.fetch.return_value = [
        {"id": 1, "latitude": 40.7128, "longitude": -74.006},
    ]
    mock_db.fetchrow.return_value = None  # no nearby neighbour
    mock_db.fetchval.return_value = 5  # remaining

    pelias_response = {
        "features": [
            {
                "properties": {
                    "label": "123 Main St, New York, NY",
                    "street": "Main St",
                    "housenumber": "123",
                    "neighbourhood": "Downtown",
                    "locality": "New York",
                    "region": "New York",
                    "country": "United States",
                    "postalcode": "10001",
                    "confidence": 0.95,
                }
            }
        ]
    }

    mock_httpx_response = MagicMock()
    mock_httpx_response.json.return_value = pelias_response
    mock_httpx_response.raise_for_status = MagicMock()

    with patch("app.routers.geocoding.httpx.AsyncClient") as mock_client_cls:
        mock_client_instance = AsyncMock()
        mock_client_instance.get.return_value = mock_httpx_response
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client_instance

        response = await client.post("/api/v1/geocoding/trigger?batch_size=1")

    assert response.status_code == 200
    body = response.json()
    assert body["processed"] == 1
    assert body["remaining"] == 5

    # Verify raw_response is serialized as a JSON string (not a dict)
    execute_calls = mock_db.execute.call_args_list
    assert len(execute_calls) >= 1
    upsert_args = execute_calls[0][0]
    # raw_response is the last positional arg in the INSERT
    raw_response_arg = upsert_args[-1]
    assert isinstance(raw_response_arg, str)
    assert '"features"' in raw_response_arg


@pytest.mark.asyncio
async def test_trigger_geocoding_pelias_no_features(client: AsyncClient, mock_db: AsyncMock):
    mock_db.fetch.return_value = [
        {"id": 2, "latitude": 0.0, "longitude": 0.0},
    ]
    mock_db.fetchrow.return_value = None  # no nearby neighbour
    mock_db.fetchval.return_value = 100  # remaining

    pelias_response: dict[str, list[object]] = {"features": []}
    mock_httpx_response = MagicMock()
    mock_httpx_response.json.return_value = pelias_response
    mock_httpx_response.raise_for_status = MagicMock()

    with patch("app.routers.geocoding.httpx.AsyncClient") as mock_client_cls:
        mock_client_instance = AsyncMock()
        mock_client_instance.get.return_value = mock_httpx_response
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client_instance

        response = await client.post("/api/v1/geocoding/trigger?batch_size=1")

    assert response.status_code == 200
    body = response.json()
    assert body["processed"] == 1
    # Verify _upsert_geocoded was called with no_coverage status
    assert mock_db.execute.call_count >= 1


@pytest.mark.asyncio
async def test_trigger_geocoding_dedup_from_neighbour(client: AsyncClient, mock_db: AsyncMock):
    mock_db.fetch.return_value = [
        {"id": 3, "latitude": 40.7128, "longitude": -74.006},
    ]
    mock_db.fetchval.return_value = 50  # remaining
    mock_db.fetchrow.return_value = {
        "display_address": "123 Main St",
        "street": "Main St",
        "housenumber": "123",
        "neighbourhood": "Downtown",
        "locality": "New York",
        "region": "NY",
        "country": "US",
        "postalcode": "10001",
        "confidence": 0.9,
        "raw_response": {},
    }

    response = await client.post("/api/v1/geocoding/trigger?batch_size=1")

    assert response.status_code == 200
    body = response.json()
    assert body["skipped_dedup"] == 1
    assert body["processed"] == 0


@pytest.mark.asyncio
async def test_trigger_geocoding_requires_auth(
    app: FastAPI,
    client: AsyncClient,
):
    async def _deny_auth() -> dict:
        raise HTTPException(
            status_code=http_status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    app.dependency_overrides[require_auth] = _deny_auth
    try:
        response = await client.post("/api/v1/geocoding/trigger")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}


@pytest.mark.asyncio
async def test_trigger_geocoding_custom_batch_size(client: AsyncClient, mock_db: AsyncMock):
    mock_db.fetch.return_value = []
    mock_db.fetchval.return_value = 0

    response = await client.post("/api/v1/geocoding/trigger?batch_size=150")

    assert response.status_code == 200
    mock_db.fetch.assert_called_once()
    call_args = mock_db.fetch.call_args
    assert call_args[0][1] == 150  # batch_size parameter


@pytest.mark.asyncio
async def test_trigger_geocoding_batch_size_exceeds_public_limit(client: AsyncClient):
    """Authenticated endpoint rejects batch_size > 500."""
    response = await client.post("/api/v1/geocoding/trigger?batch_size=501")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_internal_trigger_accepts_large_batch_size(client: AsyncClient, mock_db: AsyncMock):
    """Internal endpoint still accepts batch_size > 200 (up to 1000)."""
    mock_db.fetch.return_value = []
    mock_db.fetchval.return_value = 0

    response = await client.post("/internal/geocoding/trigger?batch_size=500")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_trigger_geocoding_retry_failed(client: AsyncClient, mock_db: AsyncMock):
    mock_db.fetch.return_value = []
    mock_db.fetchval.return_value = 0

    response = await client.post("/api/v1/geocoding/trigger?retry_failed=true")

    assert response.status_code == 200
    # Verify the retry_failed query targets both no_coverage and error rows
    call_args = mock_db.fetch.call_args
    sql = call_args[0][0]
    assert "no_coverage" in sql
    assert "error" in sql


# --- Internal geocoding endpoint tests ---


@pytest.mark.asyncio
async def test_internal_trigger_no_auth_required(client: AsyncClient, mock_db: AsyncMock):
    """Internal endpoint should succeed without authentication."""
    mock_db.fetch.return_value = []
    mock_db.fetchval.return_value = 0

    response = await client.post("/internal/geocoding/trigger")

    assert response.status_code == 200
    body = response.json()
    assert body["processed"] == 0
    assert body["remaining"] == 0
    assert body["skipped_dedup"] == 0


@pytest.mark.asyncio
async def test_internal_trigger_retry_failed(client: AsyncClient, mock_db: AsyncMock):
    """Internal endpoint should support retry_failed query parameter."""
    mock_db.fetch.return_value = []
    mock_db.fetchval.return_value = 0

    response = await client.post("/internal/geocoding/trigger?retry_failed=true")

    assert response.status_code == 200
    call_args = mock_db.fetch.call_args
    sql = call_args[0][0]
    assert "no_coverage" in sql
    assert "error" in sql


@pytest.mark.asyncio
async def test_internal_trigger_happy_path(client: AsyncClient, mock_db: AsyncMock):
    """Internal endpoint should process locations via Pelias."""
    mock_db.fetch.return_value = [
        {"id": 10, "latitude": 40.7128, "longitude": -74.006},
    ]
    mock_db.fetchrow.return_value = None  # no nearby neighbour
    mock_db.fetchval.return_value = 3  # remaining

    pelias_response = {
        "features": [
            {
                "properties": {
                    "label": "456 Broadway, New York, NY",
                    "street": "Broadway",
                    "housenumber": "456",
                    "neighbourhood": "SoHo",
                    "locality": "New York",
                    "region": "New York",
                    "country": "United States",
                    "postalcode": "10012",
                    "confidence": 0.88,
                }
            }
        ]
    }

    mock_httpx_response = MagicMock()
    mock_httpx_response.json.return_value = pelias_response
    mock_httpx_response.raise_for_status = MagicMock()

    with patch("app.routers.geocoding.httpx.AsyncClient") as mock_client_cls:
        mock_client_instance = AsyncMock()
        mock_client_instance.get.return_value = mock_httpx_response
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client_instance

        response = await client.post("/internal/geocoding/trigger?batch_size=1")

    assert response.status_code == 200
    body = response.json()
    assert body["processed"] == 1
    assert body["remaining"] == 3


@pytest.mark.asyncio
async def test_trigger_geocoding_db_timeout_handled(client: AsyncClient, mock_db: AsyncMock):
    """Database TimeoutError per-location should not crash the entire batch."""
    mock_db.fetch.return_value = [
        {"id": 100, "latitude": 40.7128, "longitude": -74.006},
        {"id": 101, "latitude": 40.7130, "longitude": -74.007},
    ]
    mock_db.fetchrow.side_effect = [TimeoutError("query timed out"), None]
    mock_db.fetchval.return_value = 10  # remaining

    pelias_response = {
        "features": [
            {
                "properties": {
                    "label": "789 Park Ave",
                    "street": "Park Ave",
                    "housenumber": "789",
                    "neighbourhood": "Upper East Side",
                    "locality": "New York",
                    "region": "New York",
                    "country": "United States",
                    "postalcode": "10065",
                    "confidence": 0.92,
                }
            }
        ]
    }

    mock_httpx_response = MagicMock()
    mock_httpx_response.json.return_value = pelias_response
    mock_httpx_response.raise_for_status = MagicMock()

    with patch("app.routers.geocoding.httpx.AsyncClient") as mock_client_cls:
        mock_client_instance = AsyncMock()
        mock_client_instance.get.return_value = mock_httpx_response
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client_instance

        response = await client.post("/internal/geocoding/trigger?batch_size=2")

    assert response.status_code == 200
    body = response.json()
    # First location timed out (0, 0), second processed via Pelias (1, 0)
    assert body["processed"] == 1
    assert body["remaining"] == 10


@pytest.mark.asyncio
async def test_trigger_geocoding_unexpected_error_upserts_error_status(client: AsyncClient, mock_db: AsyncMock):
    """Non-timeout Exception per-location should upsert error status, not silently skip."""
    mock_db.fetch.return_value = [
        {"id": 200, "latitude": 40.7128, "longitude": -74.006},
        {"id": 201, "latitude": 40.7130, "longitude": -74.007},
    ]
    # First location raises unexpected error; second returns no neighbour
    mock_db.fetchrow.side_effect = [RuntimeError("unexpected"), None]
    mock_db.fetchval.return_value = 8  # remaining

    pelias_response = {
        "features": [
            {
                "properties": {
                    "label": "100 Main St",
                    "street": "Main St",
                    "housenumber": "100",
                    "neighbourhood": "Downtown",
                    "locality": "New York",
                    "region": "New York",
                    "country": "United States",
                    "postalcode": "10001",
                    "confidence": 0.9,
                }
            }
        ]
    }

    mock_httpx_response = MagicMock()
    mock_httpx_response.json.return_value = pelias_response
    mock_httpx_response.raise_for_status = MagicMock()

    with patch("app.routers.geocoding.httpx.AsyncClient") as mock_client_cls:
        mock_client_instance = AsyncMock()
        mock_client_instance.get.return_value = mock_httpx_response
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client_instance

        response = await client.post("/internal/geocoding/trigger?batch_size=2")

    assert response.status_code == 200
    body = response.json()
    # First location errored (0, 0) with error upsert, second processed via Pelias (1, 0)
    assert body["processed"] == 1
    assert body["remaining"] == 8

    # Verify error status was upserted for the failed location
    error_upsert_calls = [
        call
        for call in mock_db.execute.call_args_list
        if len(call.args) >= 3 and call.args[2] == "error" and call.args[1] == 200
    ]
    assert len(error_upsert_calls) == 1


@pytest.mark.asyncio
async def test_internal_trigger_disabled_by_config(config: Config, mock_db: AsyncMock):
    """Internal endpoint should return 404 when internal_endpoints_enabled is False."""
    from app.config import Config as ConfigCls

    disabled_config = ConfigCls(
        db_host=config.db_host,
        db_port=config.db_port,
        db_name=config.db_name,
        db_user=config.db_user,
        db_password=config.db_password,
        internal_endpoints_enabled=False,
    )
    disabled_app = create_app(disabled_config)
    disabled_app.state.db = mock_db

    transport = ASGITransport(app=disabled_app)
    async with AsyncClient(transport=transport, base_url="http://test") as disabled_client:
        response = await disabled_client.post("/internal/geocoding/trigger")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Garmin trigger + waypoint selector
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_garmin_no_activities(client: AsyncClient, mock_db: AsyncMock):
    mock_db.fetch.return_value = []
    mock_db.fetchval.return_value = 0

    app_obj = client._transport.app  # type: ignore[attr-defined]
    app_obj.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    try:
        response = await client.post("/api/v1/geocoding/trigger/garmin")
    finally:
        app_obj.dependency_overrides.pop(require_auth, None)

    assert response.status_code == 200
    body = response.json()
    assert body["processed"] == 0
    assert body["skipped_dedup"] == 0


@pytest.mark.asyncio
async def test_trigger_garmin_requires_auth(client: AsyncClient, mock_db: AsyncMock):
    app_obj = client._transport.app  # type: ignore[attr-defined]

    def _deny() -> None:
        raise HTTPException(status_code=http_status.HTTP_401_UNAUTHORIZED, detail="nope")

    app_obj.dependency_overrides[require_auth] = _deny
    try:
        response = await client.post("/api/v1/geocoding/trigger/garmin")
    finally:
        app_obj.dependency_overrides.pop(require_auth, None)

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_internal_trigger_garmin_no_activities(client: AsyncClient, mock_db: AsyncMock):
    mock_db.fetch.return_value = []
    mock_db.fetchval.return_value = 0

    response = await client.post("/internal/geocoding/trigger/garmin")

    assert response.status_code == 200
    assert response.json()["processed"] == 0

    # Activities without track points are excluded from selection and remaining count.
    selection_sql = mock_db.fetch.call_args[0][0]
    remaining_sql = mock_db.fetchval.call_args[0][0]
    assert "EXISTS" in selection_sql
    assert "garmin_track_points" in selection_sql
    assert "EXISTS" in remaining_sql
    assert "garmin_track_points" in remaining_sql


@pytest.mark.asyncio
async def test_internal_trigger_garmin_retry_failed_targets_error_and_no_coverage(
    client: AsyncClient, mock_db: AsyncMock
):
    """retry_failed=true should re-pick activities with no_coverage OR error waypoints."""
    mock_db.fetch.return_value = []
    mock_db.fetchval.return_value = 0

    response = await client.post("/internal/geocoding/trigger/garmin?retry_failed=true")

    assert response.status_code == 200
    selection_sql = mock_db.fetch.call_args[0][0]
    assert "no_coverage" in selection_sql
    assert "error" in selection_sql


@pytest.mark.asyncio
async def test_select_garmin_waypoints_picks_start_mid_end(mock_db: AsyncMock):
    from app.routers.geocoding import _select_garmin_waypoints

    mock_db.fetch.return_value = [
        {"id": 1, "latitude": 40.0, "longitude": -74.0, "timestamp": "t1", "distance_from_start_km": 0.0},
        {"id": 2, "latitude": 40.01, "longitude": -74.0, "timestamp": "t2", "distance_from_start_km": 0.5},
        {"id": 3, "latitude": 40.02, "longitude": -74.0, "timestamp": "t3", "distance_from_start_km": 1.2},
        {"id": 4, "latitude": 40.03, "longitude": -74.0, "timestamp": "t4", "distance_from_start_km": 2.5},
        {"id": 5, "latitude": 40.04, "longitude": -74.0, "timestamp": "t5", "distance_from_start_km": 3.0},
    ]

    result = await _select_garmin_waypoints(mock_db, "act-1", 1.0)

    kinds = [wp["waypoint_kind"] for wp in result]
    assert kinds[0] == "start"
    assert kinds[-1] == "end"
    assert "waypoint" in kinds
    # IDs 3 (1.2km) and 4 (2.5km) cross the 1km threshold from the previous waypoint.
    mid_ids = [wp["id"] for wp in result if wp["waypoint_kind"] == "waypoint"]
    assert mid_ids == [3, 4]


@pytest.mark.asyncio
async def test_select_garmin_waypoints_empty(mock_db: AsyncMock):
    from app.routers.geocoding import _select_garmin_waypoints

    mock_db.fetch.return_value = []
    result = await _select_garmin_waypoints(mock_db, "act-1", 1.0)
    assert result == []


@pytest.mark.asyncio
async def test_select_garmin_waypoints_decimal_distance(mock_db: AsyncMock):
    """asyncpg returns NUMERIC columns as Decimal; spacing_km is float — must not raise."""
    from decimal import Decimal

    from app.routers.geocoding import _select_garmin_waypoints

    mock_db.fetch.return_value = [
        {"id": 1, "latitude": 40.0, "longitude": -74.0, "timestamp": "t1", "distance_from_start_km": Decimal("0.0")},
        {"id": 2, "latitude": 40.01, "longitude": -74.0, "timestamp": "t2", "distance_from_start_km": Decimal("0.5")},
        {"id": 3, "latitude": 40.02, "longitude": -74.0, "timestamp": "t3", "distance_from_start_km": Decimal("1.2")},
        {"id": 4, "latitude": 40.03, "longitude": -74.0, "timestamp": "t4", "distance_from_start_km": Decimal("2.5")},
        {"id": 5, "latitude": 40.04, "longitude": -74.0, "timestamp": "t5", "distance_from_start_km": Decimal("3.0")},
    ]

    result = await _select_garmin_waypoints(mock_db, "act-1", 1.0)

    kinds = [wp["waypoint_kind"] for wp in result]
    assert kinds[0] == "start"
    assert kinds[-1] == "end"
    mid_ids = [wp["id"] for wp in result if wp["waypoint_kind"] == "waypoint"]
    assert mid_ids == [3, 4]


# ---------------------------------------------------------------------------
# Retry-mode safety: prior success rows must not be overwritten (issue #124)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_select_garmin_waypoints_retry_filters_to_error_and_no_coverage(mock_db: AsyncMock):
    """retry_failed=True must skip waypoints that are already success or absent."""
    from app.routers.geocoding import _select_garmin_waypoints

    track_rows = [
        {"id": 1, "latitude": 40.0, "longitude": -74.0, "timestamp": "t1", "distance_from_start_km": 0.0},
        {"id": 2, "latitude": 40.01, "longitude": -74.0, "timestamp": "t2", "distance_from_start_km": 0.5},
        {"id": 3, "latitude": 40.02, "longitude": -74.0, "timestamp": "t3", "distance_from_start_km": 1.2},
        {"id": 4, "latitude": 40.03, "longitude": -74.0, "timestamp": "t4", "distance_from_start_km": 2.5},
        {"id": 5, "latitude": 40.04, "longitude": -74.0, "timestamp": "t5", "distance_from_start_km": 3.0},
    ]
    status_rows = [
        {"garmin_track_point_id": 1, "status": "success"},
        {"garmin_track_point_id": 3, "status": "error"},
        {"garmin_track_point_id": 4, "status": "no_coverage"},
        {"garmin_track_point_id": 5, "status": "success"},
    ]
    mock_db.fetch.side_effect = [track_rows, status_rows]

    result = await _select_garmin_waypoints(mock_db, "act-1", 1.0, retry_failed=True)

    returned_ids = sorted(wp["id"] for wp in result)
    assert returned_ids == [3, 4], "Only error/no_coverage waypoints should be retried"


@pytest.mark.asyncio
async def test_select_garmin_waypoints_retry_no_match_returns_empty(mock_db: AsyncMock):
    """If every candidate waypoint is success, retry mode returns nothing — prevents demotion."""
    from app.routers.geocoding import _select_garmin_waypoints

    track_rows = [
        {"id": 1, "latitude": 40.0, "longitude": -74.0, "timestamp": "t1", "distance_from_start_km": 0.0},
        {"id": 2, "latitude": 40.04, "longitude": -74.0, "timestamp": "t2", "distance_from_start_km": 3.0},
    ]
    status_rows = [
        {"garmin_track_point_id": 1, "status": "success"},
        {"garmin_track_point_id": 2, "status": "success"},
    ]
    mock_db.fetch.side_effect = [track_rows, status_rows]

    result = await _select_garmin_waypoints(mock_db, "act-1", 1.0, retry_failed=True)
    assert result == []


@pytest.mark.asyncio
async def test_select_garmin_waypoints_non_retry_ignores_status(mock_db: AsyncMock):
    """Default (retry_failed=False) path must not issue the status query."""
    from app.routers.geocoding import _select_garmin_waypoints

    mock_db.fetch.return_value = [
        {"id": 1, "latitude": 40.0, "longitude": -74.0, "timestamp": "t1", "distance_from_start_km": 0.0},
        {"id": 2, "latitude": 40.04, "longitude": -74.0, "timestamp": "t2", "distance_from_start_km": 3.0},
    ]

    result = await _select_garmin_waypoints(mock_db, "act-1", 1.0)

    assert {wp["id"] for wp in result} == {1, 2}
    # Only one fetch call (track points); no follow-up status query in non-retry mode.
    assert mock_db.fetch.call_count == 1


@pytest.mark.asyncio
async def test_internal_trigger_garmin_retry_uses_rotation_order_by(client: AsyncClient, mock_db: AsyncMock):
    """retry_failed activity selection must rotate by least-recently-attempted, not activity_id."""
    mock_db.fetch.return_value = []
    mock_db.fetchval.return_value = 0

    response = await client.post("/internal/geocoding/trigger/garmin?retry_failed=true")

    assert response.status_code == 200
    selection_sql = mock_db.fetch.call_args_list[0][0][0]
    assert "MIN(ga.geocoded_at)" in selection_sql
    assert "ASC NULLS FIRST" in selection_sql
    # Must not rely on activity_id ordering (which caused starvation in issue #124).
    assert "ORDER BY a.activity_id" not in selection_sql


@pytest.mark.asyncio
async def test_internal_trigger_garmin_retry_remaining_counts_retry_backlog(client: AsyncClient, mock_db: AsyncMock):
    """In retry mode, remaining must reflect the error/no_coverage backlog, not the fresh queue."""
    mock_db.fetch.return_value = []
    mock_db.fetchval.return_value = 42

    response = await client.post("/internal/geocoding/trigger/garmin?retry_failed=true")

    assert response.status_code == 200
    body = response.json()
    assert body["remaining"] == 42
    remaining_sql = mock_db.fetchval.call_args[0][0]
    assert "no_coverage" in remaining_sql
    assert "error" in remaining_sql
    assert "ga.source = 'garmin'" in remaining_sql
