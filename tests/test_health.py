"""Tests for health endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    response = await client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["version"] == "1.0.0"
    assert data["timestamp"].endswith("+00:00")


@pytest.mark.asyncio
async def test_ready(client: AsyncClient, mock_db):
    mock_db.health_check.return_value = {
        "status": "connected",
        "pool_size": 2,
        "pool_free": 2,
    }

    response = await client.get("/ready")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["database"]["status"] == "connected"
    assert data["version"] == "1.0.0"
    assert data["timestamp"].endswith("+00:00")


@pytest.mark.asyncio
async def test_ready_db_down(client: AsyncClient, mock_db):
    mock_db.health_check.side_effect = Exception("Connection refused")

    response = await client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "error": "Connection refused"}
