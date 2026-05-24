#!/usr/bin/env python3
"""Drain the Garmin reverse-geocoding retry backlog.

Repeatedly POSTs to ``/internal/geocoding/trigger/garmin`` with
``retry_failed=true`` until the ``remaining`` count reaches zero (or the
optional ``--max-batches`` cap is hit).

Intended for ad-hoc backfills run via ``kubectl exec`` against the
``otel-data-api`` pod, or against a local ``make dev`` instance.

Examples
--------
Drain against the in-cluster API (kubectl exec)::

    kubectl -n otel-data-api exec deploy/otel-data-api -- \\
        python /app/scripts/drain_garmin_geocoding.py \\
        --base-url http://localhost:8080 --batch-size 100

Drain against a local dev server::

    python scripts/drain_garmin_geocoding.py \\
        --base-url http://localhost:8080 --batch-size 50

Environment variables (read when corresponding flag not supplied):

* ``OTEL_DATA_API_BASE_URL`` -- defaults to ``http://localhost:8080``
* ``DRAIN_BATCH_SIZE`` -- defaults to 100
* ``DRAIN_MAX_BATCHES`` -- 0 means unlimited (default)
* ``DRAIN_SLEEP_SECONDS`` -- pause between batches (default 1.0)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

try:
    import httpx
except ImportError:  # pragma: no cover - script-time dependency check
    sys.stderr.write("ERROR: httpx is required (pip install httpx)\n")
    sys.exit(2)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--base-url",
        default=os.environ.get("OTEL_DATA_API_BASE_URL", "http://localhost:8080"),
        help="Base URL of otel-data-api (default: env OTEL_DATA_API_BASE_URL or http://localhost:8080)",
    )
    p.add_argument(
        "--batch-size",
        type=int,
        default=int(os.environ.get("DRAIN_BATCH_SIZE", "100")),
        help="Activities per trigger request (default: 100, env DRAIN_BATCH_SIZE)",
    )
    p.add_argument(
        "--max-batches",
        type=int,
        default=int(os.environ.get("DRAIN_MAX_BATCHES", "0")),
        help="Stop after this many batches (0 = unlimited, default 0)",
    )
    p.add_argument(
        "--sleep",
        type=float,
        default=float(os.environ.get("DRAIN_SLEEP_SECONDS", "1.0")),
        help="Seconds to sleep between batches (default 1.0)",
    )
    p.add_argument(
        "--request-timeout",
        type=float,
        default=float(os.environ.get("DRAIN_REQUEST_TIMEOUT", "600")),
        help="HTTP timeout per trigger request, in seconds (default 600)",
    )
    p.add_argument(
        "--no-health-gate",
        action="store_true",
        help="Skip the /pelias-health pre-flight check",
    )
    return p.parse_args()


def _pelias_health(client: httpx.Client, base_url: str) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/api/v1/geocoding/pelias-health"
    resp = client.get(url, timeout=15.0)
    resp.raise_for_status()
    data: dict[str, Any] = resp.json()
    return data


def _trigger(client: httpx.Client, base_url: str, batch_size: int, timeout: float) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/internal/geocoding/trigger/garmin"
    resp = client.post(
        url,
        params={"retry_failed": "true", "batch_size": str(batch_size)},
        timeout=timeout,
    )
    resp.raise_for_status()
    data: dict[str, Any] = resp.json()
    return data


def main() -> int:
    args = _parse_args()
    print(
        f"[drain] base_url={args.base_url} batch_size={args.batch_size} "
        f"max_batches={args.max_batches or 'unlimited'} sleep={args.sleep}s",
        flush=True,
    )

    with httpx.Client() as client:
        if not args.no_health_gate:
            try:
                health = _pelias_health(client, args.base_url)
            except httpx.HTTPError as e:
                print(f"[drain] ERROR: pelias-health probe failed: {e}", file=sys.stderr, flush=True)
                return 3
            if not health.get("healthy"):
                print(
                    f"[drain] ABORT: Pelias is unhealthy: {json.dumps(health)}",
                    file=sys.stderr,
                    flush=True,
                )
                return 4
            print(f"[drain] pelias-health OK ({health.get('latency_ms')}ms)", flush=True)

        batch_idx = 0
        total_processed = 0
        total_dedup = 0
        consecutive_zero = 0

        while True:
            batch_idx += 1
            if args.max_batches and batch_idx > args.max_batches:
                print(f"[drain] max-batches limit hit ({args.max_batches}); stopping", flush=True)
                break

            try:
                body = _trigger(client, args.base_url, args.batch_size, args.request_timeout)
            except httpx.HTTPError as e:
                print(f"[drain] batch {batch_idx} ERROR: {e}", file=sys.stderr, flush=True)
                return 5

            processed = int(body.get("processed", 0))
            remaining = int(body.get("remaining", 0))
            skipped_dedup = int(body.get("skipped_dedup", 0))
            total_processed += processed
            total_dedup += skipped_dedup

            print(
                f"[drain] batch={batch_idx} processed={processed} skipped_dedup={skipped_dedup} "
                f"remaining={remaining} total_processed={total_processed}",
                flush=True,
            )

            if processed == 0:
                consecutive_zero += 1
            else:
                consecutive_zero = 0

            if remaining == 0 and processed == 0:
                print("[drain] queue drained (remaining=0, processed=0)", flush=True)
                break
            if consecutive_zero >= 3:
                print(
                    "[drain] STALL: three consecutive zero-processed batches; stopping",
                    file=sys.stderr,
                    flush=True,
                )
                return 6

            time.sleep(args.sleep)

    print(f"[drain] done: total_processed={total_processed} total_dedup={total_dedup}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
