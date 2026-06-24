"""Pydantic models for Garmin activity and track point data."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date as date_type
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.geocoding import GeocodedAddressSummary


class GarminDevice(BaseModel):
    """Recording device metadata for a Garmin activity."""

    device_id: int | None = Field(default=None, description="Recording device serial number")
    manufacturer: str | None = Field(default=None, description="Device manufacturer (e.g. garmin)")
    garmin_product: int | None = Field(
        default=None, description="Raw Garmin product enum id from the FIT file (e.g. 4061)"
    )
    model: str | None = Field(default=None, description="Friendly device model name (e.g. Edge 540 Solar)")
    software_version: str | None = Field(default=None, description="Device firmware/software version (e.g. 31.30)")


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
    hr_available: bool = Field(
        default=False,
        description="Whether this activity has usable heart-rate data in summary or track points",
    )
    min_heart_rate: int | None = Field(default=None, description="Minimum heart rate in beats per minute")
    aerobic_training_effect: float | None = Field(default=None, description="Aerobic training effect score")
    anaerobic_training_effect: float | None = Field(default=None, description="Anaerobic training effect score")
    exercise_load: int | None = Field(default=None, description="Exercise load score")
    avg_respiration_rate: int | None = Field(default=None, description="Average respiration rate in breaths per minute")
    min_respiration_rate: int | None = Field(default=None, description="Minimum respiration rate in breaths per minute")
    max_respiration_rate: int | None = Field(default=None, description="Maximum respiration rate in breaths per minute")
    sweat_loss_ml: int | None = Field(default=None, description="Estimated sweat loss in millilitres")
    moderate_intensity_minutes: int | None = Field(default=None, description="Moderate intensity minutes")
    vigorous_intensity_minutes: int | None = Field(default=None, description="Vigorous intensity minutes")
    total_intensity_minutes: int | None = Field(default=None, description="Total intensity minutes")
    paved_distance_km: float | None = Field(default=None, description="Distance over paved surfaces in kilometres")
    unpaved_distance_km: float | None = Field(default=None, description="Distance over unpaved surfaces in kilometres")
    avg_cadence: int | None = Field(default=None, description="Average cadence in RPM")
    max_cadence: int | None = Field(default=None, description="Maximum cadence in RPM")
    total_strokes: int | None = Field(default=None, description="Total activity strokes")
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
    device: GarminDevice | None = Field(default=None, description="Recording device metadata")

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> GarminActivity:
        """Build an activity from a DB row, folding joined device columns into ``device``.

        Device columns are selected with a ``dev_`` prefix (plus ``device_id``)
        so they do not collide with the activity's own ``device_manufacturer``.
        """
        data = dict(row)
        device_id = data.pop("device_id", None)
        dev_manufacturer = data.pop("dev_manufacturer", None)
        dev_garmin_product = data.pop("dev_garmin_product", None)
        dev_model = data.pop("dev_model", None)
        dev_software_version = data.pop("dev_software_version", None)
        device = None
        if device_id is not None:
            device = GarminDevice(
                device_id=device_id,
                manufacturer=dev_manufacturer,
                garmin_product=dev_garmin_product,
                model=dev_model,
                software_version=dev_software_version,
            )
        return cls(**data, device=device)

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
                    "hr_available": True,
                    "min_heart_rate": 98,
                    "aerobic_training_effect": 2.6,
                    "anaerobic_training_effect": 0.0,
                    "exercise_load": 48,
                    "avg_respiration_rate": 25,
                    "min_respiration_rate": 16,
                    "max_respiration_rate": 32,
                    "sweat_loss_ml": 1629,
                    "moderate_intensity_minutes": 88,
                    "vigorous_intensity_minutes": 29,
                    "total_intensity_minutes": 146,
                    "paved_distance_km": 21.09,
                    "unpaved_distance_km": 0.65,
                    "avg_cadence": 78,
                    "max_cadence": 112,
                    "total_strokes": 4250,
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
                    "device": {
                        "device_id": 3444454776,
                        "manufacturer": "garmin",
                        "garmin_product": 4061,
                        "model": "Edge 540 Solar",
                        "software_version": "31.30",
                    },
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
    hr_zone: int | None = Field(default=None, description="Heart-rate zone index (1-5)")
    respiration_rate: int | None = Field(default=None, description="Respiration rate in breaths per minute")
    cadence: int | None = Field(default=None, description="Pedal/step cadence in RPM")
    temperature_c: int | None = Field(default=None, description="Ambient temperature in degrees C")
    surface_type: str | None = Field(default=None, description="Road or terrain type")
    effort_level: str | None = Field(default=None, description="Effort classification label")
    created_at: datetime | None = Field(default=None, description="UTC timestamp when the record was inserted")
    address: GeocodedAddressSummary | None = Field(
        default=None,
        description="Reverse-geocoded address for this track point (Garmin pipeline). "
        "Only populated for waypoints that have been geocoded.",
    )

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
                    "hr_zone": 3,
                    "respiration_rate": 22,
                    "cadence": 80,
                    "temperature_c": 18,
                    "surface_type": "paved",
                    "effort_level": "steady",
                    "created_at": "2026-02-09T23:56:37Z",
                    "address": None,
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
    hr_zone: int | None = Field(default=None, description="Heart-rate zone index (1-5)")
    respiration_rate: int | None = Field(default=None, description="Respiration rate in breaths per minute")
    cadence: int | None = Field(default=None, description="Pedal/step cadence in RPM")
    temperature_c: int | None = Field(default=None, description="Ambient temperature in degrees C")
    surface_type: str | None = Field(default=None, description="Road or terrain type")
    effort_level: str | None = Field(default=None, description="Effort classification label")
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
                    "hr_zone": 3,
                    "respiration_rate": 22,
                    "cadence": 80,
                    "temperature_c": 18,
                    "surface_type": "paved",
                    "effort_level": "steady",
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


class GarminDateRange(BaseModel):
    """Earliest and latest Garmin activity timestamps in the database."""

    min_date: datetime = Field(description="Timestamp of the earliest Garmin activity")
    max_date: datetime = Field(description="Timestamp of the latest Garmin activity")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "min_date": "2025-11-08T18:21:13+00:00",
                    "max_date": "2026-04-06T20:00:00+00:00",
                }
            ]
        }
    }


class GarminSyncResponse(BaseModel):
    """Response payload for Garmin on-demand sync trigger requests."""

    status: str = Field(description="Sync trigger status (accepted, conflict, bad_request, error)")
    message: str = Field(description="Human-readable status message")
    triggered_at: datetime | None = Field(default=None, description="UTC timestamp when sync was triggered")
    started_at: datetime | None = Field(default=None, description="UTC timestamp when active sync started")
    lookback: int | None = Field(default=None, description="Effective lookback override used for this trigger")
    window_hours: int | None = Field(default=None, description="Effective window in hours used for this trigger")
    window_start: datetime | None = Field(default=None, description="Computed UTC window start timestamp")

    model_config = {
        "extra": "allow",
        "json_schema_extra": {
            "examples": [
                {
                    "status": "accepted",
                    "message": "Sync started",
                    "triggered_at": "2026-03-12T01:25:14.586353+00:00",
                    "window_hours": 48,
                    "window_start": "2026-03-10T01:25:14.586331+00:00",
                },
                {
                    "status": "conflict",
                    "message": "Sync already in progress",
                    "started_at": "2026-03-12T01:24:58.102924+00:00",
                },
            ]
        },
    }


class GarminActivityTotal(BaseModel):
    """Aggregated Garmin activity totals for a single time bucket (week/month/year)."""

    period_start: date_type = Field(description="UTC start date of the period bucket (week/month/year)")
    activity_count: int = Field(description="Number of activities recorded in the period")
    total_distance_km: float | None = Field(default=None, description="Sum of distance in kilometres")
    total_duration_seconds: int | None = Field(
        default=None, description="Sum of active duration in seconds (excludes pauses)"
    )
    total_ascent_m: int | None = Field(default=None, description="Sum of elevation gain in meters")
    total_calories: int | None = Field(default=None, description="Sum of calories burned")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "period_start": "2025-05-01",
                    "activity_count": 12,
                    "total_distance_km": 632.4,
                    "total_duration_seconds": 90123,
                    "total_ascent_m": 4521,
                    "total_calories": 18234,
                }
            ]
        }
    }


class GarminActivityManualUpdate(BaseModel):
    """Partial manual update payload for Garmin activity records."""

    sport: str | None = Field(default=None, description="Primary sport type (e.g. cycling, running)")
    sub_sport: str | None = Field(default=None, description="Sub-sport classification (e.g. road, trail)")
    start_time: datetime | None = Field(default=None, description="Activity start time in UTC")
    end_time: datetime | None = Field(default=None, description="Activity end time in UTC")
    distance_km: float | None = Field(default=None, description="Total distance in kilometres")
    duration_seconds: int | None = Field(default=None, description="Active duration in seconds (excludes pauses)")
    avg_heart_rate: int | None = Field(default=None, description="Average heart rate in beats per minute")
    max_heart_rate: int | None = Field(default=None, description="Maximum heart rate in beats per minute")
    min_heart_rate: int | None = Field(default=None, description="Minimum heart rate in beats per minute")
    aerobic_training_effect: float | None = Field(default=None, description="Aerobic training effect score")
    anaerobic_training_effect: float | None = Field(default=None, description="Anaerobic training effect score")
    exercise_load: int | None = Field(default=None, description="Exercise load score")
    avg_respiration_rate: int | None = Field(default=None, description="Average respiration rate in breaths per minute")
    min_respiration_rate: int | None = Field(default=None, description="Minimum respiration rate in breaths per minute")
    max_respiration_rate: int | None = Field(default=None, description="Maximum respiration rate in breaths per minute")
    sweat_loss_ml: int | None = Field(default=None, description="Estimated sweat loss in millilitres")
    moderate_intensity_minutes: int | None = Field(default=None, description="Moderate intensity minutes")
    vigorous_intensity_minutes: int | None = Field(default=None, description="Vigorous intensity minutes")
    total_intensity_minutes: int | None = Field(default=None, description="Total intensity minutes")
    paved_distance_km: float | None = Field(default=None, description="Distance over paved surfaces in kilometres")
    unpaved_distance_km: float | None = Field(default=None, description="Distance over unpaved surfaces in kilometres")
    avg_cadence: int | None = Field(default=None, description="Average cadence in RPM")
    max_cadence: int | None = Field(default=None, description="Maximum cadence in RPM")
    total_strokes: int | None = Field(default=None, description="Total activity strokes")
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
        default=None,
        description="Total elapsed time in seconds (includes pauses)",
    )
    total_timer_time: float | None = Field(default=None, description="Total timer time in seconds (active recording)")
    uploaded_at: datetime | None = Field(default=None, description="UTC timestamp when the FIT file was uploaded")

    model_config = {
        "extra": "forbid",
        "json_schema_extra": {
            "examples": [
                {
                    "avg_heart_rate": 141,
                    "max_heart_rate": 172,
                    "avg_cadence": 82,
                    "aerobic_training_effect": 3.2,
                    "device_manufacturer": "polar_electro",
                }
            ]
        },
    }
