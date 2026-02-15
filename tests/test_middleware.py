"""Tests for trace correlation middleware."""

from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_trace_headers_present_when_nr_active(client: AsyncClient):
    """Response includes X-Trace-Id and X-Span-Id when New Relic is active."""
    mock_nr = MagicMock()
    mock_nr.current_trace_id.return_value = "trace-001"
    mock_nr.current_span_id.return_value = "span-002"

    mock_parent = MagicMock()
    mock_parent.agent = mock_nr

    with patch.dict("sys.modules", {"newrelic": mock_parent, "newrelic.agent": mock_nr}):
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.headers.get("X-Trace-Id") == "trace-001"
    assert response.headers.get("X-Span-Id") == "span-002"


@pytest.mark.asyncio
async def test_trace_headers_absent_without_nr(client: AsyncClient):
    """Response does NOT include trace headers when New Relic is not active."""
    response = await client.get("/health")
    assert response.status_code == 200
    assert "X-Trace-Id" not in response.headers
    assert "X-Span-Id" not in response.headers


@pytest.mark.asyncio
async def test_middleware_does_not_break_responses(client: AsyncClient):
    """Middleware gracefully handles missing New Relic — requests still work."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
