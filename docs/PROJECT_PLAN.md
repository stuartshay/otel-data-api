# OTel Data API — Project Plan

## Overview

The `otel-data-api` is a FastAPI microservice that provides REST API access to
the OwnTracks + Garmin location database. It replaces the legacy `otel-demo`
Flask API with a modern async architecture using asyncpg, PostGIS spatial
queries, and optional AWS Cognito JWT authentication.

## Architecture

```text
┌──────────┐     ┌──────────────┐     ┌───────────┐     ┌────────────┐
│  otel-ui │────▶│ otel-data-api│────▶│ PgBouncer │────▶│ PostgreSQL │
│ (React)  │     │  (FastAPI)   │     │  :6432    │     │   :5432    │
└──────────┘     └──────────────┘     └───────────┘     └────────────┘
                        │
                        ▼
                 ┌──────────────┐
                 │  Cognito JWT │
                 │    (Auth)    │
                 └──────────────┘
```

### Tech Stack

| Component | Technology | Version |
|-----------|-----------|---------|
| Framework | FastAPI | 0.115.8 |
| ASGI Server | Uvicorn | 0.34.0 |
| Database Driver | asyncpg | 0.30.0 |
| Connection Pooling | PgBouncer | 6432 |
| Spatial Queries | PostGIS | ST_DWithin, ST_Distance |
| Validation | Pydantic | 2.10.6 |
| Auth | python-jose + Cognito | PKCE/JWT |
| Observability | OpenTelemetry | 1.30.0 |
| Container | Docker (python:3.12-slim) | — |

## Phase 1 — Initial Scaffolding (Completed)

### Deliverables

- [x] Project structure with `app/` package (routers, models, config, database, auth)
- [x] 6 API routers: health, locations, garmin, unified, reference, spatial
- [x] 5 Pydantic model groups: locations, garmin, reference, spatial, shared
- [x] Async database service with asyncpg connection pooling
- [x] Cognito JWT authentication (optional, controlled by `OAUTH2_ENABLED`)
- [x] PostGIS spatial queries (nearby, distance, geofencing)
- [x] 10 unit tests covering all routers
- [x] Docker image (python:3.12-slim, non-root user)
- [x] CI pipeline (GitHub Actions: pre-commit, pytest, hadolint, pip-audit)
- [x] Pre-commit hooks (ruff, mypy, pyright, markdownlint, shellcheck, detect-secrets)
- [x] Makefile with dev, test, lint, docker, and db-test targets
- [x] AGENTS.md and copilot-instructions.md

### API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/health` | No | Liveness probe |
| GET | `/ready` | No | Readiness probe (DB check) |
| GET | `/api/v1/locations` | No | Paginated location list |
| GET | `/api/v1/locations/devices` | No | Device ID list |
| GET | `/api/v1/locations/count` | No | Per-device counts |
| GET | `/api/v1/locations/{id}` | No | Location by ID |
| GET | `/api/v1/garmin/activities` | No | Paginated activities |
| GET | `/api/v1/garmin/sports` | No | Sport type summary |
| GET | `/api/v1/garmin/activities/{id}` | No | Activity detail |
| GET | `/api/v1/garmin/activities/{id}/tracks` | No | Track points |
| GET | `/api/v1/gps/unified` | No | Unified GPS (view) |
| GET | `/api/v1/gps/daily-summary` | No | Daily stats (view) |
| GET | `/api/v1/reference-locations` | No | List named locations |
| GET | `/api/v1/reference-locations/{id}` | No | Reference detail |
| POST | `/api/v1/reference-locations` | Yes | Create reference |
| PUT | `/api/v1/reference-locations/{id}` | Yes | Update reference |
| DELETE | `/api/v1/reference-locations/{id}` | Yes | Delete reference |
| GET | `/api/v1/spatial/nearby` | No | Nearby GPS points |
| GET | `/api/v1/spatial/distance` | No | Point-to-point distance |
| GET | `/api/v1/spatial/within-reference/{name}` | No | Points in geofence |

### Database Tables

| Table/View | Type | Purpose |
|-----------|------|---------|
| `public.locations` | Table | OwnTracks GPS data |
| `public.garmin_activities` | Table | Garmin Connect activities |
| `public.garmin_track_points` | Table | Garmin GPS track points |
| `public.reference_locations` | Table | Named reference locations |
| `unified_gps_points` | View | Combined OwnTracks + Garmin |
| `daily_activity_summary` | View | Aggregated daily statistics |

## Phase 2 — Kubernetes Deployment (Completed)

### Tasks

- [x] Create Kubernetes manifests in `k8s-gitops/apps/base/otel-data-api/`
  - Deployment with resource limits, health probes, env vars
  - Service (ClusterIP, port 8080)
  - Ingress with TLS (cert-manager, Let's Encrypt)
  - Namespace: `otel-data-api`
- [x] Add Argo CD Application resource in `bootstrap/`
- [x] Configure Kustomize overlays in `clusters/k8s-pi5-cluster/`
- [x] Create Cloudflare DNS record: `api.lab.informationcart.com`
- [x] Add Docker build workflow (`docker.yml`) for multi-arch images
- [x] Fix version reporting — health endpoint reads `APP_VERSION` env var set
  by Docker build (format: `{major}.{minor}.{build_number}`)
- [x] Verify end-to-end: otel-ui → otel-data-api → PgBouncer → PostgreSQL

### Target Configuration

| Property | Value |
|----------|-------|
| Namespace | `otel-data-api` |
| Replicas | 1 |
| Port | 8080 |
| Image | `stuartshay/otel-data-api` |
| DNS | `api.lab.informationcart.com` |
| Ingress IP | 192.168.1.100 (MetalLB) |

## Phase 3 — otel-ui Integration (Next)

### Tasks

- [ ] Update otel-ui to use `otel-data-api` as backend
- [ ] Replace `VITE_API_BASE_URL` with new API endpoint
- [ ] Test all frontend features against new API
- [ ] Migrate away from legacy `otel-demo` endpoints
- [ ] Update otel-ui documentation

## Phase 4 — Enhancements

### Tasks

- [ ] Add OpenTelemetry trace correlation (response headers, log injection)
- [ ] Add `/api/v1/locations` write endpoints (POST for ingesting data)
- [ ] Add rate limiting middleware
- [ ] Add response caching for expensive spatial queries
- [ ] Add API versioning strategy (v2 prefix)
- [ ] Integration tests with live database
- [ ] Load testing and performance benchmarks

## Related Repositories

| Repository | Purpose |
|-----------|---------|
| [otel-ui](https://github.com/stuartshay/otel-ui) | React frontend (primary consumer) |
| [otel-demo](https://github.com/stuartshay/otel-demo) | Flask API (legacy, to be replaced) |
| [otel-worker](https://github.com/stuartshay/otel-worker) | Go gRPC distance calculator |
| [k8s-gitops](https://github.com/stuartshay/k8s-gitops) | Kubernetes deployment manifests |
| [homelab-database-migrations](https://github.com/stuartshay/homelab-database-migrations) | Database schema migrations |
| [homelab-infrastructure](https://github.com/stuartshay/homelab-infrastructure) | Terraform (Cognito, S3) |
