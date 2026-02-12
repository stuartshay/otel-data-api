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

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "source": "owntracks",
                    "identifier": "iphone_stuart",
                    "latitude": 40.736238,
                    "longitude": -74.039405,
                    "timestamp": "2026-02-12T08:11:55+00:00",
                    "accuracy": 7,
                    "battery": 100,
                    "speed_kmh": None,
                    "heart_rate": None,
                    "created_at": "2026-02-12T08:11:55+00:00",
                }
            ]
        }
    }


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

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "activity_date": "2026-02-11",
                    "owntracks_device": "iphone_stuart",
                    "owntracks_points": 1429,
                    "min_battery": 64,
                    "max_battery": 100,
                    "avg_accuracy": 4.89,
                    "garmin_sport": "cycling",
                    "garmin_activities": 1,
                    "total_distance_km": 50.6,
                    "total_duration_seconds": 6932,
                    "avg_heart_rate": 142.0,
                    "total_calories": 1689,
                }
            ]
        }
    }


class NearbyPoint(BaseModel):
    source: str
    id: int
    latitude: float
    longitude: float
    distance_meters: float
    timestamp: datetime

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "source": "owntracks",
                    "id": 35144,
                    "latitude": 40.736202,
                    "longitude": -74.039404,
                    "distance_meters": 0.40,
                    "timestamp": "2026-02-02T10:30:53Z",
                }
            ]
        }
    }


class DistanceResult(BaseModel):
    distance_meters: float
    from_lat: float
    from_lon: float
    to_lat: float
    to_lon: float

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "distance_meters": 5309.71,
                    "from_lat": 40.7128,
                    "from_lon": -74.006,
                    "to_lat": 40.758,
                    "to_lon": -73.9855,
                }
            ]
        }
    }


class WithinReferenceResult(BaseModel):
    reference_name: str
    radius_meters: int
    total_points: int
    points: list[NearbyPoint]

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "reference_name": "home",
                    "radius_meters": 40,
                    "total_points": 2,
                    "points": [
                        {
                            "source": "owntracks",
                            "id": 35144,
                            "latitude": 40.736202,
                            "longitude": -74.039404,
                            "distance_meters": 0.40,
                            "timestamp": "2026-02-02T10:30:53Z",
                        }
                    ],
                }
            ]
        }
    }
