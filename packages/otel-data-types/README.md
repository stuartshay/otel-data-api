# @stuartshay/otel-data-types

TypeScript types auto-generated from the
[otel-data-api](https://github.com/stuartshay/otel-data-api) OpenAPI 3.1
specification.

## Installation

```bash
npm install @stuartshay/otel-data-types
```

## Usage

```typescript
import type { paths, components } from '@stuartshay/otel-data-types';

// Typed API response
type LocationsResponse = paths['/api/v1/locations']['get']['responses']['200']['content']['application/json'];

// Typed schema
type Location = components['schemas']['Location'];
type GarminActivity = components['schemas']['GarminActivity'];
```

## Generation

Types are generated from the FastAPI source code using `openapi-typescript`:

```bash
./scripts/generate-types.sh
```

## API Coverage

- **Locations** — OwnTracks GPS data (CRUD, count, devices)
- **Garmin** — Activities and track points
- **Unified GPS** — Combined OwnTracks + Garmin view
- **Reference Locations** — Named locations with radius
- **Spatial** — PostGIS queries (nearby, distance, within-reference)
- **Health** — Liveness and readiness probes
