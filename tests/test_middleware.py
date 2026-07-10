"""Tests for request logging middleware."""

from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient

from app.middleware import _log_request, _request_log_kwargs


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


def test_log_request_uses_status_code_severity():
    """Request log helper maps response status codes to expected levels."""
    log_kwargs = {"http.method": "GET"}

    with patch("app.middleware.logger") as mock_logger:
        _log_request(200, log_kwargs)
        _log_request(404, log_kwargs)
        _log_request(500, log_kwargs)

    mock_logger.info.assert_called_once_with("HTTP request", **log_kwargs)
    mock_logger.warning.assert_called_once_with("HTTP request", **log_kwargs)
    mock_logger.error.assert_called_once_with("HTTP request", **log_kwargs)


def test_request_log_kwargs_includes_trace_and_query_params():
    """Request log field helper includes trace context and query params."""
    request = MagicMock()
    request.method = "GET"
    request.url.path = "/api/v1/locations/status"
    request.url.__str__.return_value = "https://api.example.test/api/v1/locations/status?device_id=phone"
    request.query_params = {"device_id": "phone"}
    request.client.host = "127.0.0.1"

    response = MagicMock()
    response.status_code = 200

    log_kwargs = _request_log_kwargs(request, response, 12.345, "trace-1", "span-1", True)

    assert log_kwargs["http.url"] == "https://api.example.test/api/v1/locations/status?device_id=phone"
    assert log_kwargs["http.query_params"] == {"device_id": "phone"}
    assert log_kwargs["trace.id"] == "trace-1"
    assert log_kwargs["span.id"] == "span-1"
    assert log_kwargs["duration_ms"] == 12.35


def test_request_log_kwargs_omits_query_params_when_disabled():
    """Request log field helper omits query params when configured off."""
    request = MagicMock()
    request.method = "GET"
    request.url.scheme = "https"
    request.url.netloc = "api.example.test"
    request.url.path = "/api/v1/locations/status"
    request.query_params = {"device_id": "phone"}
    request.client.host = "127.0.0.1"

    response = MagicMock()
    response.status_code = 200

    log_kwargs = _request_log_kwargs(request, response, 1.0, None, None, False)

    assert log_kwargs["http.url"] == "https://api.example.test/api/v1/locations/status"
    assert "http.query_params" not in log_kwargs
