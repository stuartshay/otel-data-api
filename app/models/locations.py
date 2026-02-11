"""Pydantic models for OwnTracks location data."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class Location(BaseModel):
    id: int
    device_id: str
    tid: str | None = None
    latitude: float
    longitude: float
    accuracy: int | None = None
    altitude: float | None = None
    velocity: int | None = None
    battery: int | None = None
    battery_status: int | None = None
    connection_type: str | None = None
    trigger: str | None = None
    timestamp: datetime
    created_at: datetime | None = None


class LocationDetail(Location):
    raw_payload: dict | None = None


class DeviceInfo(BaseModel):
    device_id: str


class LocationCount(BaseModel):
    count: int
    date: str | None = None
    device_id: str | None = None
