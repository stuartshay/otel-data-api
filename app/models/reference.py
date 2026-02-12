"""Pydantic models for reference locations."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ReferenceLocation(BaseModel):
    id: int
    name: str
    latitude: float
    longitude: float
    radius_meters: int = 50
    description: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "id": 1,
                    "name": "home",
                    "latitude": 40.7362,
                    "longitude": -74.0394,
                    "radius_meters": 40,
                    "description": "Primary apartment - 40m radius",
                    "created_at": "2026-02-03T22:49:07Z",
                    "updated_at": "2026-02-03T22:50:01Z",
                }
            ]
        }
    }


class ReferenceLocationCreate(BaseModel):
    name: str
    latitude: float
    longitude: float
    radius_meters: int = 50
    description: str | None = None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "name": "office",
                    "latitude": 40.7128,
                    "longitude": -74.006,
                    "radius_meters": 100,
                    "description": "Downtown office building",
                }
            ]
        }
    }


class ReferenceLocationUpdate(BaseModel):
    name: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    radius_meters: int | None = None
    description: str | None = None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "radius_meters": 75,
                    "description": "Updated radius for office building",
                }
            ]
        }
    }
