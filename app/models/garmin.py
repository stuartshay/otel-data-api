"""Pydantic models for Garmin activity and track point data."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class GarminActivity(BaseModel):
    activity_id: str
    sport: str
    sub_sport: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    distance_km: float | None = None
    duration_seconds: int | None = None
    avg_heart_rate: int | None = None
    max_heart_rate: int | None = None
    avg_cadence: int | None = None
    max_cadence: int | None = None
    calories: int | None = None
    avg_speed_kmh: float | None = None
    max_speed_kmh: float | None = None
    total_ascent_m: int | None = None
    total_descent_m: int | None = None
    total_distance: float | None = None
    avg_pace: float | None = None
    device_manufacturer: str | None = None
    created_at: datetime | None = None
    uploaded_at: datetime | None = None
    track_point_count: int | None = None


class GarminTrackPoint(BaseModel):
    id: int
    activity_id: str
    latitude: float
    longitude: float
    timestamp: datetime
    altitude: float | None = None
    distance_from_start_km: float | None = None
    speed_kmh: float | None = None
    heart_rate: int | None = None
    cadence: int | None = None
    temperature_c: int | None = None
    created_at: datetime | None = None


class SportInfo(BaseModel):
    sport: str
    activity_count: int
