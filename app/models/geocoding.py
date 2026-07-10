"""Pydantic models for geocoding management endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

WaypointKind = Literal["start", "end", "waypoint"]

# Shared field-description constants (reused across address models to avoid
# duplicating the same literal in multiple Field(...) definitions).
DESC_DISPLAY_ADDRESS = "Full formatted address label from Pelias"
DESC_STREET = "Street name"
DESC_HOUSENUMBER = "House or building number"
DESC_NEIGHBOURHOOD = "Neighbourhood name"
DESC_LOCALITY = "City or town"
DESC_REGION = "State or province"
DESC_COUNTRY = "Country name"
DESC_POSTALCODE = "Postal or ZIP code"
DESC_CONFIDENCE = "Pelias confidence score (0-1)"
DESC_STATUS = "Geocoding status: success, no_coverage, error, pending"
DESC_GEOCODED_AT = "UTC timestamp when geocoding was performed"


class GeocodedAddress(BaseModel):
    """Reverse-geocoded address components from Pelias."""

    display_address: str | None = Field(default=None, description=DESC_DISPLAY_ADDRESS)
    street: str | None = Field(default=None, description=DESC_STREET)
    housenumber: str | None = Field(default=None, description=DESC_HOUSENUMBER)
    neighbourhood: str | None = Field(default=None, description=DESC_NEIGHBOURHOOD)
    locality: str | None = Field(default=None, description=DESC_LOCALITY)
    region: str | None = Field(default=None, description=DESC_REGION)
    country: str | None = Field(default=None, description=DESC_COUNTRY)
    postalcode: str | None = Field(default=None, description=DESC_POSTALCODE)
    confidence: float | None = Field(default=None, description=DESC_CONFIDENCE)
    status: str = Field(description=DESC_STATUS)
    geocoded_at: datetime | None = Field(default=None, description=DESC_GEOCODED_AT)

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
    by_source: GeocodingStatusBySource = Field(
        description="Per-source breakdown of geocoding coverage (owntracks, garmin)",
    )
    dense_cells_total: int = Field(
        default=0,
        description="Total number of distinct 4dp (~11m) GPS cells observed in garmin_track_points",
    )
    dense_cells_geocoded: int = Field(
        default=0,
        description="Number of dense cells with any geocoding row (any status)",
    )
    dense_cells_success: int = Field(default=0, description="Number of dense cells with status='success'")
    dense_cells_pending: int = Field(default=0, description="Number of dense cells awaiting geocoding")
    dense_cells_no_coverage: int = Field(default=0, description="Number of dense cells outside Pelias coverage")
    dense_cells_errors: int = Field(default=0, description="Number of dense cells that failed geocoding")
    dense_point_coverage_percent: float = Field(
        default=0.0,
        description="Percentage of garmin_track_points whose 4dp cell has any geocoded row",
    )

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


class GeocodingSourceStatus(BaseModel):
    """Coverage statistics for a single geocoding source (owntracks or garmin)."""

    success: int = Field(description="Number of successfully geocoded records for this source")
    pending: int = Field(default=0, description="Number of records awaiting geocoding for this source")
    no_coverage: int = Field(description="Number of records outside Pelias coverage area")
    errors: int = Field(description="Number of records that failed geocoding")
    total: int = Field(description="Total number of geocoded_addresses rows for this source")


class GeocodingStatusBySource(BaseModel):
    """Per-source breakdown of geocoding coverage."""

    owntracks: GeocodingSourceStatus = Field(description="Coverage stats for OwnTracks rows")
    garmin: GeocodingSourceStatus = Field(description="Coverage stats for Garmin rows")
    garmin_activities_total: int = Field(
        description="Total number of Garmin activities (denominator for activity-level coverage)"
    )
    garmin_activities_geocoded: int = Field(
        description="Number of Garmin activities that have at least one address row"
    )
    garmin_coverage_percent: float = Field(
        description="Percentage of Garmin activities with at least one geocoded address"
    )
    garmin_waypoint_success_percent: float = Field(
        default=0.0,
        description=(
            "Percentage of Garmin waypoint rows with status='success' "
            "(success / (success + pending + no_coverage + error))."
        ),
    )


class PeliasHealth(BaseModel):
    """Result of an upstream Pelias reverse-geocoder health probe."""

    healthy: bool = Field(description="True when Pelias returned a usable feature for the probe coordinate.")
    latency_ms: float = Field(description="Round-trip latency for the probe request, in milliseconds.")
    sample_features_count: int = Field(
        default=0, description="Number of features returned by the probe (0 means the probe failed)."
    )
    detail: str | None = Field(
        default=None,
        description="Failure detail when not healthy (timeout, transport error, non-2xx status).",
    )


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


class GarminActivityAddress(BaseModel):
    """Reverse-geocoded address attached to a Garmin activity waypoint."""

    track_point_id: int = Field(description="garmin_track_points.id this address was geocoded from")
    activity_id: str = Field(description="Parent Garmin activity identifier")
    waypoint_kind: WaypointKind = Field(description="Role of this waypoint: start, end, or mid-route waypoint")
    timestamp: datetime = Field(description="UTC timestamp of the track point this address was derived from")
    latitude: float = Field(description="GPS latitude in decimal degrees (WGS 84)")
    longitude: float = Field(description="GPS longitude in decimal degrees (WGS 84)")
    display_address: str | None = Field(default=None, description=DESC_DISPLAY_ADDRESS)
    street: str | None = Field(default=None, description=DESC_STREET)
    housenumber: str | None = Field(default=None, description=DESC_HOUSENUMBER)
    neighbourhood: str | None = Field(default=None, description=DESC_NEIGHBOURHOOD)
    locality: str | None = Field(default=None, description=DESC_LOCALITY)
    region: str | None = Field(default=None, description=DESC_REGION)
    country: str | None = Field(default=None, description=DESC_COUNTRY)
    postalcode: str | None = Field(default=None, description=DESC_POSTALCODE)
    confidence: float | None = Field(default=None, description=DESC_CONFIDENCE)
    status: str = Field(description=DESC_STATUS)
    geocoded_at: datetime | None = Field(default=None, description=DESC_GEOCODED_AT)


class GeocodedAddressSummary(BaseModel):
    """Compact address summary embedded in track-point payloads."""

    display_address: str | None = Field(default=None, description=DESC_DISPLAY_ADDRESS)
    street: str | None = Field(default=None, description=DESC_STREET)
    housenumber: str | None = Field(default=None, description=DESC_HOUSENUMBER)
    neighbourhood: str | None = Field(default=None, description=DESC_NEIGHBOURHOOD)
    locality: str | None = Field(default=None, description=DESC_LOCALITY)
    region: str | None = Field(default=None, description=DESC_REGION)
    country: str | None = Field(default=None, description=DESC_COUNTRY)
    postalcode: str | None = Field(default=None, description=DESC_POSTALCODE)
    confidence: float | None = Field(default=None, description=DESC_CONFIDENCE)
    waypoint_kind: WaypointKind | None = Field(default=None, description="Role of this waypoint (Garmin only)")
    status: str = Field(description=DESC_STATUS)
    geocoded_at: datetime | None = Field(default=None, description=DESC_GEOCODED_AT)
