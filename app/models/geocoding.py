"""Pydantic models for geocoding management endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class GeocodedAddress(BaseModel):
    """Reverse-geocoded address components from Pelias."""

    display_address: str | None = Field(default=None, description="Full formatted address label from Pelias")
    street: str | None = Field(default=None, description="Street name")
    housenumber: str | None = Field(default=None, description="House or building number")
    neighbourhood: str | None = Field(default=None, description="Neighbourhood name")
    locality: str | None = Field(default=None, description="City or town")
    region: str | None = Field(default=None, description="State or province")
    country: str | None = Field(default=None, description="Country name")
    postalcode: str | None = Field(default=None, description="Postal or ZIP code")
    confidence: float | None = Field(default=None, description="Pelias confidence score (0-1)")
    status: str = Field(description="Geocoding status: success, no_coverage, error, pending")
    geocoded_at: datetime | None = Field(default=None, description="UTC timestamp when geocoding was performed")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "display_address": "123 Main St, Hoboken, NJ 07030",
                    "street": "Main St",
                    "housenumber": "123",
                    "neighbourhood": "Downtown",
                    "locality": "Hoboken",
                    "region": "New Jersey",
                    "country": "United States",
                    "postalcode": "07030",
                    "confidence": 0.95,
                    "status": "success",
                    "geocoded_at": "2026-02-12T08:10:55+00:00",
                }
            ]
        }
    }


class GeocodingStatus(BaseModel):
    """Coverage statistics for geocoded location records."""

    total_locations: int = Field(description="Total number of OwnTracks location records")
    geocoded: int = Field(description="Number of locations with a geocoded address (any status)")
    success: int = Field(description="Number of successfully geocoded locations")
    pending: int = Field(description="Number of locations awaiting geocoding")
    no_coverage: int = Field(description="Number of locations outside Pelias coverage area")
    errors: int = Field(description="Number of locations that failed geocoding")
    coverage_percent: float = Field(description="Percentage of locations with a geocoded address")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "total_locations": 45000,
                    "geocoded": 12000,
                    "success": 11500,
                    "pending": 33000,
                    "no_coverage": 400,
                    "errors": 100,
                    "coverage_percent": 26.67,
                }
            ]
        }
    }


class GeocodingTriggerResponse(BaseModel):
    """Result of triggering a batch geocoding operation."""

    processed: int = Field(description="Number of records processed in this batch")
    remaining: int = Field(description="Number of records still awaiting geocoding")
    skipped_dedup: int = Field(description="Number of records skipped via proximity deduplication")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "processed": 100,
                    "remaining": 32900,
                    "skipped_dedup": 35,
                }
            ]
        }
    }
