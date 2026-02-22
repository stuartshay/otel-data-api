"""Tests for DatabaseService connection management and helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.database import DatabaseService


class FakePool:
    def __init__(self) -> None:
        self.fetch = AsyncMock()
        self.fetchrow = AsyncMock()
        self.fetchval = AsyncMock()
        self.execute = AsyncMock()
        self.closed = False
        self._size = 2
        self._idle = 1

    def get_size(self) -> int:
        return self._size

    def get_idle_size(self) -> int:
        return self._idle

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_initialize_creates_pool(monkeypatch: pytest.MonkeyPatch, config):
    fake_pool = FakePool()
    captured: dict = {}

    async def _fake_create_pool(**kwargs):
        captured.update(kwargs)
        return fake_pool

    monkeypatch.setattr("app.database.asyncpg.create_pool", _fake_create_pool)

    db = DatabaseService(config)
    await db.initialize()

    assert db.pool is fake_pool
    assert captured["host"] == config.db_host
    assert captured["port"] == config.db_port
    assert captured["database"] == config.db_name
    assert captured["user"] == config.db_user
    assert captured["password"] == config.db_password
    assert captured["min_size"] == config.db_pool_min
    assert captured["max_size"] == config.db_pool_max
    assert captured["command_timeout"] == config.db_connect_timeout


def test_pool_property_requires_initialize(config):
    db = DatabaseService(config)
    with pytest.raises(RuntimeError):
        _ = db.pool


@pytest.mark.asyncio
async def test_health_check_success(monkeypatch: pytest.MonkeyPatch, config):
    fake_pool = FakePool()
    fake_pool.fetchrow.return_value = {"version": "PostgreSQL 16", "server_time": "2026-02-22T12:00:00Z"}
    fake_pool._size = 4
    fake_pool._idle = 3

    monkeypatch.setattr("app.database.asyncpg.create_pool", AsyncMock(return_value=fake_pool))

    db = DatabaseService(config)
    await db.initialize()

    result = await db.health_check()

    assert result["status"] == "healthy"
    assert result["version"] == "PostgreSQL 16"
    assert result["server_time"] == "2026-02-22T12:00:00Z"
    assert result["pool_size"] == 4
    assert result["pool_free"] == 3


@pytest.mark.asyncio
async def test_health_check_handles_errors(monkeypatch: pytest.MonkeyPatch, config):
    fake_pool = FakePool()
    fake_pool.fetchrow.side_effect = ValueError("boom")

    monkeypatch.setattr("app.database.asyncpg.create_pool", AsyncMock(return_value=fake_pool))

    db = DatabaseService(config)
    await db.initialize()

    result = await db.health_check()

    assert result["status"] == "unhealthy"
    assert "boom" in result["error"]


@pytest.mark.asyncio
async def test_fetch_helpers_delegate_to_pool(monkeypatch: pytest.MonkeyPatch, config):
    fake_pool = FakePool()
    fake_pool.fetch.return_value = ["rows"]
    fake_pool.fetchrow.return_value = {"id": 1}
    fake_pool.fetchval.return_value = 99
    fake_pool.execute.return_value = "OK"

    monkeypatch.setattr("app.database.asyncpg.create_pool", AsyncMock(return_value=fake_pool))

    db = DatabaseService(config)
    await db.initialize()

    assert await db.fetch("SELECT * FROM table WHERE id=$1", 1) == ["rows"]
    fake_pool.fetch.assert_awaited_with("SELECT * FROM table WHERE id=$1", 1)

    assert await db.fetchrow("SELECT 1") == {"id": 1}
    fake_pool.fetchrow.assert_awaited_with("SELECT 1")

    assert await db.fetchval("SELECT COUNT(*)") == 99
    fake_pool.fetchval.assert_awaited_with("SELECT COUNT(*)")

    assert await db.execute("DELETE FROM table") == "OK"
    fake_pool.execute.assert_awaited_with("DELETE FROM table")


@pytest.mark.asyncio
async def test_close_shuts_pool_and_resets(monkeypatch: pytest.MonkeyPatch, config):
    fake_pool = FakePool()
    monkeypatch.setattr("app.database.asyncpg.create_pool", AsyncMock(return_value=fake_pool))

    db = DatabaseService(config)
    await db.initialize()

    await db.close()

    assert fake_pool.closed is True
    with pytest.raises(RuntimeError):
        _ = db.pool
