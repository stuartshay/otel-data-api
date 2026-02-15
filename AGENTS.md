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
- **Production branch**: `master` (releases only, PR-only)
- **Lint before commit**: `pre-commit run -a`
- **Build**: `make docker-build`
- **Run dev**: `make dev`
- **Test**: `make test`
- **API Docs**: <http://localhost:8080/docs>

## Development Workflow

1. Switch to develop: `git checkout develop && git pull origin develop`
2. **Rebase from master**: `git fetch origin master && git rebase origin/master`
3. Make changes to API code in `app/`
4. Run `pre-commit run -a`
5. Run `make test`
6. Commit and push to `develop` or `feature/*` branch
7. Create PR to `master` when ready for production

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
