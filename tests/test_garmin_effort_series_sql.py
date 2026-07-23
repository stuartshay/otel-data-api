"""PostgreSQL-backed regression tests for Garmin effort-series binning SQL."""

import os
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

from app.routers.garmin import SEGMENT_EFFORT_SERIES_BATCH_SQL, SEGMENT_EFFORT_SERIES_SQL


@pytest.fixture()
async def postgres_connection():
    """Connect to the PostgreSQL instance named by TEST_DATABASE_URL.

    CI points this at an ephemeral `postgres:18-alpine` service container
    that only exists for the job's lifetime (see .github/workflows/lint.yml).
    Locally, TEST_DATABASE_URL is whatever the caller sets it to -- this
    fixture only guards against the database name not looking like a test
    database, since it creates a session-local temp table there. Point it at
    a real database's connection string at your own risk.
    """
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    if "test" not in database_url.rsplit("/", 1)[-1].lower():
        pytest.fail(
            "TEST_DATABASE_URL's database name must contain 'test' as a guard "
            "against accidentally pointing this at a real database"
        )

    connection = await asyncpg.connect(database_url)
    try:
        await connection.execute(
            """
            CREATE TEMP TABLE garmin_track_points (
                activity_id text NOT NULL,
                timestamp timestamptz NOT NULL,
                distance_from_start_km double precision,
                speed_kmh double precision,
                heart_rate integer
            )
            """
        )
        yield connection
    finally:
        await connection.close()


def _test_table(sql: str) -> str:
    """Point production SQL at the connection-local temporary table."""
    return sql.replace("public.garmin_track_points", "pg_temp.garmin_track_points")


@pytest.mark.asyncio
async def test_effort_series_sql_gap_fills_empty_and_degenerate_efforts(postgres_connection):
    start = datetime(2026, 7, 5, 10, 30, tzinfo=UTC)
    end = start + timedelta(minutes=2)
    await postgres_connection.executemany(
        """
        INSERT INTO pg_temp.garmin_track_points
            (activity_id, timestamp, distance_from_start_km, speed_kmh, heart_rate)
        VALUES ($1, $2, $3, $4, $5)
        """,
        [
            ("sampled", start, 0.0, 10.0, 100),
            ("sampled", start + timedelta(minutes=1), 0.5, 20.0, 0),
            ("sampled", end, 1.0, 30.0, 140),
            ("degenerate", start, 5.0, 12.0, 120),
        ],
    )

    sampled = await postgres_connection.fetch(_test_table(SEGMENT_EFFORT_SERIES_SQL), "sampled", start, end, 10)
    assert len(sampled) == 10
    assert [row["index"] for row in sampled] == list(range(10))
    assert sampled[0]["speed_kmh"] == 10.0
    assert sampled[5]["speed_kmh"] == 20.0
    assert sampled[5]["heart_rate"] is None
    assert sampled[9]["speed_kmh"] == 30.0

    for activity_id in ("degenerate", "missing"):
        rows = await postgres_connection.fetch(
            _test_table(SEGMENT_EFFORT_SERIES_SQL),
            activity_id,
            start,
            end,
            10,
        )
        assert len(rows) == 10
        assert all(row["speed_kmh"] is None and row["heart_rate"] is None for row in rows)


@pytest.mark.asyncio
async def test_effort_series_batch_sql_uses_one_ordered_gap_filled_result(postgres_connection):
    start = datetime(2026, 7, 5, 10, 30, tzinfo=UTC)
    end = start + timedelta(minutes=2)
    await postgres_connection.executemany(
        """
        INSERT INTO pg_temp.garmin_track_points
            (activity_id, timestamp, distance_from_start_km, speed_kmh, heart_rate)
        VALUES ($1, $2, $3, $4, $5)
        """,
        [
            ("activity-b", start, 1.0, 15.0, 110),
            ("activity-b", end, 2.0, 25.0, 150),
        ],
    )

    rows = await postgres_connection.fetch(
        _test_table(SEGMENT_EFFORT_SERIES_BATCH_SQL),
        ["missing", "activity-b"],
        [start, start],
        [end, end],
        10,
    )

    assert len(rows) == 20
    assert [(row["request_index"], row["index"]) for row in rows] == [
        (request_index, index) for request_index in range(2) for index in range(10)
    ]
    assert all(row["speed_kmh"] is None for row in rows[:10])
    assert rows[10]["speed_kmh"] == 15.0
    assert rows[-1]["speed_kmh"] == 25.0
