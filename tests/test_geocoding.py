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
    # geocoded_addresses and geocoded_point_cells status counts now come from
    # two GROUP BY queries (db.fetch); the remaining six scalars come from
    # db.fetchval in this order: total_locations, activities_total,
    # activities_geocoded, dense_total_cells, total_track_points,
    # covered_track_points.
    addr_rows = [
        {"source": "owntracks", "status": "success", "n": 550},
        {"source": "owntracks", "status": "pending", "n": 30},
        {"source": "owntracks", "status": "no_coverage", "n": 10},
        {"source": "owntracks", "status": "error", "n": 10},
        {"source": "garmin", "status": "success", "n": 80},
        {"source": "garmin", "status": "pending", "n": 5},
        {"source": "garmin", "status": "no_coverage", "n": 4},
        {"source": "garmin", "status": "error", "n": 1},
    ]
    cell_rows = [
        {"status": "success", "n": 3000},
        {"status": "pending", "n": 100},
        {"status": "no_coverage", "n": 50},
        {"status": "error", "n": 20},
    ]
    mock_db.fetch.side_effect = [addr_rows, cell_rows]
    mock_db.fetchval.side_effect = [
        1000,  # total locations
        25,  # garmin activities total
        12,  # garmin activities geocoded
        4500,  # dense_total_cells (mv)
        50000,  # total_track_points
        35000,  # covered_track_points
    ]

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
    assert body["dense_cells_total"] == 4500
    assert body["dense_cells_success"] == 3000
    assert body["dense_cells_pending"] == 100
    assert body["dense_cells_no_coverage"] == 50
    assert body["dense_cells_errors"] == 20
    assert body["dense_cells_geocoded"] == 3170
    assert body["dense_point_coverage_percent"] == 70.0
    # Guard against regressing dense_cells_total back to the slow
    # COUNT(DISTINCT ...) over garmin_track_points (migration 18 MV).
    fetchval_queries = [call.args[0] for call in mock_db.fetchval.await_args_list]
    assert any("mv_garmin_track_point_cells" in sql for sql in fetchval_queries)
    assert not any("COUNT(DISTINCT" in sql and "garmin_track_points" in sql for sql in fetchval_queries)


@pytest.mark.asyncio
async def test_geocoding_status_empty_database(client: AsyncClient, mock_db: AsyncMock):
    # Both GROUP BY queries return no rows; the six scalar counts are zero.
    mock_db.fetch.side_effect = [[], []]
    mock_db.fetchval.side_effect = [0] * 6

    response = await client.get("/api/v1/geocoding/status")

    assert response.status_code == 200
    body = response.json()
    assert body["total_locations"] == 0
    assert body["coverage_percent"] == 0.0
    assert body["by_source"]["garmin_coverage_percent"] == 0.0
    assert body["dense_cells_total"] == 0
    assert body["dense_cells_geocoded"] == 0
    assert body["dense_point_coverage_percent"] == 0.0


@pytest.mark.asyncio
async def test_geocoding_status_cached_within_ttl(client: AsyncClient, mock_db: AsyncMock):
    """A second /status call within the TTL is served from cache without re-querying."""
    addr_rows = [
        {"source": "owntracks", "status": "success", "n": 100},
        {"source": "garmin", "status": "success", "n": 50},
    ]
    cell_rows = [{"status": "success", "n": 200}]
    # Only enough side-effects for ONE computation — if caching is bypassed the
    # second request exhausts these and raises StopAsyncIteration.
    mock_db.fetch.side_effect = [addr_rows, cell_rows]
    mock_db.fetchval.side_effect = [1000, 10, 5, 300, 50000, 35000]

    first = await client.get("/api/v1/geocoding/status")
    second = await client.get("/api/v1/geocoding/status")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    # Underlying queries ran exactly once: 2 GROUP BY fetches + 6 scalars.
    assert mock_db.fetch.await_count == 2
    assert mock_db.fetchval.await_count == 6


@pytest.mark.asyncio
async def test_geocoding_status_cache_expires(client: AsyncClient, mock_db: AsyncMock):
    """After the TTL elapses the /status response is recomputed."""
    addr_rows = [{"source": "owntracks", "status": "success", "n": 100}]
    cell_rows = [{"status": "success", "n": 200}]
    mock_db.fetch.side_effect = [addr_rows, cell_rows, addr_rows, cell_rows]
    mock_db.fetchval.side_effect = [1000, 10, 5, 300, 50000, 35000] * 2

    now = [0.0]
    with patch("app.routers.geocoding.time.monotonic", side_effect=lambda: now[0]):
        await client.get("/api/v1/geocoding/status")
        assert mock_db.fetch.await_count == 2  # first computation
        now[0] = 1000.0  # advance well beyond the 60s TTL
        await client.get("/api/v1/geocoding/status")

    # Cache was stale, so the queries ran a second time.
    assert mock_db.fetch.await_count == 4
    assert mock_db.fetchval.await_count == 12


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
    mock_httpx_response.status_code = 200

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
    mock_httpx_response.status_code = 200

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
        "_dist": 5.0,
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
    # Verify the retry_failed query targets the retryable status set (no_coverage, error, pending)
    call_args = mock_db.fetch.call_args
    sql = call_args[0][0]
    statuses = call_args[0][2]
    assert "status = ANY" in sql
    assert "no_coverage" in statuses
    assert "error" in statuses
    assert "pending" in statuses


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
    statuses = call_args[0][2]
    assert "status = ANY" in sql
    assert "no_coverage" in statuses
    assert "error" in statuses
    assert "pending" in statuses


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
    mock_httpx_response.status_code = 200

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
    # The nearest-address lookup now issues up to two fetchrow calls (one per
    # source). Raise the timeout on the first neighbour lookup only, then return
    # None — robust to concurrent processing order and the new call count.
    _timeout_calls = {"n": 0}

    def _fetchrow_timeout(*_args: object, **_kwargs: object) -> None:
        _timeout_calls["n"] += 1
        if _timeout_calls["n"] == 1:
            raise TimeoutError("query timed out")
        return None

    mock_db.fetchrow.side_effect = _fetchrow_timeout
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
    mock_httpx_response.status_code = 200

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
    # First neighbour lookup raises an unexpected error; subsequent per-source
    # lookups return None. Call-counter form is robust to the two-query split
    # and concurrent location processing.
    _err_calls = {"n": 0}

    def _fetchrow_error(*_args: object, **_kwargs: object) -> None:
        _err_calls["n"] += 1
        if _err_calls["n"] == 1:
            raise RuntimeError("unexpected")
        return None

    mock_db.fetchrow.side_effect = _fetchrow_error
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
    mock_httpx_response.status_code = 200

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
    call_args = mock_db.fetch.call_args
    selection_sql = call_args[0][0]
    statuses = call_args[0][2]
    assert "status = ANY" in selection_sql
    assert "no_coverage" in statuses
    assert "error" in statuses
    assert "pending" in statuses


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
    """retry_failed=True must skip waypoints that are already success or have no prior row.

    Sampled candidates after 1km spacing are ids 1 (start), 3, 4, 5 (end). The status
    fixture omits id=4 entirely (absent prior row) and marks ids 1 and 5 as success,
    leaving only id=3 (error) as the legitimate retry target.
    """
    from app.routers.geocoding import _select_garmin_waypoints

    track_rows = [
        {"id": 1, "latitude": 40.0, "longitude": -74.0, "timestamp": "t1", "distance_from_start_km": 0.0},
        {"id": 2, "latitude": 40.01, "longitude": -74.0, "timestamp": "t2", "distance_from_start_km": 0.5},
        {"id": 3, "latitude": 40.02, "longitude": -74.0, "timestamp": "t3", "distance_from_start_km": 1.2},
        {"id": 4, "latitude": 40.03, "longitude": -74.0, "timestamp": "t4", "distance_from_start_km": 2.5},
        {"id": 5, "latitude": 40.04, "longitude": -74.0, "timestamp": "t5", "distance_from_start_km": 3.0},
    ]
    # Note: id=4 deliberately omitted to exercise the "absent prior row" branch.
    status_rows = [
        {"garmin_track_point_id": 1, "status": "success"},
        {"garmin_track_point_id": 3, "status": "error"},
        {"garmin_track_point_id": 5, "status": "success"},
    ]
    mock_db.fetch.side_effect = [track_rows, status_rows]

    result = await _select_garmin_waypoints(mock_db, "act-1", 1.0, retry_failed=True)

    returned_ids = sorted(wp["id"] for wp in result)
    assert returned_ids == [3], (
        "Only error/no_coverage waypoints should be retried; success and absent rows must be skipped"
    )


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
    remaining_statuses = mock_db.fetchval.call_args[0][1]
    assert "status = ANY" in remaining_sql
    assert "ga.source = 'garmin'" in remaining_sql
    assert "no_coverage" in remaining_statuses
    assert "error" in remaining_statuses
    assert "pending" in remaining_statuses


# --- Pelias transient-error / retry hardening tests ---


@pytest.mark.asyncio
async def test_call_pelias_retries_on_timeout_then_raises():
    """Three consecutive timeouts should raise PeliasTransientError."""
    import httpx

    from app.routers.geocoding import PeliasTransientError, _call_pelias

    client = AsyncMock()
    client.get = AsyncMock(side_effect=httpx.TimeoutException("boom"))

    with patch("app.routers.geocoding.asyncio.sleep", new=AsyncMock()), pytest.raises(PeliasTransientError):
        await _call_pelias(client, "http://pelias.test", 40.0, -74.0)

    assert client.get.await_count == 3


@pytest.mark.asyncio
async def test_call_pelias_retries_on_5xx_then_raises():
    """Three consecutive 5xx responses should raise PeliasTransientError."""
    from app.routers.geocoding import PeliasTransientError, _call_pelias

    bad = MagicMock()
    bad.status_code = 503
    bad.raise_for_status = MagicMock()

    client = AsyncMock()
    client.get = AsyncMock(return_value=bad)

    with patch("app.routers.geocoding.asyncio.sleep", new=AsyncMock()), pytest.raises(PeliasTransientError):
        await _call_pelias(client, "http://pelias.test", 40.0, -74.0)

    assert client.get.await_count == 3


@pytest.mark.asyncio
async def test_call_pelias_4xx_is_permanent_no_retry():
    """A 4xx response should return None (permanent) without retrying."""
    from app.routers.geocoding import _call_pelias

    bad = MagicMock()
    bad.status_code = 400
    bad.raise_for_status = MagicMock()

    client = AsyncMock()
    client.get = AsyncMock(return_value=bad)

    result = await _call_pelias(client, "http://pelias.test", 40.0, -74.0)
    assert result is None
    assert client.get.await_count == 1


@pytest.mark.asyncio
async def test_call_pelias_success_first_try():
    """A 2xx response with valid JSON should return parsed body on the first attempt."""
    from app.routers.geocoding import _call_pelias

    ok = MagicMock()
    ok.status_code = 200
    ok.raise_for_status = MagicMock()
    ok.json.return_value = {"features": [{"properties": {"label": "X"}}]}

    client = AsyncMock()
    client.get = AsyncMock(return_value=ok)

    result = await _call_pelias(client, "http://pelias.test", 40.0, -74.0)
    assert result == {"features": [{"properties": {"label": "X"}}]}
    assert client.get.await_count == 1


@pytest.mark.asyncio
async def test_pelias_health_endpoint_healthy(client: AsyncClient):
    """/pelias-health returns healthy=true when probe returns features."""
    ok = MagicMock()
    ok.status_code = 200
    ok.raise_for_status = MagicMock()
    ok.json.return_value = {"features": [{"properties": {"label": "Times Square"}}]}

    with patch("app.routers.geocoding.httpx.AsyncClient") as mock_async_client:
        instance = AsyncMock()
        instance.get = AsyncMock(return_value=ok)
        mock_async_client.return_value.__aenter__.return_value = instance

        response = await client.get("/api/v1/geocoding/pelias-health")

    assert response.status_code == 200
    body = response.json()
    assert body["healthy"] is True
    assert body["sample_features_count"] == 1
    assert body["detail"] is None


@pytest.mark.asyncio
async def test_pelias_health_endpoint_unhealthy_on_timeout(client: AsyncClient):
    """/pelias-health returns healthy=false when probe times out."""
    import httpx

    with patch("app.routers.geocoding.httpx.AsyncClient") as mock_async_client:
        instance = AsyncMock()
        instance.get = AsyncMock(side_effect=httpx.TimeoutException("slow"))
        mock_async_client.return_value.__aenter__.return_value = instance

        response = await client.get("/api/v1/geocoding/pelias-health")

    assert response.status_code == 200
    body = response.json()
    assert body["healthy"] is False
    assert body["sample_features_count"] == 0
    assert body["detail"] is not None
    assert "timeout" in body["detail"].lower()


# ---------------------------------------------------------------------------
# Perf optimization (#129): single-query retry selector + parallel activities
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_select_garmin_retry_waypoints_single_join_query(mock_db: AsyncMock):
    """retry-mode selector must use one JOIN query returning only retryable rows."""
    from app.routers.geocoding import _select_garmin_retry_waypoints

    mock_db.fetch.return_value = [
        {"id": 7, "latitude": 40.7, "longitude": -73.9, "waypoint_kind": "waypoint"},
        {"id": 11, "latitude": 40.71, "longitude": -73.91, "waypoint_kind": "start"},
    ]

    result = await _select_garmin_retry_waypoints(mock_db, "act-99")

    # Exactly ONE fetch call (no Python-side thinning, no second status query).
    assert mock_db.fetch.call_count == 1
    sql, activity_id, statuses = mock_db.fetch.call_args[0]
    assert "INNER JOIN public.garmin_track_points" in sql
    assert "ga.status = ANY" in sql
    assert "ORDER BY ga.geocoded_at ASC NULLS FIRST" in sql
    assert activity_id == "act-99"
    assert set(statuses) == {"no_coverage", "error", "pending"}

    assert [wp["id"] for wp in result] == [7, 11]
    assert [wp["waypoint_kind"] for wp in result] == ["waypoint", "start"]
    assert all(wp["activity_id"] == "act-99" for wp in result)


@pytest.mark.asyncio
async def test_select_garmin_retry_waypoints_empty(mock_db: AsyncMock):
    """No retryable rows -> empty list, still a single query."""
    from app.routers.geocoding import _select_garmin_retry_waypoints

    mock_db.fetch.return_value = []
    result = await _select_garmin_retry_waypoints(mock_db, "act-empty")
    assert result == []
    assert mock_db.fetch.call_count == 1


@pytest.mark.asyncio
async def test_select_garmin_retry_waypoints_defaults_waypoint_kind(mock_db: AsyncMock):
    """Legacy rows missing waypoint_kind default to 'waypoint' (not None)."""
    from app.routers.geocoding import _select_garmin_retry_waypoints

    mock_db.fetch.return_value = [
        {"id": 1, "latitude": 40.0, "longitude": -74.0, "waypoint_kind": None},
    ]
    result = await _select_garmin_retry_waypoints(mock_db, "act-1")
    assert result[0]["waypoint_kind"] == "waypoint"


@pytest.mark.asyncio
async def test_internal_trigger_garmin_retry_uses_single_query_selector(client: AsyncClient, mock_db: AsyncMock):
    """retry_failed=True must NOT issue the fresh-pass track-scan + status-filter pair.

    Confirms the trigger impl routes through `_select_garmin_retry_waypoints`
    (one fetch per activity) rather than `_select_garmin_waypoints` with
    retry_failed=True (which would issue two fetches per activity).
    """
    activity_selection = [{"activity_id": "act-1"}, {"activity_id": "act-2"}]
    retry_waypoints_by_activity = {
        "act-1": [
            {"id": 10, "latitude": 40.0, "longitude": -74.0, "waypoint_kind": "waypoint"},
        ],
        "act-2": [],
    }

    # act-1 and act-2 run concurrently, so any positional side_effect ordering
    # is racy. Dispatch on SQL content + bound activity_id parameter instead.
    def fetch_side_effect(*args: object, **_kwargs: object) -> list[dict]:
        sql = args[0] if args else ""
        assert isinstance(sql, str)
        if "FROM public.garmin_activities" in sql:
            return activity_selection
        if "INNER JOIN public.garmin_track_points" in sql and "ga.status = ANY" in sql:
            activity_id = args[1] if len(args) > 1 else None
            return retry_waypoints_by_activity.get(str(activity_id), [])
        if "ST_DWithin" in sql:
            return []  # _find_nearby_address candidate probes
        return []

    mock_db.fetch.side_effect = fetch_side_effect
    mock_db.fetchval.return_value = 0
    mock_db.fetchrow.return_value = None  # _find_nearby_address final lookup
    mock_db.execute.return_value = None

    with patch("app.routers.geocoding._call_pelias", AsyncMock(return_value=None)):
        response = await client.post("/internal/geocoding/trigger/garmin?retry_failed=true")

    assert response.status_code == 200
    # 5 fetch calls total: 1 selector + 2 retry-selectors + 2 _find_nearby_address candidate lookups.
    assert mock_db.fetch.call_count == 5
    # At least 2 calls must be the new single-query retry selector
    # (one per activity, not 2 per activity which would indicate the old path).
    retry_selector_calls = [
        c
        for c in mock_db.fetch.call_args_list
        if "INNER JOIN public.garmin_track_points" in c[0][0] and "ga.status = ANY" in c[0][0]
    ]
    assert len(retry_selector_calls) == 2


@pytest.mark.asyncio
async def test_concurrency_constants_increased_for_drain_throughput(mock_db: AsyncMock):
    """Guard against accidental reversion of the #129 throughput tuning."""
    from app.routers import geocoding

    assert geocoding.MAX_GEOCODE_CONCURRENCY >= 20, (
        "MAX_GEOCODE_CONCURRENCY must stay >= 20 to keep drain wall time <5min/batch"
    )
    assert geocoding.GARMIN_ACTIVITY_CONCURRENCY >= 2, (
        "GARMIN_ACTIVITY_CONCURRENCY must allow >= 2 activities in parallel"
    )


# ---------------------------------------------------------------------------
# _find_nearby_address — two-query split (#132)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_nearby_address_no_candidates_short_circuits(mock_db: AsyncMock):
    """Both GIST lookups empty → returns None without hitting fetchrow."""
    from app.routers.geocoding import _find_nearby_address

    mock_db.fetch.side_effect = [[], []]

    result = await _find_nearby_address(mock_db, lat=40.0, lon=-74.0)

    assert result is None
    assert mock_db.fetch.call_count == 2
    mock_db.fetchrow.assert_not_called()


@pytest.mark.asyncio
async def test_find_nearby_address_owntracks_only_hit(mock_db: AsyncMock):
    """Owntracks candidates only → only the owntracks lookup runs."""
    from app.routers.geocoding import _find_nearby_address

    address: dict = {
        "display_address": "1 Owntracks Way",
        "street": "Owntracks Way",
        "housenumber": "1",
        "neighbourhood": None,
        "locality": "NYC",
        "region": "NY",
        "country": "US",
        "postalcode": "10001",
        "confidence": 0.9,
        "raw_response": {},
    }
    mock_db.fetch.side_effect = [[{"id": 42}], []]
    mock_db.fetchrow.return_value = {**address, "_dist": 12.5}

    result = await _find_nearby_address(mock_db, lat=40.0, lon=-74.0)

    # The internal _dist ranking column must be stripped from the result.
    assert result == address
    # gt_ids is empty, so only the owntracks lookup runs.
    assert mock_db.fetchrow.call_count == 1
    final_call = mock_db.fetchrow.call_args
    sql = final_call[0][0]
    assert "ga.source = 'owntracks'" in sql
    assert "ga.location_id = ANY" in sql
    # Positional args: lon, lat, ow_ids
    assert final_call[0][1] == -74.0
    assert final_call[0][2] == 40.0
    assert final_call[0][3] == [42]


@pytest.mark.asyncio
async def test_find_nearby_address_garmin_only_hit(mock_db: AsyncMock):
    """Garmin candidates only → only the garmin lookup runs."""
    from app.routers.geocoding import _find_nearby_address

    address: dict = {
        "display_address": "5 Trail Rd",
        "street": "Trail Rd",
        "housenumber": "5",
        "neighbourhood": None,
        "locality": "NYC",
        "region": "NY",
        "country": "US",
        "postalcode": "10001",
        "confidence": 0.8,
        "raw_response": {},
    }
    mock_db.fetch.side_effect = [[], [{"id": 99}, {"id": 100}]]
    mock_db.fetchrow.return_value = {**address, "_dist": 7.0}

    result = await _find_nearby_address(mock_db, lat=40.0, lon=-74.0)

    assert result == address
    assert mock_db.fetchrow.call_count == 1
    final_call = mock_db.fetchrow.call_args
    sql = final_call[0][0]
    assert "ga.source = 'garmin'" in sql
    assert "ga.garmin_track_point_id = ANY" in sql
    # Positional args: lon, lat, gt_ids
    assert final_call[0][3] == [99, 100]


@pytest.mark.asyncio
async def test_find_nearby_address_both_sources_picks_nearest(mock_db: AsyncMock):
    """Both sources hit → the smaller _dist wins and two lookups run."""
    from app.routers.geocoding import _find_nearby_address

    base: dict = {
        "street": None,
        "housenumber": None,
        "neighbourhood": None,
        "locality": None,
        "region": None,
        "country": None,
        "postalcode": None,
        "raw_response": {},
    }
    ow = {**base, "display_address": "OW", "confidence": 0.9, "_dist": 30.0}
    gt = {**base, "display_address": "GT", "confidence": 0.8, "_dist": 5.0}
    mock_db.fetch.side_effect = [[{"id": 1}], [{"id": 2}]]
    mock_db.fetchrow.side_effect = [ow, gt]

    result = await _find_nearby_address(mock_db, lat=40.0, lon=-74.0)

    assert mock_db.fetchrow.call_count == 2
    assert result is not None
    assert result["display_address"] == "GT"  # nearer (smaller _dist)
    assert "_dist" not in result


@pytest.mark.asyncio
async def test_find_nearby_address_does_not_use_coalesce_query(mock_db: AsyncMock):
    """Guard against regression to the slow COALESCE/OR Seq Scan plan."""
    from app.routers.geocoding import _find_nearby_address

    mock_db.fetch.side_effect = [[{"id": 1}], [{"id": 2}]]
    mock_db.fetchrow.return_value = None

    await _find_nearby_address(mock_db, lat=40.0, lon=-74.0)

    for call in mock_db.fetch.call_args_list:
        sql = call[0][0]
        assert "COALESCE" not in sql, "Candidate lookup must hit GIST indexes directly — no COALESCE allowed."
        assert "ST_DWithin(geog" in sql
    # Each per-source final lookup filters via its indexed id column with ANY,
    # never via a COALESCE/OR across both columns (the old Seq Scan plan).
    assert mock_db.fetchrow.call_count == 2
    for call in mock_db.fetchrow.call_args_list:
        final_sql = call[0][0]
        assert "COALESCE" not in final_sql, "Final lookup must not seq-scan via COALESCE."
        assert "ANY" in final_sql
        assert "ST_DWithin" not in final_sql, "Final lookup must not re-filter by distance."


# ---------------------------------------------------------------------------
# Dense per-point cell geocoding tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_internal_trigger_garmin_dense_no_pending(client: AsyncClient, mock_db: AsyncMock):
    """No pending cells -> processed=0, remaining=0."""
    mock_db.fetch.return_value = []
    mock_db.fetchval.return_value = 0

    response = await client.post("/internal/geocoding/trigger/garmin-dense")

    assert response.status_code == 200
    body = response.json()
    assert body["processed"] == 0
    assert body["remaining"] == 0
    selection_sql = mock_db.fetch.call_args[0][0]
    assert "DISTINCT" in selection_sql
    assert "geocoded_point_cells" in selection_sql
    assert "ROUND(gtp.latitude * 10000)" in selection_sql


@pytest.mark.asyncio
async def test_internal_trigger_garmin_dense_happy_path(
    client: AsyncClient, mock_db: AsyncMock, monkeypatch: pytest.MonkeyPatch
):
    """Cells get reverse-geocoded and upserted with status=success."""
    from app.routers import geocoding as geo_mod

    mock_db.fetch.return_value = [
        {"lat_4dp": 405000, "lon_4dp": -740000},
        {"lat_4dp": 405001, "lon_4dp": -740001},
    ]
    mock_db.fetchval.return_value = 5  # remaining

    async def _fake_pelias(client, base, lat, lon):
        return {
            "features": [
                {
                    "properties": {
                        "label": "1 Main St, NYC",
                        "street": "Main St",
                        "housenumber": "1",
                        "neighbourhood": "Downtown",
                        "locality": "NYC",
                        "region": "NY",
                        "country": "USA",
                        "postalcode": "10001",
                        "confidence": 0.9,
                    }
                }
            ]
        }

    monkeypatch.setattr(geo_mod, "_call_pelias", _fake_pelias)

    response = await client.post("/internal/geocoding/trigger/garmin-dense?batch_size=10")

    assert response.status_code == 200
    body = response.json()
    assert body["processed"] == 2
    assert body["remaining"] == 5

    # Two upserts to geocoded_point_cells with status='success'.
    upsert_calls = [c for c in mock_db.execute.call_args_list if "geocoded_point_cells" in c[0][0]]
    assert len(upsert_calls) == 2
    for c in upsert_calls:
        assert "'success'" in c[0][0]


@pytest.mark.asyncio
async def test_internal_trigger_garmin_dense_no_coverage(
    client: AsyncClient, mock_db: AsyncMock, monkeypatch: pytest.MonkeyPatch
):
    """Empty features -> status='no_coverage' upsert."""
    from app.routers import geocoding as geo_mod

    mock_db.fetch.return_value = [{"lat_4dp": 405000, "lon_4dp": -740000}]
    mock_db.fetchval.return_value = 0

    async def _fake_pelias(client, base, lat, lon):
        return {"features": []}

    monkeypatch.setattr(geo_mod, "_call_pelias", _fake_pelias)

    response = await client.post("/internal/geocoding/trigger/garmin-dense")

    assert response.status_code == 200
    assert response.json()["processed"] == 1
    upsert_sql = mock_db.execute.call_args[0][0]
    assert "geocoded_point_cells" in upsert_sql
    assert mock_db.execute.call_args[0][3] == "no_coverage"


@pytest.mark.asyncio
async def test_internal_trigger_garmin_dense_retry_failed_targets_statuses(client: AsyncClient, mock_db: AsyncMock):
    """retry_failed=true selects cells with status in (no_coverage, error, pending)."""
    mock_db.fetch.return_value = []
    mock_db.fetchval.return_value = 0

    response = await client.post("/internal/geocoding/trigger/garmin-dense?retry_failed=true")

    assert response.status_code == 200
    call_args = mock_db.fetch.call_args
    selection_sql = call_args[0][0]
    statuses = call_args[0][2]
    assert "status = ANY" in selection_sql
    assert "geocoded_point_cells" in selection_sql
    assert "no_coverage" in statuses
    assert "error" in statuses
    assert "pending" in statuses


@pytest.mark.asyncio
async def test_trigger_garmin_dense_requires_auth(client: AsyncClient, mock_db: AsyncMock):
    """Public dense endpoint must require auth."""
    app_obj = client._transport.app  # type: ignore[attr-defined]

    def _deny() -> None:
        raise HTTPException(status_code=http_status.HTTP_401_UNAUTHORIZED, detail="nope")

    app_obj.dependency_overrides[require_auth] = _deny
    try:
        response = await client.post("/api/v1/geocoding/trigger/garmin-dense")
    finally:
        app_obj.dependency_overrides.pop(require_auth, None)

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_trigger_garmin_dense_public_batch_size_limit(client: AsyncClient, mock_db: AsyncMock):
    """Public endpoint caps batch_size at 500."""
    app_obj = client._transport.app  # type: ignore[attr-defined]
    app_obj.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    try:
        response = await client.post("/api/v1/geocoding/trigger/garmin-dense?batch_size=501")
    finally:
        app_obj.dependency_overrides.pop(require_auth, None)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_internal_trigger_garmin_dense_retry_remaining_counts_retryable(client: AsyncClient, mock_db: AsyncMock):
    """In retry mode, `remaining` must count cells in retryable statuses, not unmatched track-point cells."""
    mock_db.fetch.return_value = []
    mock_db.fetchval.return_value = 7

    response = await client.post("/internal/geocoding/trigger/garmin-dense?retry_failed=true")

    assert response.status_code == 200
    assert response.json()["remaining"] == 7
    remaining_sql = mock_db.fetchval.call_args[0][0]
    remaining_statuses = mock_db.fetchval.call_args[0][1]
    assert "geocoded_point_cells" in remaining_sql
    assert "status = ANY" in remaining_sql
    assert "no_coverage" in remaining_statuses
    assert "error" in remaining_statuses
    assert "pending" in remaining_statuses
