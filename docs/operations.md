# Operations Guide

## Local Development

### Prerequisites

- Python 3.12+
- Access to PostgreSQL/PgBouncer at 192.168.1.175:6432
- Docker (optional)

### Setup

```bash
./setup.sh
source venv/bin/activate
cp .env.example .env   # Edit with your credentials
make dev
```

### Common Commands

```bash
make dev           # Start dev server with auto-reload
make test          # Run unit tests
make lint          # Run ruff linter
make format        # Auto-format code
make type-check    # Run mypy type checker
make check         # Run all checks (lint + type-check + test)
make db-test       # Test database connectivity
make docker-build  # Build Docker image
make docker-run    # Run Docker container
```

### API Documentation

With the dev server running, visit:

- Swagger UI: <http://localhost:8080/docs>
- ReDoc: <http://localhost:8080/redoc>
- OpenAPI JSON: <http://localhost:8080/openapi.json>

## Testing

### Run Tests

```bash
# All tests
make test

# With coverage
pytest --cov=app --cov-report=term-missing tests/

# Single file
pytest tests/test_health.py -v

# Single test
pytest tests/test_health.py::test_health_endpoint -v
```

### Validate Before Commit

```bash
pre-commit run --all-files
```

## Docker

### Build

```bash
docker build -t stuartshay/otel-data-api .
```

### Run

```bash
docker run -p 8080:8080 \
  -e PGBOUNCER_HOST=192.168.1.175 \
  -e PGBOUNCER_PORT=6432 \
  -e POSTGRES_DB=owntracks \
  -e POSTGRES_USER=development \
  -e POSTGRES_PASSWORD=development \
  stuartshay/otel-data-api
```

## Health Checks

```bash
# Liveness (no DB dependency)
curl -s http://localhost:8080/health | jq

# Readiness (checks DB connection)
curl -s http://localhost:8080/ready | jq
```

## Database Connectivity

The API connects to PostgreSQL via PgBouncer:

| Property | Dev Value |
|----------|-----------|
| Host | 192.168.1.175 |
| Port | 6432 (PgBouncer) |
| Database | owntracks |
| User | development |
| Pool Min | 2 |
| Pool Max | 10 |

### Test Connection

```bash
make db-test
# Or manually:
psql -h 192.168.1.175 -p 6432 -U development -d owntracks -c "SELECT 1"
```

## Troubleshooting

### Import Errors

If `make dev` fails with import errors:

```bash
source venv/bin/activate
pip install -r requirements.txt
```

### Database Connection Refused

1. Verify PgBouncer is running: `nc -zv 192.168.1.175 6432`
2. Check `.env` credentials match the database
3. Verify `owntracks` database exists

### Pre-commit Failures

```bash
# Clear pre-commit cache and retry
pre-commit clean
pre-commit install
pre-commit run --all-files
```

### Pyright Missing Imports

Pyright requires the venv to resolve imports. Ensure:

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```
