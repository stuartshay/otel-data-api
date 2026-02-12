"""Pydantic models for reference locations."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ReferenceLocation(BaseModel):
    id: int
    name: str
    latitude: float
    longitude: float
    radius_meters: int = 50
    description: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ReferenceLocationCreate(BaseModel):
    name: str
    latitude: float
    longitude: float
    radius_meters: int = 50
    description: str | None = None


class ReferenceLocationUpdate(BaseModel):
    name: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    radius_meters: int | None = None
    description: str | None = None
