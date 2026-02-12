"""Pydantic models for spatial queries and unified views."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class UnifiedGpsPoint(BaseModel):
    source: str
    identifier: str
    latitude: float
    longitude: float
    timestamp: datetime
    accuracy: int | None = None
    battery: int | None = None
    speed_kmh: float | None = None
    heart_rate: int | None = None
    created_at: datetime | None = None


class DailyActivitySummary(BaseModel):
    activity_date: str | None = None
    owntracks_device: str | None = None
    owntracks_points: int | None = None
    min_battery: int | None = None
    max_battery: int | None = None
    avg_accuracy: float | None = None
    garmin_sport: str | None = None
    garmin_activities: int | None = None
    total_distance_km: float | None = None
    total_duration_seconds: int | None = None
    avg_heart_rate: float | None = None
    total_calories: int | None = None


class NearbyPoint(BaseModel):
    source: str
    id: int
    latitude: float
    longitude: float
    distance_meters: float
    timestamp: datetime


class DistanceResult(BaseModel):
    distance_meters: float
    from_lat: float
    from_lon: float
    to_lat: float
    to_lon: float


class WithinReferenceResult(BaseModel):
    reference_name: str
    radius_meters: int
    total_points: int
    points: list[NearbyPoint]
