"""Pydantic models for Garmin activity and track point data."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class GarminActivity(BaseModel):
    """Summary of a Garmin Connect activity parsed from a FIT file."""

    activity_id: str = Field(description="Garmin Connect activity identifier")
    sport: str = Field(description="Primary sport type (e.g. cycling, running)")
    sub_sport: str | None = Field(default=None, description="Sub-sport classification (e.g. road, trail)")
    start_time: datetime | None = Field(default=None, description="Activity start time in UTC")
    end_time: datetime | None = Field(default=None, description="Activity end time in UTC")
    distance_km: float | None = Field(default=None, description="Total distance in kilometres")
    duration_seconds: int | None = Field(default=None, description="Active duration in seconds (excludes pauses)")
    avg_heart_rate: int | None = Field(default=None, description="Average heart rate in beats per minute")
    max_heart_rate: int | None = Field(default=None, description="Maximum heart rate in beats per minute")
    avg_cadence: int | None = Field(default=None, description="Average cadence in RPM")
    max_cadence: int | None = Field(default=None, description="Maximum cadence in RPM")
    calories: int | None = Field(default=None, description="Total calories burned")
    avg_speed_kmh: float | None = Field(default=None, description="Average speed in km/h")
    max_speed_kmh: float | None = Field(default=None, description="Maximum speed in km/h")
    total_ascent_m: int | None = Field(default=None, description="Total elevation gain in meters")
    total_descent_m: int | None = Field(default=None, description="Total elevation loss in meters")
    total_distance: float | None = Field(default=None, description="Raw total distance in meters from FIT file")
    avg_pace: float | None = Field(default=None, description="Average pace in minutes per kilometre")
    device_manufacturer: str | None = Field(default=None, description="Device manufacturer (e.g. garmin)")
    avg_temperature_c: int | None = Field(default=None, description="Average ambient temperature in degrees C")
    min_temperature_c: int | None = Field(default=None, description="Minimum ambient temperature in degrees C")
    max_temperature_c: int | None = Field(default=None, description="Maximum ambient temperature in degrees C")
    total_elapsed_time: float | None = Field(
        default=None, description="Total elapsed time in seconds (includes pauses)"
    )
    total_timer_time: float | None = Field(default=None, description="Total timer time in seconds (active recording)")
    created_at: datetime | None = Field(default=None, description="UTC timestamp when the record was inserted")
    uploaded_at: datetime | None = Field(default=None, description="UTC timestamp when the FIT file was uploaded")
    track_point_count: int | None = Field(default=None, description="Number of GPS track points in this activity")

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
    """Individual GPS track point within a Garmin activity."""

    id: int = Field(description="Unique track point record identifier")
    activity_id: str = Field(description="Parent Garmin activity identifier")
    latitude: float = Field(description="GPS latitude in decimal degrees (WGS 84)")
    longitude: float = Field(description="GPS longitude in decimal degrees (WGS 84)")
    timestamp: datetime = Field(description="UTC timestamp of the track point recording")
    altitude: float | None = Field(default=None, description="Elevation above sea level in meters")
    distance_from_start_km: float | None = Field(
        default=None, description="Cumulative distance from activity start in km"
    )
    speed_kmh: float | None = Field(default=None, description="Instantaneous speed in km/h")
    heart_rate: int | None = Field(default=None, description="Heart rate in beats per minute")
    cadence: int | None = Field(default=None, description="Pedal/step cadence in RPM")
    temperature_c: int | None = Field(default=None, description="Ambient temperature in degrees C")
    created_at: datetime | None = Field(default=None, description="UTC timestamp when the record was inserted")

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


class GarminChartPoint(BaseModel):
    """Lightweight track point optimised for time-series chart rendering."""

    timestamp: datetime = Field(description="UTC timestamp of the data point")
    altitude: float | None = Field(default=None, description="Elevation above sea level in meters")
    distance_from_start_km: float | None = Field(
        default=None, description="Cumulative distance from activity start in km"
    )
    speed_kmh: float | None = Field(default=None, description="Instantaneous speed in km/h")
    heart_rate: int | None = Field(default=None, description="Heart rate in beats per minute")
    cadence: int | None = Field(default=None, description="Pedal/step cadence in RPM")
    temperature_c: int | None = Field(default=None, description="Ambient temperature in degrees C")
    latitude: float = Field(description="GPS latitude in decimal degrees (WGS 84)")
    longitude: float = Field(description="GPS longitude in decimal degrees (WGS 84)")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "timestamp": "2025-11-08T18:21:13Z",
                    "altitude": 12.4,
                    "distance_from_start_km": 0.0,
                    "speed_kmh": 24.5,
                    "heart_rate": 135,
                    "cadence": 80,
                    "temperature_c": 18,
                    "latitude": 40.71501586586237,
                    "longitude": -74.01768794283271,
                }
            ]
        }
    }


class SportInfo(BaseModel):
    """Sport type with its activity count."""

    sport: str = Field(description="Sport type name (e.g. cycling, running)")
    activity_count: int = Field(description="Number of activities for this sport")

    model_config = {"json_schema_extra": {"examples": [{"sport": "cycling", "activity_count": 20}]}}
