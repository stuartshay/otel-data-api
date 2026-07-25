"""Timed integration tests against the live homelab database.

Opt-in only (excluded from the default `pytest` run via the `db_integration`
marker registered in pyproject.toml, since these need real network access to
the production Postgres instance at PGBOUNCER_HOST). Run with:

    pytest -m db_integration -v -s

Credentials are read from `.env` via python-dotenv, the same way
`app.config.Config.from_env()` and `run.py` already do. All queries here are
read-only SELECTs against production -- no mutations.

These tests exist to (a) prove the daily_activity_summary materialized-view
fix (migration 000037 in homelab-database-migrations) and (b) record
baseline/regression-guard timings for the other slow-query patterns
identified via New Relic APM span analysis. Most of those are *not* fixed by
a schema change -- see each test's docstring for why.
"""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator, Awaitable
from datetime import date

import pytest
from dotenv import load_dotenv

from app.config import Config
from app.database import DatabaseService

pytestmark = pytest.mark.db_integration


@pytest.fixture()
async def live_db() -> AsyncGenerator[DatabaseService]:
    """Real DatabaseService pointed at the live homelab DB (.env config).

    Function-scoped (not module/session) because pytest-asyncio 1.x gives
    each test function its own event loop under `asyncio_mode = "auto"`,
    and an asyncpg pool can't be reused across loops. Skips the test if the
    DB is unreachable, so this suite is safe to run without homelab network
    access.
    """
    load_dotenv(override=False)
    config = Config.from_env()
    db = DatabaseService(config)
    try:
        await db.initialize()
        await db.fetchval("SELECT 1")
    except Exception as exc:  # noqa: BLE001 - any connection failure means "skip"
        await db.close()
        pytest.skip(f"live DB unreachable: {exc}")
    try:
        yield db
    finally:
        await db.close()


async def _timed[T](coro: Awaitable[T]) -> tuple[T, float]:
    """Run `coro`, returning (result, elapsed_ms)."""
    start = time.perf_counter()
    result = await coro
    return result, (time.perf_counter() - start) * 1000.0


@pytest.mark.asyncio
async def test_daily_activity_summary_is_fast(live_db: DatabaseService) -> None:
    """daily_activity_summary should be fast after migration 000037.

    Pre-fix (plain VIEW): New Relic showed 99% of calls >500ms (avg 814ms).
    `EXPLAIN (ANALYZE, BUFFERS)` against prod measured 1510ms for this exact
    query -- a full Seq Scan + external disk sort of all 294,907 `locations`
    rows happened before the date filter could even apply, because a plain
    view can't push the WHERE clause below the GROUP BY aggregation.
    Post-fix (MATERIALIZED VIEW, ~1,556 total rows), this should complete in
    low single-digit ms. Query matches app/routers/unified.py's
    list_daily_summaries handler.
    """
    _, duration_ms = await _timed(
        live_db.fetchval(
            "SELECT COUNT(*) FROM daily_activity_summary WHERE activity_date >= $1::date AND activity_date <= $2::date",
            date(2020, 1, 1),
            date(2030, 1, 1),
        )
    )
    print(f"\n[daily_activity_summary] COUNT(*) took {duration_ms:.2f}ms")
    assert duration_ms < 100, (
        f"daily_activity_summary took {duration_ms:.2f}ms -- expected <100ms after migration 000037. "
        "Has the migration been applied to this database? (make prod-up in homelab-database-migrations)"
    )


@pytest.mark.asyncio
async def test_geocoded_addresses_nearest_match_regression_guard(live_db: DatabaseService) -> None:
    """Reverse-geocode nearest-match lookup: regression guard, not a fix target.

    This query (app.routers.geocoding._find_nearby_address) was already
    optimized in #165/#166/#167 to run per-source, hitting the existing
    partial unique indexes (uniq_geocoded_addresses_owntracks_location /
    uniq_geocoded_addresses_garmin_track_point). `EXPLAIN ANALYZE` against
    prod confirms it executes in well under 1ms in isolation. The
    multi-second tail New Relic reports for this query is contention from
    other expensive concurrent queries (see the track-points/coverage tests
    below), not a missing index -- so this test's threshold is generous
    (500ms covers this helper's 2-4 sequential round trips even from a
    dev/sandbox client with real network latency to the homelab DB, not
    just an in-cluster caller sitting next to PgBouncer). It exists to catch
    a *future* index regression, not to validate a fix made here.
    """
    from app.routers.geocoding import _find_nearby_address

    row = await live_db.fetchrow(
        "SELECT latitude, longitude FROM public.locations WHERE geog IS NOT NULL ORDER BY id DESC LIMIT 1"
    )
    if row is None:
        pytest.skip("no locations with geog set to test against")
    assert row is not None  # narrows for type checkers; skip() above never returns

    _, duration_ms = await _timed(_find_nearby_address(live_db, lat=row["latitude"], lon=row["longitude"]))
    print(f"\n[geocoded_addresses nearest-match] took {duration_ms:.2f}ms")
    assert duration_ms < 500, f"nearest-address lookup took {duration_ms:.2f}ms -- possible index regression"


@pytest.mark.asyncio
async def test_garmin_track_points_full_fetch_baseline(live_db: DatabaseService) -> None:
    """Full-track fetch by activity_id: baseline only, not fixed here.

    Indexes are already correct (composite unique (activity_id, timestamp)
    index + GiST on geog). New Relic's 15s max is raw data volume: some
    activities return tens of thousands of unpaginated rows/columns. This
    test documents today's baseline against the largest real activity in the
    DB; capping/paginating large-activity responses is a separate follow-up,
    not addressed here. Query matches
    app/routers/garmin.py's chart-data handler.
    """
    row = await live_db.fetchrow(
        "SELECT activity_id, COUNT(*) AS n FROM public.garmin_track_points GROUP BY activity_id ORDER BY n DESC LIMIT 1"
    )
    if row is None:
        pytest.skip("no garmin_track_points to test against")
    assert row is not None  # narrows for type checkers; skip() above never returns

    _, duration_ms = await _timed(
        live_db.fetch(
            "SELECT latitude, longitude, timestamp, altitude, distance_from_start_km, "
            "speed_kmh, heart_rate, hr_zone, respiration_rate, cadence, temperature_c, "
            "surface_type, effort_level FROM public.garmin_track_points "
            "WHERE activity_id = $1 ORDER BY timestamp ASC",
            row["activity_id"],
        )
    )
    print(
        f"\n[garmin_track_points full fetch] activity_id={row['activity_id']} ({row['n']} points) took {duration_ms:.2f}ms"
    )
    assert duration_ms < 4000, (
        f"full-track fetch for activity {row['activity_id']} ({row['n']} points) took {duration_ms:.2f}ms"
    )


@pytest.mark.asyncio
async def test_mv_garmin_track_point_cells_coverage_baseline(live_db: DatabaseService) -> None:
    """Geocoding coverage aggregate: cold-cache baseline, not sped up here.

    Full-table aggregate over mv_garmin_track_point_cells with no WHERE
    clause -- indexes can't speed up an unfiltered aggregate (~556k rows).
    New Relic showed 100% of raw calls >500ms (avg ~1s). The app-layer fix
    (this test bypasses, since it hits the DB directly) is a longer,
    dedicated cache TTL for just this portion of GET /status
    (_MV_METRICS_CACHE_TTL_SECONDS = 600s in app/routers/geocoding.py,
    decoupled from the 60s _STATUS_CACHE_TTL_SECONDS the rest of the
    response uses), which cuts how often this query runs by ~10x without
    touching the query itself. This test documents the unavoidable
    cold-cache/cache-miss cost -- see test_geocoding.py's
    test_geocoding_status_mv_metrics_outlive_status_cache_expiry for the
    caching behavior itself.
    """
    row, duration_ms = await _timed(
        live_db.fetchrow(
            "SELECT COUNT(*)::BIGINT AS dense_total_cells, "
            "COALESCE(SUM(m.point_count), 0)::BIGINT AS total_track_points, "
            "COALESCE(SUM(m.point_count) FILTER (WHERE g.lat_4dp IS NOT NULL), 0)::BIGINT AS covered_track_points "
            "FROM public.mv_garmin_track_point_cells m "
            "LEFT JOIN public.geocoded_point_cells g USING (lat_4dp, lon_4dp)"
        )
    )
    print(f"\n[mv_garmin_track_point_cells coverage] took {duration_ms:.2f}ms ({dict(row) if row else row})")
    assert duration_ms < 3000, (
        f"coverage aggregate took {duration_ms:.2f}ms -- unexpectedly slow even for an unfiltered scan"
    )


@pytest.mark.asyncio
async def test_segment_efforts_pairs_regression_guard(live_db: DatabaseService) -> None:
    """Segment-crossing effort matching: partially fixed, this test guards the fix.

    New Relic showed this as the single most expensive query pattern (avg
    3.26s, max 11.25s, 50% of calls >500ms). The `pairs` CTE (matching each
    start-crossing to its nearest later end-crossing) used a
    crossings-JOIN-crossings self-join with no index to drive it -- a full
    activity_id x activity_id nested loop, quadratic in the number of
    crossings. Rewritten to a single ordered window pass
    (`app.routers.garmin._fetch_segment_efforts`'s `pairs`/`pairs_raw` CTEs).
    Verified against prod with wide parameters (200m tolerance, all sports)
    around the busiest real track in the DB: identical results, ~25-30%
    faster (785-823ms -> 547-647ms over 3 runs) at that scale, with the win
    expected to grow for segments crossed by many more activities/laps since
    the removed cost was O(n^2) in crossing count, not O(n log n).

    The other major cost component here -- the crossing_hits/crossing_grouped
    window-function pipeline over all candidate track points -- is a larger,
    separate follow-up, not addressed by this test or the fix it guards.
    """
    row = await live_db.fetchrow(
        "SELECT t.activity_id, "
        "(SELECT longitude FROM public.garmin_track_points WHERE activity_id = t.activity_id ORDER BY timestamp ASC LIMIT 1) AS start_lon, "
        "(SELECT latitude FROM public.garmin_track_points WHERE activity_id = t.activity_id ORDER BY timestamp ASC LIMIT 1) AS start_lat, "
        "(SELECT longitude FROM public.garmin_track_points WHERE activity_id = t.activity_id ORDER BY timestamp DESC LIMIT 1) AS end_lon, "
        "(SELECT latitude FROM public.garmin_track_points WHERE activity_id = t.activity_id ORDER BY timestamp DESC LIMIT 1) AS end_lat "
        "FROM public.garmin_track_points t "
        "GROUP BY t.activity_id ORDER BY COUNT(*) DESC LIMIT 1"
    )
    if row is None:
        pytest.skip("no garmin_track_points to test against")
    assert row is not None  # narrows for type checkers; skip() above never returns

    from app.routers.garmin import _fetch_segment_efforts

    _, duration_ms = await _timed(
        _fetch_segment_efforts(
            live_db,
            start_lat=row["start_lat"],
            start_lon=row["start_lon"],
            end_lat=row["end_lat"],
            end_lon=row["end_lon"],
            tolerance_meters=200.0,
            sport=None,
            date_from=None,
            date_to=None,
            max_effort_seconds=7200,
            limit=20,
        )
    )
    print(f"\n[segment-efforts pairs] activity_id={row['activity_id']} took {duration_ms:.2f}ms")
    assert duration_ms < 5000, f"segment-efforts took {duration_ms:.2f}ms -- possible regression in the pairs rewrite"
