"""Locust load test suite simulating otel-data-ui user journeys.

Four user personas mirror real frontend traffic patterns:
- LocationBrowser:   Browsing OwnTracks locations and device data
- GarminExplorer:    Viewing Garmin cycling activities and track points
- MapViewer:         Using unified GPS map and daily summary
- SpatialAnalyst:    Running nearby/distance/within-reference spatial queries

Usage:
    locust -f locustfile.py --host https://api.lab.informationcart.com
"""

from __future__ import annotations

import random

from locust import HttpUser, between, tag, task

# ---------------------------------------------------------------------------
# Realistic parameter pools
# ---------------------------------------------------------------------------
DEVICE_IDS = ["iphone_stuart", "phone"]
SPORTS = ["cycling"]
# Pre-seeded activity IDs (updated dynamically at runtime by on_start)
ACTIVITY_IDS = [21100373038, 20932993811, 20874087125]
REFERENCE_NAMES = ["home"]
# Approximate coordinates around NYC for spatial queries
NYC_LAT = 40.7362
NYC_LON = -74.0394


def _random_date_range() -> dict[str, str]:
    """Return a random month from 2025 as a date range (1st to 28th)."""
    month = random.randint(1, 12)
    return {
        "date_from": f"2025-{month:02d}-01",
        "date_to": f"2025-{month:02d}-28",
    }


# ---------------------------------------------------------------------------
# User personas
# ---------------------------------------------------------------------------


class LocationBrowser(HttpUser):
    """Simulates a user browsing OwnTracks location data."""

    weight = 4  # most common flow
    wait_time = between(1, 3)

    @tag("health")
    @task(1)
    def health_check(self) -> None:
        self.client.get("/health", name="/health")

    @tag("health")
    @task(1)
    def readiness_check(self) -> None:
        self.client.get("/ready", name="/ready")

    @tag("locations")
    @task(5)
    def list_locations(self) -> None:
        device = random.choice(DEVICE_IDS)
        params = {"device_id": device, "limit": 50, "offset": 0, "sort": "created_at", "order": "desc"}
        self.client.get("/api/v1/locations", params=params, name="/api/v1/locations")

    @tag("locations")
    @task(3)
    def list_locations_with_dates(self) -> None:
        dates = _random_date_range()
        params = {"limit": 50, "offset": 0, **dates}
        self.client.get("/api/v1/locations", params=params, name="/api/v1/locations [date filter]")

    @tag("locations")
    @task(2)
    def list_devices(self) -> None:
        self.client.get("/api/v1/locations/devices", name="/api/v1/locations/devices")

    @tag("locations")
    @task(2)
    def location_count(self) -> None:
        device = random.choice(DEVICE_IDS)
        self.client.get("/api/v1/locations/count", params={"device_id": device}, name="/api/v1/locations/count")

    @tag("locations")
    @task(3)
    def view_location_detail(self) -> None:
        # First fetch the list to get a valid ID
        with self.client.get(
            "/api/v1/locations", params={"limit": 5}, name="/api/v1/locations [for detail]", catch_response=True
        ) as resp:
            if resp.status_code == 200:
                items = resp.json().get("items", [])
                if items:
                    loc_id = random.choice(items)["id"]
                    self.client.get(f"/api/v1/locations/{loc_id}", name="/api/v1/locations/{id}")


class GarminExplorer(HttpUser):
    """Simulates a user exploring Garmin cycling activities."""

    weight = 3
    wait_time = between(2, 5)

    def on_start(self) -> None:
        """Fetch current activity IDs for realistic requests."""
        self.activity_ids = list(ACTIVITY_IDS)  # per-instance copy
        resp = self.client.get(
            "/api/v1/garmin/activities", params={"limit": 10}, name="/api/v1/garmin/activities [init]"
        )
        if resp.status_code == 200:
            items = resp.json().get("items", [])
            if items:
                self.activity_ids = [item["activity_id"] for item in items]

    @tag("garmin")
    @task(5)
    def list_activities(self) -> None:
        params = {"limit": 50, "offset": 0, "sort": "start_time", "order": "desc"}
        self.client.get("/api/v1/garmin/activities", params=params, name="/api/v1/garmin/activities")

    @tag("garmin")
    @task(3)
    def list_activities_filtered(self) -> None:
        dates = _random_date_range()
        params = {"sport": random.choice(SPORTS), "limit": 50, "offset": 0, **dates}
        self.client.get("/api/v1/garmin/activities", params=params, name="/api/v1/garmin/activities [filtered]")

    @tag("garmin")
    @task(2)
    def list_sports(self) -> None:
        self.client.get("/api/v1/garmin/sports", name="/api/v1/garmin/sports")

    @tag("garmin")
    @task(4)
    def view_activity_detail(self) -> None:
        if self.activity_ids:
            activity_id = random.choice(self.activity_ids)
            self.client.get(f"/api/v1/garmin/activities/{activity_id}", name="/api/v1/garmin/activities/{id}")

    @tag("garmin")
    @task(3)
    def view_track_points(self) -> None:
        if self.activity_ids:
            activity_id = random.choice(self.activity_ids)
            self.client.get(
                f"/api/v1/garmin/activities/{activity_id}/tracks",
                params={"limit": 500, "sort": "timestamp", "order": "asc"},
                name="/api/v1/garmin/activities/{id}/tracks",
            )

    @tag("garmin")
    @task(2)
    def view_chart_data(self) -> None:
        if self.activity_ids:
            activity_id = random.choice(self.activity_ids)
            self.client.get(
                f"/api/v1/garmin/activities/{activity_id}/chart-data",
                name="/api/v1/garmin/activities/{id}/chart-data",
            )


class MapViewer(HttpUser):
    """Simulates a user viewing the unified GPS map and daily summary."""

    weight = 3
    wait_time = between(2, 4)

    @tag("unified")
    @task(5)
    def unified_gps(self) -> None:
        dates = _random_date_range()
        params = {"limit": 100, "offset": 0, "order": "desc", **dates}
        self.client.get("/api/v1/gps/unified", params=params, name="/api/v1/gps/unified")

    @tag("unified")
    @task(3)
    def unified_gps_by_source(self) -> None:
        source = random.choice(["owntracks", "garmin"])
        params = {"source": source, "limit": 100, "offset": 0}
        self.client.get("/api/v1/gps/unified", params=params, name="/api/v1/gps/unified [source]")

    @tag("unified")
    @task(4)
    def daily_summary(self) -> None:
        dates = _random_date_range()
        params = {"limit": 30, **dates}
        self.client.get("/api/v1/gps/daily-summary", params=params, name="/api/v1/gps/daily-summary")

    @tag("reference")
    @task(2)
    def list_reference_locations(self) -> None:
        self.client.get("/api/v1/reference-locations", name="/api/v1/reference-locations")


class SpatialAnalyst(HttpUser):
    """Simulates a user running spatial/proximity queries."""

    weight = 2  # less common flow
    wait_time = between(3, 6)

    @tag("spatial")
    @task(4)
    def find_nearby(self) -> None:
        # Small random jitter around NYC coordinates
        lat = NYC_LAT + random.uniform(-0.05, 0.05)
        lon = NYC_LON + random.uniform(-0.05, 0.05)
        radius = random.choice([500, 1000, 2000, 5000])
        params = {"lat": round(lat, 4), "lon": round(lon, 4), "radius_meters": radius, "limit": 100}
        self.client.get("/api/v1/spatial/nearby", params=params, name="/api/v1/spatial/nearby")

    @tag("spatial")
    @task(3)
    def calculate_distance(self) -> None:
        params = {
            "from_lat": NYC_LAT,
            "from_lon": NYC_LON,
            "to_lat": NYC_LAT + random.uniform(-0.1, 0.1),
            "to_lon": NYC_LON + random.uniform(-0.1, 0.1),
        }
        self.client.get("/api/v1/spatial/distance", params=params, name="/api/v1/spatial/distance")

    @tag("spatial")
    @task(2)
    def within_reference(self) -> None:
        name = random.choice(REFERENCE_NAMES)
        self.client.get(
            f"/api/v1/spatial/within-reference/{name}",
            params={"limit": 100},
            name="/api/v1/spatial/within-reference/{name}",
        )

    @tag("reference")
    @task(1)
    def list_reference_locations(self) -> None:
        self.client.get("/api/v1/reference-locations", name="/api/v1/reference-locations")
