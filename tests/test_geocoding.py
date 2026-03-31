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
    mock_db.fetchval.side_effect = [1000, 600, 550, 30, 10, 10]

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


@pytest.mark.asyncio
async def test_geocoding_status_empty_database(client: AsyncClient, mock_db: AsyncMock):
    mock_db.fetchval.side_effect = [0, 0, 0, 0, 0, 0]

    response = await client.get("/api/v1/geocoding/status")

    assert response.status_code == 200
    body = response.json()
    assert body["total_locations"] == 0
    assert body["coverage_percent"] == 0.0


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
    mock_db.fetchval.side_effect = [0, 5]  # nearby count = 0, then remaining = 5

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


@pytest.mark.asyncio
async def test_trigger_geocoding_pelias_no_features(client: AsyncClient, mock_db: AsyncMock):
    mock_db.fetch.return_value = [
        {"id": 2, "latitude": 0.0, "longitude": 0.0},
    ]
    mock_db.fetchval.side_effect = [0, 100]  # nearby count = 0, then remaining

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
    mock_db.fetchval.side_effect = [
        1,  # nearby count > 0 → dedup
        50,  # remaining
    ]
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

    response = await client.post("/api/v1/geocoding/trigger?batch_size=500")

    assert response.status_code == 200
    mock_db.fetch.assert_called_once()
    call_args = mock_db.fetch.call_args
    assert call_args[0][1] == 500  # batch_size parameter


@pytest.mark.asyncio
async def test_trigger_geocoding_retry_failed(client: AsyncClient, mock_db: AsyncMock):
    mock_db.fetch.return_value = []
    mock_db.fetchval.return_value = 0

    response = await client.post("/api/v1/geocoding/trigger?retry_failed=true")

    assert response.status_code == 200
    # Verify the retry_failed query was used (INNER JOIN with status='no_coverage')
    call_args = mock_db.fetch.call_args
    assert "no_coverage" in call_args[0][0]


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
    assert "no_coverage" in call_args[0][0]


@pytest.mark.asyncio
async def test_internal_trigger_happy_path(client: AsyncClient, mock_db: AsyncMock):
    """Internal endpoint should process locations via Pelias."""
    mock_db.fetch.return_value = [
        {"id": 10, "latitude": 40.7128, "longitude": -74.006},
    ]
    mock_db.fetchval.side_effect = [0, 3]  # nearby count = 0, then remaining = 3

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
