"""Pydantic models for reference locations."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ReferenceLocation(BaseModel):
    """Named geographic reference point used for spatial queries (e.g. home, office)."""

    id: int = Field(description="Unique reference location identifier")
    name: str = Field(description="Short, unique name for the location (e.g. home, office)")
    latitude: float = Field(description="GPS latitude in decimal degrees (WGS 84)")
    longitude: float = Field(description="GPS longitude in decimal degrees (WGS 84)")
    radius_meters: int = Field(default=50, description="Geofence radius in meters for proximity queries")
    description: str | None = Field(default=None, description="Optional human-readable description of the location")
    created_at: datetime | None = Field(default=None, description="UTC timestamp when the record was created")
    updated_at: datetime | None = Field(default=None, description="UTC timestamp when the record was last updated")

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
                    "created_at": "2026-02-03T22:49:07+00:00",
                    "updated_at": "2026-02-03T22:50:01+00:00",
                }
            ]
        }
    }


class ReferenceLocationCreate(BaseModel):
    """Request body for creating a new reference location."""

    name: str = Field(description="Short, unique name for the location (e.g. home, office)")
    latitude: float = Field(description="GPS latitude in decimal degrees (WGS 84)")
    longitude: float = Field(description="GPS longitude in decimal degrees (WGS 84)")
    radius_meters: int = Field(default=50, description="Geofence radius in meters for proximity queries")
    description: str | None = Field(default=None, description="Optional human-readable description of the location")

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
    """Request body for partially updating a reference location. All fields are optional."""

    name: str | None = Field(default=None, description="Updated location name")
    latitude: float | None = Field(default=None, description="Updated GPS latitude in decimal degrees")
    longitude: float | None = Field(default=None, description="Updated GPS longitude in decimal degrees")
    radius_meters: int | None = Field(default=None, description="Updated geofence radius in meters")
    description: str | None = Field(default=None, description="Updated description text")

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
