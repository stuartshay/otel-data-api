"""Pydantic models for spatial queries and unified views."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class UnifiedGpsPoint(BaseModel):
    """Single GPS data point from the unified view combining OwnTracks and Garmin sources."""

    source: str = Field(description="Data source: 'owntracks' or 'garmin'")
    identifier: str = Field(description="Device or activity identifier from the source")
    latitude: float = Field(description="GPS latitude in decimal degrees (WGS 84)")
    longitude: float = Field(description="GPS longitude in decimal degrees (WGS 84)")
    timestamp: datetime = Field(description="UTC timestamp of the GPS recording")
    accuracy: int | None = Field(default=None, description="Horizontal GPS accuracy in meters (OwnTracks only)")
    battery: int | None = Field(default=None, description="Device battery percentage (OwnTracks only)")
    speed_kmh: float | None = Field(default=None, description="Instantaneous speed in km/h (Garmin only)")
    heart_rate: int | None = Field(default=None, description="Heart rate in BPM (Garmin only)")
    created_at: datetime | None = Field(default=None, description="UTC timestamp when the record was inserted")

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
    """Per-day aggregate combining OwnTracks location stats and Garmin activity metrics."""

    activity_date: str | None = Field(default=None, description="Calendar date in YYYY-MM-DD format")
    owntracks_device: str | None = Field(default=None, description="OwnTracks device that reported data for this day")
    owntracks_points: int | None = Field(default=None, description="Number of OwnTracks GPS points recorded")
    min_battery: int | None = Field(default=None, description="Lowest device battery percentage observed")
    max_battery: int | None = Field(default=None, description="Highest device battery percentage observed")
    avg_accuracy: float | None = Field(default=None, description="Mean horizontal GPS accuracy in meters")
    garmin_sport: str | None = Field(default=None, description="Garmin sport type for activities on this day")
    garmin_activities: int | None = Field(default=None, description="Number of Garmin activities recorded")
    total_distance_km: float | None = Field(default=None, description="Combined Garmin activity distance in km")
    total_duration_seconds: int | None = Field(default=None, description="Combined Garmin activity duration in seconds")
    avg_heart_rate: float | None = Field(default=None, description="Mean heart rate across Garmin activities in BPM")
    total_calories: int | None = Field(default=None, description="Total calories burned across Garmin activities")

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
    """GPS point found within a spatial proximity search."""

    source: str = Field(description="Data source: 'owntracks' or 'garmin'")
    id: int = Field(description="Record identifier in the source table")
    latitude: float = Field(description="GPS latitude in decimal degrees (WGS 84)")
    longitude: float = Field(description="GPS longitude in decimal degrees (WGS 84)")
    distance_meters: float = Field(description="Distance from the search center point in meters")
    timestamp: datetime = Field(description="UTC timestamp of the GPS recording")

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
    """Geodesic distance calculation result between two geographic points."""

    distance_meters: float = Field(description="Geodesic distance between the two points in meters")
    from_lat: float = Field(description="Origin latitude in decimal degrees")
    from_lon: float = Field(description="Origin longitude in decimal degrees")
    to_lat: float = Field(description="Destination latitude in decimal degrees")
    to_lon: float = Field(description="Destination longitude in decimal degrees")

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
    """GPS points found within a named reference location's geofence radius."""

    reference_name: str = Field(description="Name of the reference location searched")
    radius_meters: int = Field(description="Geofence radius used for the search in meters")
    total_points: int = Field(description="Number of GPS points found within the radius")
    points: list[NearbyPoint] = Field(description="GPS points within the radius, sorted by distance")

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
