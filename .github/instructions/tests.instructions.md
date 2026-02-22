---
applyTo: "tests/**/*.py"
---

## Test Structure

- All tests are `async def` and decorated with `@pytest.mark.asyncio`.
- Use `client` (AsyncClient), `mock_db` (AsyncMock), and `app` (FastAPI)
  fixtures from `conftest.py`.
- Do not open real database connections in tests — use `mock_db` exclusively.

## Writing Tests

```python
@pytest.mark.asyncio
async def test_my_endpoint(client: AsyncClient, mock_db):
    mock_db.fetchrow.return_value = {"id": 1, "name": "test"}

    response = await client.get("/api/v1/my-endpoint/1")

    assert response.status_code == 200
    assert response.json()["id"] == 1
```

## Coverage

- Minimum 85% line coverage for `app/` is enforced.
- Run `make test` to verify coverage before pushing.
- New router modules must have corresponding test files in `tests/`.
