---
applyTo: "app/**/*.py"
---

## FastAPI Router Pattern

New routers go in `app/routers/`. Register them in `app/__init__.py` with a
versioned prefix:

```python
from app.routers import my_router
app.include_router(my_router.router, prefix="/api/v1")
```

## Response Models

- Define Pydantic models in `app/models/` for all request and response bodies.
- Paginated responses must use `PaginatedResponse[T]` from `app/models/`.

## Database Access

- Always access the database through `request.app.state.db` (a `DatabaseService` instance).
- Use `$1, $2, ...` placeholders — never use f-strings or string concatenation for SQL.
- Available methods: `db.fetch(sql, *args)`, `db.fetchrow(sql, *args)`,
  `db.fetchval(sql, *args)`, `db.execute(sql, *args)`.

## Error Handling

- Raise `fastapi.HTTPException` with appropriate status codes for client errors.
- Let unhandled exceptions propagate — middleware handles logging.

## Code Style

- Line length: 120 characters (enforced by ruff).
- Use type annotations on all function signatures.
- Run `pre-commit run --all-files` before committing.
