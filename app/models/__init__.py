"""Shared Pydantic models."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Wrapper for paginated list responses."""

    items: list[T] = Field(description="List of items in the current page")
    total: int = Field(description="Total number of items matching the query")
    limit: int = Field(description="Maximum number of items per page")
    offset: int = Field(description="Number of items skipped from the start")


class ErrorResponse(BaseModel):
    """Standard error response returned for 4xx/5xx status codes."""

    detail: str = Field(description="Human-readable error message")

    model_config = {"json_schema_extra": {"examples": [{"detail": "Resource not found"}]}}


class HealthResponse(BaseModel):
    """Service health and readiness status."""

    status: str = Field(description="Service health status (healthy or unhealthy)")
    version: str | None = Field(default=None, description="Application version from VERSION file")
    server_time: str | None = Field(default=None, description="Current server time in ISO 8601 format")
    pool_size: int | None = Field(default=None, description="Total database connection pool size")
    pool_free: int | None = Field(default=None, description="Number of idle connections in the pool")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "status": "healthy",
                    "version": "1.7.0",
                    "server_time": "2026-02-12T08:10:55+00:00",
                    "pool_size": 10,
                    "pool_free": 9,
                }
            ]
        }
    }
