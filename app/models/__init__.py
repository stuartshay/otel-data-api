"""Shared Pydantic models."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class ErrorResponse(BaseModel):
    detail: str

    model_config = {"json_schema_extra": {"examples": [{"detail": "Resource not found"}]}}


class HealthResponse(BaseModel):
    status: str
    version: str | None = None
    server_time: str | None = None
    pool_size: int | None = None
    pool_free: int | None = None

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
