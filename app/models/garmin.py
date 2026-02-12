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
    avg_temperature_c: int | None = None
    min_temperature_c: int | None = None
    max_temperature_c: int | None = None
    total_elapsed_time: float | None = None
    total_timer_time: float | None = None
    created_at: datetime | None = None
    uploaded_at: datetime | None = None
    track_point_count: int | None = None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "activity_id": "20932993811",
                    "sport": "cycling",
                    "sub_sport": "road",
                    "start_time": "2025-11-08T18:21:13+00:00",
                    "end_time": "2025-11-08T20:16:45+00:00",
                    "distance_km": 50.6,
                    "duration_seconds": 6932,
                    "avg_heart_rate": 142,
                    "max_heart_rate": 178,
                    "avg_cadence": 78,
                    "max_cadence": 112,
                    "calories": 1689,
                    "avg_speed_kmh": 26.3,
                    "max_speed_kmh": 48.7,
                    "total_ascent_m": 385,
                    "total_descent_m": 380,
                    "total_distance": 50598.95,
                    "avg_pace": 3.513345,
                    "device_manufacturer": "garmin",
                    "avg_temperature_c": 18,
                    "min_temperature_c": 14,
                    "max_temperature_c": 22,
                    "total_elapsed_time": 7200.5,
                    "total_timer_time": 6932.1,
                    "created_at": "2026-02-09T23:56:37+00:00",
                    "uploaded_at": "2026-02-09T23:56:37+00:00",
                    "track_point_count": 10707,
                }
            ]
        }
    }


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

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "id": 7454,
                    "activity_id": "20932993811",
                    "latitude": 40.71501586586237,
                    "longitude": -74.01768794283271,
                    "timestamp": "2025-11-08T18:21:13Z",
                    "altitude": 12.4,
                    "distance_from_start_km": 0.0,
                    "speed_kmh": 24.5,
                    "heart_rate": 135,
                    "cadence": 80,
                    "temperature_c": 18,
                    "created_at": "2026-02-09T23:56:37Z",
                }
            ]
        }
    }


class SportInfo(BaseModel):
    sport: str
    activity_count: int

    model_config = {"json_schema_extra": {"examples": [{"sport": "cycling", "activity_count": 20}]}}
