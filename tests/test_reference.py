"""Tests for reference location CRUD endpoints."""

import pytest
from fastapi import HTTPException
from fastapi import status as http_status
from fastapi.applications import FastAPI
from httpx import AsyncClient

from app.auth import require_auth


def _reference_row(location_id: int = 1, name: str = "home") -> dict:
    return {
        "id": location_id,
        "name": name,
        "latitude": 40.7362,
        "longitude": -74.0394,
        "radius_meters": 40,
        "description": "Primary apartment",
        "created_at": "2026-02-03T22:49:07+00:00",
        "updated_at": "2026-02-03T22:50:01+00:00",
    }


@pytest.mark.asyncio
async def test_list_reference_locations(client: AsyncClient, mock_db):
    mock_db.fetch.return_value = [_reference_row(1, "home"), _reference_row(2, "office")]

    response = await client.get("/api/v1/reference-locations")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["name"] == "home"
    assert data[1]["name"] == "office"


@pytest.mark.asyncio
async def test_get_reference_location_success(client: AsyncClient, mock_db):
    mock_db.fetchrow.return_value = _reference_row()

    response = await client.get("/api/v1/reference-locations/1")

    assert response.status_code == 200
    assert response.json()["name"] == "home"


@pytest.mark.asyncio
async def test_get_reference_location_not_found(client: AsyncClient, mock_db):
    mock_db.fetchrow.return_value = None

    response = await client.get("/api/v1/reference-locations/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Reference location not found"}


@pytest.mark.asyncio
async def test_create_reference_location_success(client: AsyncClient, mock_db):
    mock_db.fetchrow.return_value = _reference_row(3, "gym")

    response = await client.post(
        "/api/v1/reference-locations",
        json={
            "name": "gym",
            "latitude": 40.7,
            "longitude": -74.0,
            "radius_meters": 75,
            "description": "Neighborhood gym",
        },
    )

    assert response.status_code == 201
    assert response.json()["name"] == "gym"


@pytest.mark.asyncio
async def test_create_reference_location_failure_returns_500(client: AsyncClient, mock_db):
    mock_db.fetchrow.return_value = None

    response = await client.post(
        "/api/v1/reference-locations",
        json={"name": "gym", "latitude": 40.7, "longitude": -74.0, "radius_meters": 75},
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "Failed to create reference location"}


@pytest.mark.asyncio
async def test_update_reference_location_success(client: AsyncClient, mock_db):
    mock_db.fetchrow.return_value = _reference_row(1, "home-updated")

    response = await client.put(
        "/api/v1/reference-locations/1",
        json={"name": "home-updated", "radius_meters": 55},
    )

    assert response.status_code == 200
    assert response.json()["name"] == "home-updated"

    query = mock_db.fetchrow.await_args.args[0]
    assert "name = $1" in query
    assert "radius_meters = $2" in query
    assert "updated_at = NOW()" in query


@pytest.mark.asyncio
async def test_update_reference_location_no_fields_returns_400(client: AsyncClient, mock_db):
    response = await client.put("/api/v1/reference-locations/1", json={})

    assert response.status_code == 400
    assert response.json() == {"detail": "No fields to update"}
    mock_db.fetchrow.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_reference_location_not_found(client: AsyncClient, mock_db):
    mock_db.fetchrow.return_value = None

    response = await client.put(
        "/api/v1/reference-locations/1",
        json={"description": "Updated description"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Reference location not found"}


@pytest.mark.asyncio
async def test_delete_reference_location_success(client: AsyncClient, mock_db):
    mock_db.execute.return_value = "DELETE 1"

    response = await client.delete("/api/v1/reference-locations/1")

    assert response.status_code == 204
    assert response.content == b""


@pytest.mark.asyncio
async def test_delete_reference_location_not_found(client: AsyncClient, mock_db):
    mock_db.execute.return_value = "DELETE 0"

    response = await client.delete("/api/v1/reference-locations/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Reference location not found"}


@pytest.mark.asyncio
async def test_create_reference_location_requires_auth_when_dependency_denies(
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
        response = await client.post(
            "/api/v1/reference-locations",
            json={"name": "gym", "latitude": 40.7, "longitude": -74.0, "radius_meters": 75},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}
