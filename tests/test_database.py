"""Tests for DatabaseService connection management, helpers, and SQL logging."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.database import DatabaseService, _parse_operation


class FakeTransaction:
    async def __aenter__(self) -> FakeTransaction:
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


class FakeConnection:
    def __init__(self) -> None:
        self.fetch = AsyncMock()
        self.execute = AsyncMock()

    def transaction(self) -> FakeTransaction:
        return FakeTransaction()


class FakeAcquireContext:
    def __init__(self, conn: FakeConnection) -> None:
        self._conn = conn

    async def __aenter__(self) -> FakeConnection:
        return self._conn

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


class FakePool:
    def __init__(self) -> None:
        self.fetch = AsyncMock()
        self.fetchrow = AsyncMock()
        self.fetchval = AsyncMock()
        self.execute = AsyncMock()
        self.closed = False
        self._size = 2
        self._idle = 1
        self.conn = FakeConnection()

    def acquire(self) -> FakeAcquireContext:
        return FakeAcquireContext(self.conn)

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
    assert captured["timeout"] == config.db_connect_timeout
    assert captured["command_timeout"] == config.db_statement_timeout_ms / 1000.0
    assert "server_settings" not in captured


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
async def test_fetch_no_jit_disables_jit_for_a_single_transaction(monkeypatch: pytest.MonkeyPatch, config):
    fake_pool = FakePool()
    fake_pool.conn.fetch.return_value = ["rows"]

    monkeypatch.setattr("app.database.asyncpg.create_pool", AsyncMock(return_value=fake_pool))

    db = DatabaseService(config)
    await db.initialize()

    assert await db.fetch_no_jit("SELECT * FROM table WHERE id=$1", 1) == ["rows"]
    # runs on the SAME acquired connection, inside a transaction, so SET LOCAL
    # scopes the JIT-off setting to just this query -- not the pool default,
    # which other queries sharing the pooled connection must keep using.
    fake_pool.conn.execute.assert_awaited_with("SET LOCAL jit = off")
    fake_pool.conn.fetch.assert_awaited_with("SELECT * FROM table WHERE id=$1", 1)
    fake_pool.fetch.assert_not_awaited()  # not the plain pool.fetch() path


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


# --- SQL operation parser ---


class TestParseOperation:
    """Tests for _parse_operation helper."""

    def test_select(self):
        assert _parse_operation("SELECT * FROM table") == "SELECT"

    def test_insert(self):
        assert _parse_operation("INSERT INTO table VALUES ($1)") == "INSERT"

    def test_update(self):
        assert _parse_operation("UPDATE table SET col=$1") == "UPDATE"

    def test_delete(self):
        assert _parse_operation("DELETE FROM table") == "DELETE"

    def test_with_cte(self):
        assert _parse_operation("WITH t AS (SELECT 1) SELECT * FROM t") == "WITH"

    def test_unknown_operation(self):
        assert _parse_operation("EXPLAIN SELECT 1") == "OTHER"

    def test_empty_query(self):
        assert _parse_operation("") == "OTHER"

    def test_leading_whitespace(self):
        assert _parse_operation("  SELECT 1") == "SELECT"


# --- SQL query logging ---


@pytest.mark.asyncio
async def test_sql_logging_emits_debug_log(monkeypatch: pytest.MonkeyPatch, config):
    """SQL tracing should emit a debug-level log with semantic fields."""
    fake_pool = FakePool()
    fake_pool.fetch.return_value = [{"id": 1}, {"id": 2}]
    monkeypatch.setattr("app.database.asyncpg.create_pool", AsyncMock(return_value=fake_pool))

    db = DatabaseService(config)
    await db.initialize()

    with patch("app.database.logger") as mock_logger:
        await db.fetch("SELECT * FROM locations WHERE device_id=$1", "phone")
        debug_calls = mock_logger.debug.call_args_list
        assert any(c.args and c.args[0] == "SQL query" for c in debug_calls)
        sql_call = next(c for c in debug_calls if c.args and c.args[0] == "SQL query")
        assert sql_call.kwargs.get("db.statement") == "SELECT * FROM locations WHERE device_id=$1"


@pytest.mark.asyncio
async def test_sql_logging_disabled(monkeypatch: pytest.MonkeyPatch):
    """When log_sql=False, no SQL log events should be emitted."""
    from app.config import Config

    disabled_config = Config(
        db_host="localhost",
        db_port=5432,
        db_name="test",
        db_user="test",
        db_password="test",  # pragma: allowlist secret - test fixture
        log_level="DEBUG",
        log_format="json",
        log_sql=False,
        log_sql_params=False,
    )

    fake_pool = FakePool()
    fake_pool.fetch.return_value = []
    monkeypatch.setattr("app.database.asyncpg.create_pool", AsyncMock(return_value=fake_pool))

    db = DatabaseService(disabled_config)
    await db.initialize()

    with patch("app.database.logger") as mock_logger:
        await db.fetch("SELECT 1")
        debug_calls = mock_logger.debug.call_args_list
        assert not any(c.args and c.args[0] == "SQL query" for c in debug_calls)


@pytest.mark.asyncio
async def test_slow_query_logged_as_warning(monkeypatch: pytest.MonkeyPatch, config):
    """Queries exceeding SLOW_QUERY_THRESHOLD_MS should be logged at WARNING."""
    fake_pool = FakePool()
    fake_pool.fetch.return_value = []
    monkeypatch.setattr("app.database.asyncpg.create_pool", AsyncMock(return_value=fake_pool))

    db = DatabaseService(config)
    await db.initialize()

    # Patch time.perf_counter to simulate a slow query (>500ms)
    call_count = 0

    def fake_perf_counter():
        nonlocal call_count
        call_count += 1
        # First call returns 0, second call returns 1 (1000ms duration)
        return 0.0 if call_count % 2 == 1 else 1.0

    with (
        patch("app.database.time.perf_counter", side_effect=fake_perf_counter),
        patch("app.database.logger") as mock_logger,
    ):
        await db.fetch("SELECT * FROM big_table")
        warning_calls = mock_logger.warning.call_args_list
        assert any(c.args and c.args[0] == "Slow SQL query" for c in warning_calls)
