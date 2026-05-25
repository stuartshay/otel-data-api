#!/usr/bin/env python3
"""Per-phase timing benchmark for the Garmin geocoding retry path.

Exercises the **read path** of the retry pipeline against a real database +
Pelias instance and reports p50/p95/p99 wall time for each phase so we can
identify the actual bottleneck:

1. ``selector_sql``  - one row per activity from the INNER JOIN retry selector
2. ``waypoints_sql`` - per-activity ``_select_garmin_retry_waypoints`` query
3. ``find_nearby``   - per-waypoint PostGIS 50 m proximity dedup
4. ``pelias_call``   - per-waypoint Pelias reverse-geocode HTTP call
                       (only when ``find_nearby`` returns no neighbour)

The bench **does not write** to the database; persistence helpers are
deliberately bypassed so phase timings are not contaminated by upsert work
and side-effects do not change the retry pool during measurement.

Examples
--------
Bench 5 activities against the env-configured DB::

    python scripts/bench_garmin_geocoding.py --activities 5

Bench against a specific DB / Pelias::

    PGBOUNCER_HOST=... POSTGRES_USER=... POSTGRES_PASSWORD=... \
        PELIAS_BASE_URL=http://geocoder.lab.informationcart.com \
        python scripts/bench_garmin_geocoding.py --activities 10 --json out.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass, field

# Allow running from the repo root without installing the package.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    import asyncpg
    import httpx
except ImportError as e:
    sys.stderr.write(f"ERROR: missing dependency ({e}); run inside the otel-data-api venv\n")
    sys.exit(2)

from app.routers.geocoding import (  # noqa: E402
    PELIAS_REVERSE_PATH,
    RETRY_STATUSES,
    _find_nearby_address,
    _select_garmin_retry_waypoints,
)


@dataclass
class PhaseTimings:
    selector_sql: float = 0.0
    waypoints_sql: list[float] = field(default_factory=list)
    find_nearby: list[float] = field(default_factory=list)
    pelias_call: list[float] = field(default_factory=list)
    find_nearby_hits: int = 0
    pelias_attempts: int = 0
    activity_total: list[float] = field(default_factory=list)
    waypoints_per_activity: list[int] = field(default_factory=list)


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = max(0, min(len(s) - 1, int(round(q * (len(s) - 1)))))
    return s[idx]


async def _run(args: argparse.Namespace) -> PhaseTimings:
    db_host = os.getenv("PGBOUNCER_HOST", "192.168.1.175")
    db_port = int(os.getenv("PGBOUNCER_PORT", "6432"))
    db_name = os.getenv("POSTGRES_DB", "owntracks")
    db_user = os.getenv("POSTGRES_USER")
    db_password = os.getenv("POSTGRES_PASSWORD")
    pelias_base_url = os.getenv("PELIAS_BASE_URL", "http://geocoder.lab.informationcart.com")
    pelias_timeout = float(os.getenv("PELIAS_TIMEOUT_SECONDS", "10"))

    if not db_user or not db_password:
        sys.stderr.write("ERROR: POSTGRES_USER and POSTGRES_PASSWORD must be set\n")
        sys.exit(2)

    print(
        f"# bench: db={db_user}@{db_host}:{db_port}/{db_name} pelias={pelias_base_url} "
        f"activities={args.activities} max_waypoints_per_activity={args.max_waypoints}",
        flush=True,
    )

    pool = await asyncpg.create_pool(
        host=db_host,
        port=db_port,
        database=db_name,
        user=db_user,
        password=db_password,
        min_size=2,
        max_size=8,
        command_timeout=30.0,
    )
    assert pool is not None  # noqa: S101
    timings = PhaseTimings()
    try:
        async with pool.acquire() as conn:
            t0 = time.monotonic()
            activity_rows = await conn.fetch(
                "SELECT a.activity_id "
                "FROM public.garmin_activities a "
                "INNER JOIN public.geocoded_addresses ga "
                "  ON ga.garmin_activity_id = a.activity_id AND ga.source = 'garmin' "
                "WHERE ga.status = ANY($2::text[]) "
                "GROUP BY a.activity_id "
                "ORDER BY MIN(ga.geocoded_at) ASC NULLS FIRST "
                "LIMIT $1",
                args.activities,
                list(RETRY_STATUSES),
            )
            timings.selector_sql = time.monotonic() - t0
            print(f"# selector_sql returned {len(activity_rows)} activities in {timings.selector_sql:.3f}s")

        async with httpx.AsyncClient(timeout=pelias_timeout) as client:
            for i, row in enumerate(activity_rows, start=1):
                activity_id = row["activity_id"]
                async with pool.acquire() as conn:
                    a_start = time.monotonic()
                    t0 = time.monotonic()
                    waypoints = await _select_garmin_retry_waypoints(conn, activity_id)
                    timings.waypoints_sql.append(time.monotonic() - t0)

                    capped = waypoints[: args.max_waypoints] if args.max_waypoints > 0 else waypoints
                    timings.waypoints_per_activity.append(len(capped))

                    for wp in capped:
                        lat = float(wp["latitude"])
                        lon = float(wp["longitude"])

                        t0 = time.monotonic()
                        neighbour = await _find_nearby_address(conn, lat, lon)
                        timings.find_nearby.append(time.monotonic() - t0)
                        if neighbour:
                            timings.find_nearby_hits += 1
                            continue

                        timings.pelias_attempts += 1
                        t0 = time.monotonic()
                        try:
                            resp = await client.get(
                                f"{pelias_base_url}{PELIAS_REVERSE_PATH}",
                                params={"point.lat": lat, "point.lon": lon, "size": 1},
                            )
                            _ = resp.status_code  # force read
                        except Exception as exc:
                            print(f"  ! pelias error wp={wp['id']}: {exc!r}")
                        timings.pelias_call.append(time.monotonic() - t0)

                    timings.activity_total.append(time.monotonic() - a_start)
                    print(
                        f"  [{i:>3}/{len(activity_rows)}] activity={activity_id} "
                        f"waypoints={len(capped)} elapsed={timings.activity_total[-1]:.2f}s",
                        flush=True,
                    )
    finally:
        await pool.close()

    return timings


def _print_report(t: PhaseTimings) -> None:
    def line(label: str, values: list[float], total_calls: int | None = None) -> str:
        if not values:
            return f"  {label:<18} n=0"
        n = len(values)
        calls = total_calls if total_calls is not None else n
        return (
            f"  {label:<18} n={n:>5} "
            f"p50={_pct(values, 0.50) * 1000:>7.1f}ms "
            f"p95={_pct(values, 0.95) * 1000:>8.1f}ms "
            f"p99={_pct(values, 0.99) * 1000:>8.1f}ms "
            f"mean={statistics.mean(values) * 1000:>7.1f}ms "
            f"sum={sum(values):>6.1f}s "
            f"({calls} calls)"
        )

    print("\n=== Per-phase timing summary ===")
    print(f"  selector_sql       {t.selector_sql * 1000:>7.1f}ms (1 call)")
    print(line("waypoints_sql", t.waypoints_sql))
    print(line("find_nearby", t.find_nearby))
    print(line("pelias_call", t.pelias_call, t.pelias_attempts) + f"  [dedup_hits={t.find_nearby_hits}]")
    print(line("activity_total", t.activity_total))

    if t.activity_total:
        total_wall = sum(t.activity_total)
        n_act = len(t.activity_total)
        n_wp = sum(t.waypoints_per_activity)
        total_pelias_wall = sum(t.pelias_call)
        total_nearby_wall = sum(t.find_nearby)
        total_wp_sql = sum(t.waypoints_sql)
        print("\n=== Breakdown ===")
        print(f"  activities sampled        : {n_act}")
        print(f"  waypoints sampled         : {n_wp}")
        print(f"  total wall                : {total_wall:.2f}s")
        print(f"   - waypoints_sql          : {total_wp_sql:.2f}s ({total_wp_sql / total_wall * 100:.1f}%)")
        print(f"   - find_nearby            : {total_nearby_wall:.2f}s ({total_nearby_wall / total_wall * 100:.1f}%)")
        print(f"   - pelias_call            : {total_pelias_wall:.2f}s ({total_pelias_wall / total_wall * 100:.1f}%)")
        residual = total_wall - total_wp_sql - total_nearby_wall - total_pelias_wall
        print(f"   - residual (overhead)    : {residual:.2f}s ({residual / total_wall * 100:.1f}%)")
        print(f"  per-activity mean         : {total_wall / n_act:.2f}s")
        if n_wp:
            print(f"  per-waypoint mean         : {total_wall / n_wp * 1000:.1f}ms")
            print(f"  dedup hit rate            : {t.find_nearby_hits / n_wp * 100:.1f}%")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--activities", type=int, default=5, help="Activities to sample (default: 5)")
    p.add_argument(
        "--max-waypoints",
        type=int,
        default=0,
        help="Cap waypoints per activity (0 = no cap, default)",
    )
    p.add_argument("--json", help="Optional path to dump raw timings as JSON")
    args = p.parse_args()

    timings = asyncio.run(_run(args))
    _print_report(timings)

    if args.json:
        with open(args.json, "w") as f:
            json.dump(
                {
                    "selector_sql": timings.selector_sql,
                    "waypoints_sql": timings.waypoints_sql,
                    "find_nearby": timings.find_nearby,
                    "pelias_call": timings.pelias_call,
                    "activity_total": timings.activity_total,
                    "waypoints_per_activity": timings.waypoints_per_activity,
                    "find_nearby_hits": timings.find_nearby_hits,
                    "pelias_attempts": timings.pelias_attempts,
                },
                f,
                indent=2,
            )
        print(f"\n# wrote raw timings to {args.json}")


if __name__ == "__main__":
    main()
