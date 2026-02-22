# Copilot Rules for otel-data-api Repo

These rules ensure Copilot/assistants follow best practices for FastAPI
microservice development.

## Always Read First

- **README**: Read `README.md` for project overview and endpoints
- **env**: Load `.env` for database and auth configuration (gitignored)
- **pre-commit**: ALWAYS run `pre-commit run -a` before commit/PR

## Project Overview

Python FastAPI microservice providing REST API access to the OwnTracks + Garmin
location database. Features async PostgreSQL via asyncpg/PgBouncer, PostGIS
spatial queries, and optional AWS Cognito JWT authentication.

## Target Infrastructure

| Property      | Value                                         |
| ------------- | --------------------------------------------- |
| Language      | Python 3.14+ / FastAPI                        |
| Database      | PostgreSQL via PgBouncer (192.168.1.175:6432) |
| Database Name | owntracks                                     |
| K8s Cluster   | k8s-pi5-cluster                               |
| Namespace     | otel-data-api                                 |
| Docker Image  | stuartshay/otel-data-api                      |
| Auth Provider | AWS Cognito (optional)                        |

## Development Workflow

### Branch Strategy

⚠️ **CRITICAL RULE**: NEVER commit directly to `master` branch. All changes
MUST go through `develop` or `feature/*` branches.

- **master**: Protected branch, production-only (PR required, direct commits
  FORBIDDEN)
- **develop**: Primary development branch (work here by default)
- **feature/\***: Feature branches (use for isolated features, PR to `master`)

### Before Starting Any Work

**ALWAYS sync your working branch with the remote before making changes:**

```bash
# If working on develop:
git checkout develop && git fetch origin && git pull origin develop

# If creating a new feature branch:
git checkout master && git fetch origin && git pull origin master
git checkout -b feature/my-feature
```

**ALWAYS rebase onto the latest protected branch before creating a PR:**

```bash
git fetch origin master && git rebase origin/master
```

### Before Creating a PR

⚠️ **ALWAYS check for and resolve conflicts before creating a PR:**

1. Rebase onto the latest protected branch:
   `git fetch origin master && git rebase origin/master`
2. Resolve any conflicts during rebase
3. Force-push the rebased branch: `git push origin <branch> --force-with-lease`
4. Verify the PR shows no conflicts on GitHub before requesting review

This is especially important after squash merges, which cause develop to
diverge from master.

### Daily Workflow

1. **ALWAYS** start from `develop` or create a feature branch
2. **Sync with remote** before making any changes (see above)
3. Run `./setup.sh` to initialize environment
4. Activate venv: `source venv/bin/activate`
5. Run locally: `make dev`
6. Test endpoints: `curl http://localhost:8080/health`
7. Run `pre-commit run -a` before commit
8. Commit and push to `develop` or `feature/*` branch
9. **For feature branches**: rebase onto latest `master` before PR:
   `git fetch origin master && git rebase origin/master`
10. Create PR to `master` when ready for deployment
11. **NEVER**: `git push origin master` or commit directly to master

## Writing Code

### FastAPI Endpoints

- All routers in `app/routers/` with versioned prefix `/api/v1/`
- Use Pydantic models from `app/models/` for responses
- Paginated endpoints return `PaginatedResponse[T]`
- Use parameterized queries (never string interpolation for SQL)
- Access database via `request.app.state.db`

### Database

- Always use PgBouncer (port 6432) for connections
- Use `DatabaseService` methods: `fetch`, `fetchrow`, `fetchval`, `execute`
- Use parameterized queries with `$1, $2` placeholders
- Filter by indexed columns: `device_id`, `timestamp`, `created_at`

### Authentication

- Auth is optional (controlled by `OAUTH2_ENABLED` env var)
- Read operations are public
- Write operations (POST/PUT/DELETE on reference-locations) require auth
- Use `require_auth` dependency for protected endpoints
- Use `get_current_user` for optional user context

### Spell Checking (cspell)

- The `cspell.json` `words` list **MUST always be sorted in strict alphabetical
  order** (case-insensitive)
- When adding a new word, insert it in its correct alphabetical position — do
  not append it to the end of the list

## Local Development Services

⚠️ **ALWAYS start local services in hot-reload mode.** Never use `make start`
or production mode for local development.

- **Start command**: `make dev` (runs `uvicorn --reload` with file watching)
- **Port**: 8080
- **Health check**: `curl http://localhost:8080/health`
- **Hot reload**: Automatically restarts on Python file changes
- Do NOT use `make start` for development — it runs without `--reload`

When starting the full local stack, start services in this order:

1. `otel-data-api` — `make dev` (port 8080)
2. `otel-data-gateway` — `make dev` (port 4000)
3. `otel-data-ui` — `make dev` (port 5173)

## Project Structure

```text
otel-data-api/
├── app/
│   ├── __init__.py          # App factory (create_app)
│   ├── auth.py              # Cognito JWT auth
│   ├── config.py            # Pydantic settings (Config)
│   ├── database.py          # asyncpg DatabaseService
│   ├── middleware.py        # Request logging middleware
│   ├── models/              # Pydantic response models
│   │   ├── __init__.py      # Shared models (PaginatedResponse, StatusResponse)
│   │   ├── garmin.py
│   │   ├── locations.py
│   │   ├── reference.py
│   │   └── spatial.py
│   └── routers/             # FastAPI route handlers
│       ├── garmin.py        # /api/v1/garmin/*
│       ├── health.py        # /health, /ready
│       ├── locations.py     # /api/v1/locations/*
│       ├── reference.py     # /api/v1/reference-locations/*
│       ├── spatial.py       # /api/v1/spatial/*
│       └── unified.py       # /api/v1/gps/*
├── tests/                   # pytest test suite (async, uses mock_db)
├── packages/otel-data-types/ # TypeScript type definitions (npm)
├── scripts/                 # Utility scripts
├── pyproject.toml           # Python project config, ruff/mypy/pytest settings
├── requirements.txt         # Python dependencies
├── Dockerfile               # Container image (Python 3.14 slim)
├── Makefile                 # Build automation
└── setup.sh                 # Dev environment bootstrap
```

## CI/CD Pipelines

Four workflows run on push/PR to `master` and `develop`:

| Workflow | File | Checks |
|----------|------|--------|
| Lint and Validate | `lint.yml` | pre-commit (ruff, mypy, cspell, markdownlint), pytest, Dockerfile lint (hadolint), pip-audit |
| Docker | `docker.yml` | Build Docker image, push to Docker Hub on master |
| Publish Types | `publish-types.yml` | Build and publish TypeScript types to npm |
| Auto Approve | `auto-approve.yml` | Auto-approves PRs from stuartshay, renovate[bot], dependabot[bot] |

**Replicate CI locally before pushing:**

```bash
pre-commit run --all-files   # Runs all lint/format/type checks
make test                    # Runs pytest with coverage
```

## Testing Conventions

- Tests live in `tests/` using `pytest` with `pytest-asyncio`
- All tests are `async` and decorated with `@pytest.mark.asyncio`
- Use `mock_db` fixture (AsyncMock of DatabaseService) to avoid real DB
- Use `client` fixture (AsyncClient wrapping the test app) for HTTP requests
- Use `app` fixture to get a FastAPI app with mocked DB injected
- Coverage must be ≥ 85% for `app/` (enforced in `pyproject.toml`)

```bash
make test          # Run tests with coverage
make test-cov      # Run tests with HTML coverage report
pytest tests/test_health.py -v   # Run a specific test file
```

## Safety Rules (Do Not)

- ⛔ **NEVER commit directly to master branch** - ALWAYS use develop or feature
  branches
- Do not commit secrets or `.env` files
- Do not use `latest` Docker tags in deployments
- Do not skip `pre-commit run -a` before commits
- Do not use string interpolation in SQL queries (SQL injection risk)
- Do not hardcode database credentials

## Quick Commands

```bash
make help          # Show all commands
make dev           # Start dev server (auto-reload)
make test          # Run tests
make lint          # Run ruff linter
make format        # Format code
make check         # Run all checks
make db-test       # Test database connection
make docker-build  # Build Docker image
pre-commit run -a  # Pre-commit checks
```

## Related Repositories

- [otel-ui](https://github.com/stuartshay/otel-ui) — React frontend (primary
  consumer)
- [otel-demo](https://github.com/stuartshay/otel-demo) — Flask API (legacy)
- [otel-worker](https://github.com/stuartshay/otel-worker) — Go gRPC distance
  calculator
- [k8s-gitops](https://github.com/stuartshay/k8s-gitops) — Kubernetes deployment
- [homelab-database-migrations](https://github.com/stuartshay/homelab-database-migrations) — Database schema

## When Unsure

- Check existing code for patterns
- Reference FastAPI documentation
- Validate with `pre-commit run -a` before asking
- Test locally with `make dev` before pushing
