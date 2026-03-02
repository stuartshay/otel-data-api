"""Tests for request logging middleware."""

from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_trace_headers_from_otel(client: AsyncClient):
    """Response includes trace headers when OTel span context is active."""
    mock_ctx = MagicMock()
    mock_ctx.trace_id = 0x0AF7651916CD43DD8448EB211C80319C
    mock_ctx.span_id = 0xB7AD6B7169203331

    mock_span = MagicMock()
    mock_span.get_span_context.return_value = mock_ctx

    with patch("app.middleware.otel_trace.get_current_span", return_value=mock_span):
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.headers.get("X-Trace-Id") == "0af7651916cd43dd8448eb211c80319c"  # pragma: allowlist secret
    assert response.headers.get("X-Span-Id") == "b7ad6b7169203331"  # pragma: allowlist secret


@pytest.mark.asyncio
async def test_trace_headers_fallback_to_nr(client: AsyncClient):
    """Response falls back to NR trace IDs when OTel has no active span."""
    mock_ctx = MagicMock()
    mock_ctx.trace_id = 0  # OTel returns 0 when no span is active

    mock_span = MagicMock()
    mock_span.get_span_context.return_value = mock_ctx

    mock_nr = MagicMock()
    mock_nr.current_trace_id.return_value = "nr-trace-001"
    mock_nr.current_span_id.return_value = "nr-span-002"

    mock_parent = MagicMock()
    mock_parent.agent = mock_nr

    with (
        patch("app.middleware.otel_trace.get_current_span", return_value=mock_span),
        patch.dict("sys.modules", {"newrelic": mock_parent, "newrelic.agent": mock_nr}),
    ):
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.headers.get("X-Trace-Id") == "nr-trace-001"
    assert response.headers.get("X-Span-Id") == "nr-span-002"


@pytest.mark.asyncio
async def test_trace_headers_absent_without_tracing(client: AsyncClient):
    """Response does NOT include trace headers when neither OTel nor NR is active."""
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


@pytest.mark.asyncio
async def test_health_endpoint_excluded_from_logging(client: AsyncClient):
    """Health endpoints should not produce request log entries."""
    with patch("app.middleware.logger") as mock_logger:
        await client.get("/health")
        all_calls = (
            mock_logger.info.call_args_list + mock_logger.warning.call_args_list + mock_logger.error.call_args_list
        )
        assert not any(c.args and c.args[0] == "HTTP request" for c in all_calls)


@pytest.mark.asyncio
async def test_non_health_endpoint_produces_log(client: AsyncClient):
    """Non-excluded endpoints should produce an 'HTTP request' log entry."""
    with patch("app.middleware.logger") as mock_logger:
        await client.get("/api/v1/locations/status")
        all_calls = (
            mock_logger.info.call_args_list + mock_logger.warning.call_args_list + mock_logger.error.call_args_list
        )
        assert any(c.args[0] == "HTTP request" for c in all_calls if c.args)
