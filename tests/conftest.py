"""Test configuration and shared fixtures."""

import asyncio
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app import create_app
from app.config import Config
from app.database import DatabaseService


def _test_config() -> Config:
    """Return a Config suitable for testing."""
    return Config(
        pgbouncer_host="localhost",
        pgbouncer_port=5432,
        postgres_db="test_db",
        postgres_user="test",
        postgres_password="test",
        db_pool_min=1,
        db_pool_max=2,
        db_connect_timeout=5,
        port=8080,
        otel_exporter_endpoint="",
        otel_service_name="otel-data-api-test",
        otel_service_namespace="test",
        otel_environment="test",
        cognito_issuer="",
        cognito_client_id="",
        oauth2_enabled=False,
        cors_origins="*",
    )


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture()
def config() -> Config:
    return _test_config()


@pytest.fixture()
def mock_db() -> AsyncMock:
    """Mock DatabaseService."""
    db = AsyncMock(spec=DatabaseService)
    db.health_check = AsyncMock(
        return_value={"status": "connected", "pool_size": 2, "pool_free": 2}
    )
    db.fetch = AsyncMock(return_value=[])
    db.fetchrow = AsyncMock(return_value=None)
    db.fetchval = AsyncMock(return_value=0)
    db.execute = AsyncMock(return_value="OK")
    return db


@pytest.fixture()
def app(config: Config, mock_db: AsyncMock) -> FastAPI:
    """Create a test FastAPI application with mocked database."""
    test_app = create_app(config)
    test_app.state.db = mock_db
    return test_app


@pytest.fixture()
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client for testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
