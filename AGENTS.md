# Agent Operating Guide

All automation, assistants, and developers must follow
`.github/copilot-instructions.md` for workflow, safety, and environment rules.

## How to Use

- Read `.github/copilot-instructions.md` before making changes
- Apply every rule in that file as-is; do not redefine or override them here
- If updates are needed, edit `.github/copilot-instructions.md` and keep this
  file pointing to it

## Quick Reference

- **Language**: Python 3.12+ / FastAPI
- **Database**: PostgreSQL via PgBouncer (192.168.1.175:6432)
- **Development branch**: `develop` (default working branch)
- **Production branch**: `main` (releases only, PR-only)
- **Lint before commit**: `pre-commit run -a`
- **Build**: `make docker-build`
- **Run dev**: `make dev`
- **Test**: `make test`
- **API Docs**: http://localhost:8080/docs

## Development Workflow

1. Switch to develop: `git checkout develop && git pull`
2. Make changes to API code in `app/`
3. Run `pre-commit run -a`
4. Run `make test`
5. Commit and push to `develop` or `feature/*` branch
6. Create PR to `main` when ready for production

## Project Structure

```text
otel-data-api/
├── app/
│   ├── __init__.py          # App factory (create_app)
│   ├── config.py            # Configuration
│   ├── database.py          # asyncpg DatabaseService
│   ├── auth.py              # Cognito JWT auth
│   ├── models/              # Pydantic response models
│   │   ├── locations.py
│   │   ├── garmin.py
│   │   ├── reference.py
│   │   └── spatial.py
│   └── routers/             # FastAPI route handlers
│       ├── health.py
│       ├── locations.py
│       ├── garmin.py
│       ├── unified.py
│       ├── reference.py
│       └── spatial.py
├── tests/                   # pytest test suite
├── run.py                   # Entrypoint
├── Dockerfile               # Container image
├── Makefile                 # Build automation
└── setup.sh                # Dev environment setup
```
