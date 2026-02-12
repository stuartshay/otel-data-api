"""Async database service using asyncpg connection pool."""

from __future__ import annotations

import logging
from typing import Any

import asyncpg

from app.config import Config

logger = logging.getLogger(__name__)


class DatabaseService:
    """Manages asyncpg connection pool for PostgreSQL/PgBouncer."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._pool: asyncpg.Pool | None = None

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
            command_timeout=self._config.db_connect_timeout,
        )
        logger.info(
            "Database pool initialized (min=%d, max=%d)",
            self._config.db_pool_min,
            self._config.db_pool_max,
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
            logger.error("Database health check failed: %s", e)
            return {"status": "unhealthy", "error": str(e)}

    async def fetch(self, query: str, *args: Any) -> list[asyncpg.Record]:
        """Execute a query and return all rows."""
        result: list[asyncpg.Record] = await self.pool.fetch(query, *args)
        return result

    async def fetchrow(self, query: str, *args: Any) -> asyncpg.Record | None:
        """Execute a query and return a single row."""
        return await self.pool.fetchrow(query, *args)

    async def fetchval(self, query: str, *args: Any) -> Any:
        """Execute a query and return a single value."""
        return await self.pool.fetchval(query, *args)

    async def execute(self, query: str, *args: Any) -> str:
        """Execute a query and return the status."""
        result: str = await self.pool.execute(query, *args)
        return result
