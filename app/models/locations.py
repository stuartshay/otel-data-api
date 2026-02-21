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
    raw_payload: dict | None = None

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
    device_id: str

    model_config = {"json_schema_extra": {"examples": [{"device_id": "iphone_stuart"}]}}


class LocationCount(BaseModel):
    count: int
    date: str | None = None
    device_id: str | None = None

    model_config = {"json_schema_extra": {"examples": [{"count": 45883, "date": None, "device_id": "iphone_stuart"}]}}
