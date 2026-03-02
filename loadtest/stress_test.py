"""Stress test to determine otel-data-api connection capacity.

Ramps users in steps: 10 → 25 → 50 → 75 → 100 → 150 → 200
Each step holds for 2 minutes to measure steady-state behavior.
Total runtime: ~14 minutes.

Monitor New Relic during the test:
- Memory usage (should stay under 512Mi limit)
- Response times (p95 degradation signals capacity limit)
- Error rate (5xx errors signal overload)
- DB pool exhaustion (connection timeouts)

Usage:
    locust -f stress_test.py --host https://api.lab.informationcart.com \
        --headless --only-summary
"""

from __future__ import annotations

import random

from locust import HttpUser, LoadTestShape, between, tag, task

# ---------------------------------------------------------------------------
# Realistic parameter pools (same as locustfile.py)
# ---------------------------------------------------------------------------
DEVICE_IDS = ["iphone_stuart", "phone"]
ACTIVITY_IDS = [21100373038, 20932993811, 20874087125]
NYC_LAT = 40.7362
NYC_LON = -74.0394


def _random_date_range() -> dict[str, str]:
    month = random.randint(1, 12)
    return {
        "date_from": f"2025-{month:02d}-01",
        "date_to": f"2025-{month:02d}-28",
    }


# ---------------------------------------------------------------------------
# Step load shape: ramp users in stages
# ---------------------------------------------------------------------------
class StressTestShape(LoadTestShape):
    """Step load test: ramp users progressively to find breaking point.

    Each step runs for `step_duration` seconds at the given user count.
    """

    stages = [
        {"duration": 120, "users": 10, "spawn_rate": 5},
        {"duration": 240, "users": 25, "spawn_rate": 5},
        {"duration": 360, "users": 50, "spawn_rate": 10},
        {"duration": 480, "users": 75, "spawn_rate": 10},
        {"duration": 600, "users": 100, "spawn_rate": 15},
        {"duration": 720, "users": 150, "spawn_rate": 15},
        {"duration": 840, "users": 200, "spawn_rate": 20},
    ]

    def tick(self) -> tuple[int, float] | None:
        run_time = self.get_run_time()
        for stage in self.stages:
            if run_time < stage["duration"]:
                return (stage["users"], stage["spawn_rate"])
        return None


# ---------------------------------------------------------------------------
# Single combined user persona for stress testing
# ---------------------------------------------------------------------------
class StressUser(HttpUser):
    """Combined user persona hitting all endpoint categories."""

    wait_time = between(0.5, 2)

    def on_start(self) -> None:
        self.activity_ids = list(ACTIVITY_IDS)
        resp = self.client.get(
            "/api/v1/garmin/activities",
            params={"limit": 5},
            name="/api/v1/garmin/activities [init]",
        )
        if resp.status_code == 200:
            items = resp.json().get("items", [])
            if items:
                self.activity_ids = [item["activity_id"] for item in items]

    # -- Health (lightweight baseline) --
    @tag("health")
    @task(1)
    def health_check(self) -> None:
        self.client.get("/health", name="/health")

    # -- Locations (most common) --
    @tag("locations")
    @task(5)
    def list_locations(self) -> None:
        device = random.choice(DEVICE_IDS)
        params = {
            "device_id": device,
            "limit": 50,
            "offset": 0,
            "sort": "created_at",
            "order": "desc",
        }
        self.client.get("/api/v1/locations", params=params, name="/api/v1/locations")

    @tag("locations")
    @task(3)
    def list_locations_dates(self) -> None:
        params = {"limit": 50, "offset": 0, **_random_date_range()}
        self.client.get(
            "/api/v1/locations",
            params=params,
            name="/api/v1/locations [date]",
        )

    @tag("locations")
    @task(2)
    def location_detail(self) -> None:
        with self.client.get(
            "/api/v1/locations",
            params={"limit": 5},
            name="/api/v1/locations [for detail]",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                items = resp.json().get("items", [])
                if items:
                    loc_id = random.choice(items)["id"]
                    self.client.get(
                        f"/api/v1/locations/{loc_id}",
                        name="/api/v1/locations/{id}",
                    )

    # -- Garmin --
    @tag("garmin")
    @task(3)
    def list_activities(self) -> None:
        params = {"limit": 50, "offset": 0, "sort": "start_time", "order": "desc"}
        self.client.get(
            "/api/v1/garmin/activities",
            params=params,
            name="/api/v1/garmin/activities",
        )

    @tag("garmin")
    @task(2)
    def activity_tracks(self) -> None:
        if self.activity_ids:
            aid = random.choice(self.activity_ids)
            self.client.get(
                f"/api/v1/garmin/activities/{aid}/tracks",
                params={"limit": 500},
                name="/api/v1/garmin/activities/{id}/tracks",
            )

    # -- Unified GPS --
    @tag("unified")
    @task(3)
    def unified_gps(self) -> None:
        params = {"limit": 100, "offset": 0, "order": "desc", **_random_date_range()}
        self.client.get("/api/v1/gps/unified", params=params, name="/api/v1/gps/unified")

    @tag("unified")
    @task(2)
    def daily_summary(self) -> None:
        params = {"limit": 30, **_random_date_range()}
        self.client.get(
            "/api/v1/gps/daily-summary",
            params=params,
            name="/api/v1/gps/daily-summary",
        )

    # -- Spatial (heavier queries) --
    @tag("spatial")
    @task(2)
    def find_nearby(self) -> None:
        lat = NYC_LAT + random.uniform(-0.05, 0.05)
        lon = NYC_LON + random.uniform(-0.05, 0.05)
        radius = random.choice([500, 1000, 2000, 5000])
        params = {
            "lat": round(lat, 4),
            "lon": round(lon, 4),
            "radius_meters": radius,
            "limit": 100,
        }
        self.client.get("/api/v1/spatial/nearby", params=params, name="/api/v1/spatial/nearby")

    @tag("spatial")
    @task(1)
    def calculate_distance(self) -> None:
        params = {
            "from_lat": NYC_LAT,
            "from_lon": NYC_LON,
            "to_lat": NYC_LAT + random.uniform(-0.1, 0.1),
            "to_lon": NYC_LON + random.uniform(-0.1, 0.1),
        }
        self.client.get(
            "/api/v1/spatial/distance",
            params=params,
            name="/api/v1/spatial/distance",
        )
