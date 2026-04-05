"""Async database service using asyncpg connection pool."""

from __future__ import annotations

import time
from typing import Any

import asyncpg
import structlog

from app.config import Config

# Slow-query threshold (milliseconds) — queries above this are logged at WARNING
SLOW_QUERY_THRESHOLD_MS: float = 500.0

logger = structlog.get_logger(__name__)

# Maximum SQL length to include in log events (prevents log bloat)
_MAX_SQL_LOG_LENGTH = 1000


def _parse_operation(query: str) -> str:
    """Extract the SQL operation (SELECT, INSERT, …) from the query text."""
    first_word = query.lstrip().split(None, 1)[0].upper() if query.strip() else "UNKNOWN"
    return first_word if first_word in {"SELECT", "INSERT", "UPDATE", "DELETE", "WITH", "BEGIN", "COMMIT"} else "OTHER"


class DatabaseService:
    """Manages asyncpg connection pool for PostgreSQL/PgBouncer."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._pool: asyncpg.Pool | None = None
        self._log_sql = config.log_sql
        self._log_sql_params = config.log_sql_params

    async def initialize(self) -> None:
        """Create the connection pool."""
        self._config.validate_database()
        self._pool = await asyncpg.create_pool(
            host=self._config.db_host,
            port=self._config.db_port,
            database=self._config.db_name,
            user=self._config.db_user,
            password=self._config.db_password,
            min_size=self._config.db_pool_min,
            max_size=self._config.db_pool_max,
            timeout=self._config.db_connect_timeout,
            command_timeout=self._config.db_statement_timeout_ms / 1000.0,
        )
        logger.info(
            "Database pool initialized",
            db_pool_min=self._config.db_pool_min,
            db_pool_max=self._config.db_pool_max,
        )

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("Database pool closed")

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("Database pool not initialized. Call initialize() first.")
        return self._pool

    def _log_query(self, query: str, args: tuple[Any, ...], duration_ms: float, row_count: int | None = None) -> None:
        """Emit a structured log event for a SQL query."""
        if not self._log_sql:
            return

        log_kwargs: dict[str, Any] = {
            "db.statement": query[:_MAX_SQL_LOG_LENGTH],
            "db.operation": _parse_operation(query),
            "db.duration_ms": round(duration_ms, 2),
        }
        if row_count is not None:
            log_kwargs["db.rows_affected"] = row_count
        if self._log_sql_params and args:
            log_kwargs["db.params"] = [str(a) for a in args]

        if duration_ms >= SLOW_QUERY_THRESHOLD_MS:
            logger.warning("Slow SQL query", **log_kwargs)
        else:
            logger.debug("SQL query", **log_kwargs)

    async def health_check(self) -> dict[str, Any]:
        """Check database connectivity and return status."""
        try:
            row = await self.pool.fetchrow("SELECT version() AS version, NOW() AS server_time")
            return {
                "status": "healthy",
                "version": row["version"] if row else "unknown",
                "server_time": str(row["server_time"]) if row else "unknown",
                "pool_size": self.pool.get_size(),
                "pool_free": self.pool.get_idle_size(),
            }
        except Exception as e:
            logger.error("Database health check failed", error=str(e))
            return {"status": "unhealthy", "error": str(e)}

    async def fetch(self, query: str, *args: Any) -> list[asyncpg.Record]:
        """Execute a query and return all rows."""
        start = time.perf_counter()
        result: list[asyncpg.Record] = await self.pool.fetch(query, *args)
        self._log_query(query, args, (time.perf_counter() - start) * 1000.0, row_count=len(result))
        return result

    async def fetchrow(self, query: str, *args: Any) -> asyncpg.Record | None:
        """Execute a query and return a single row."""
        start = time.perf_counter()
        result = await self.pool.fetchrow(query, *args)
        self._log_query(query, args, (time.perf_counter() - start) * 1000.0, row_count=1 if result else 0)
        return result

    async def fetchval(self, query: str, *args: Any) -> Any:
        """Execute a query and return a single value."""
        start = time.perf_counter()
        result = await self.pool.fetchval(query, *args)
        self._log_query(query, args, (time.perf_counter() - start) * 1000.0)
        return result

    async def execute(self, query: str, *args: Any) -> str:
        """Execute a query and return the status."""
        start = time.perf_counter()
        result: str = await self.pool.execute(query, *args)
        self._log_query(query, args, (time.perf_counter() - start) * 1000.0)
        return result
