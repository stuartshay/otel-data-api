"""Pydantic models for OwnTracks location data."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class Location(BaseModel):
    """GPS location recorded by the OwnTracks mobile app."""

    id: int = Field(description="Unique location record identifier")
    device_id: str = Field(description="OwnTracks device identifier (e.g. iphone_stuart)")
    tid: str | None = Field(default=None, description="Two-character tracker ID set in the OwnTracks app")
    latitude: float = Field(description="GPS latitude in decimal degrees (WGS 84)")
    longitude: float = Field(description="GPS longitude in decimal degrees (WGS 84)")
    accuracy: int | None = Field(default=None, description="Horizontal accuracy of the GPS fix in meters")
    altitude: float | None = Field(default=None, description="Altitude above sea level in meters")
    velocity: int | None = Field(default=None, description="Device velocity in km/h at time of report")
    battery: int | None = Field(default=None, description="Device battery level as a percentage (0-100)")
    battery_status: int | None = Field(
        default=None, description="Battery charging state (0=unknown, 1=unplugged, 2=charging, 3=full)"
    )
    connection_type: str | None = Field(default=None, description="Network connection type (w=WiFi, m=mobile)")
    trigger: str | None = Field(
        default=None, description="What triggered this location report (p=ping, c=circular, t=timer)"
    )
    timestamp: datetime = Field(description="UTC timestamp when the device recorded the location")
    created_at: datetime | None = Field(
        default=None, description="UTC timestamp when the record was inserted into the database"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "id": 101160,
                    "device_id": "iphone_stuart",
                    "tid": "ss",
                    "latitude": 40.736238,
                    "longitude": -74.039405,
                    "accuracy": 7,
                    "altitude": 4,
                    "velocity": None,
                    "battery": 100,
                    "battery_status": 2,
                    "connection_type": "w",
                    "trigger": "t",
                    "timestamp": "2026-02-12T08:10:55+00:00",
                    "created_at": "2026-02-12T08:10:55+00:00",
                }
            ]
        }
    }


class LocationDetail(Location):
    """Full location detail including the original OwnTracks JSON payload."""

    raw_payload: dict | None = Field(
        default=None, description="Original OwnTracks JSON payload as received from the MQTT broker"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "id": 101160,
                    "device_id": "iphone_stuart",
                    "tid": "ss",
                    "latitude": 40.736238,
                    "longitude": -74.039405,
                    "accuracy": 7,
                    "altitude": 4,
                    "velocity": None,
                    "battery": 100,
                    "battery_status": 2,
                    "connection_type": "w",
                    "trigger": "t",
                    "timestamp": "2026-02-12T08:10:55Z",
                    "created_at": "2026-02-12T08:10:55Z",
                    "raw_payload": {
                        "_type": "location",
                        "tid": "ss",
                        "lat": 40.736238,
                        "lon": -74.039405,
                        "acc": 7,
                        "batt": 100,
                    },
                }
            ]
        }
    }


class DeviceInfo(BaseModel):
    """Distinct OwnTracks device identifier."""

    device_id: str = Field(description="OwnTracks device identifier")

    model_config = {"json_schema_extra": {"examples": [{"device_id": "iphone_stuart"}]}}


class LocationCount(BaseModel):
    """Aggregate location count with optional filter context."""

    count: int = Field(description="Total number of location records matching the filter")
    date: str | None = Field(default=None, description="Date filter applied (YYYY-MM-DD), if any")
    device_id: str | None = Field(default=None, description="Device ID filter applied, if any")

    model_config = {"json_schema_extra": {"examples": [{"count": 45883, "date": None, "device_id": "iphone_stuart"}]}}
