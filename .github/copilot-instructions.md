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
| Language      | Python 3.12+ / FastAPI                        |
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
