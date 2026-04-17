"""Tests for health endpoints."""

import asyncio

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
        "status": "healthy",
        "pool_size": 2,
        "pool_free": 2,
    }

    response = await client.get("/ready")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["database"]["status"] == "healthy"
    assert data["version"] == "1.0.0"
    assert data["timestamp"].endswith("+00:00")


@pytest.mark.asyncio
async def test_ready_db_down(client: AsyncClient, mock_db):
    mock_db.health_check.side_effect = Exception("Connection refused")

    response = await client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "error": "Connection refused"}


@pytest.mark.asyncio
async def test_ready_db_timeout(client: AsyncClient, mock_db, monkeypatch):
    monkeypatch.setattr("app.routers.health._READY_TIMEOUT_S", 0.1)

    async def slow_health_check():
        await asyncio.sleep(1)

    mock_db.health_check.side_effect = slow_health_check

    response = await client.get("/ready")

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "not_ready"
    assert "timed out" in data["error"]


@pytest.mark.asyncio
async def test_ready_db_unhealthy(client: AsyncClient, mock_db):
    mock_db.health_check.return_value = {
        "status": "unhealthy",
        "error": "connection refused",
    }

    response = await client.get("/ready")

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "not_ready"
    assert data["database"]["status"] == "unhealthy"
