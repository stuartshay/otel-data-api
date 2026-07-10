"""Middleware for request logging, trace correlation headers, and request context."""

from __future__ import annotations

import time
from typing import Any

import structlog
from opentelemetry import trace as otel_trace
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.config import Config

logger = structlog.get_logger(__name__)

# Response header names for trace correlation
TRACE_ID_HEADER = "X-Trace-Id"
SPAN_ID_HEADER = "X-Span-Id"

# Paths excluded from request logging (health probes generate too much noise)
_EXCLUDED_PATHS: set[str] = {"/health", "/ready"}
_HTTP_REQUEST_LOG_MESSAGE = "HTTP request"


def _current_trace_ids() -> tuple[str | None, str | None]:
    trace_id, span_id = _otel_trace_ids()
    if trace_id:
        return trace_id, span_id
    return _new_relic_trace_ids()


def _otel_trace_ids() -> tuple[str | None, str | None]:
    try:
        span = otel_trace.get_current_span()
        ctx = span.get_span_context()
        if ctx and ctx.trace_id:
            return format(ctx.trace_id, "032x"), format(ctx.span_id, "016x")
    except Exception:  # noqa: BLE001
        pass
    return None, None


def _new_relic_trace_ids() -> tuple[str | None, str | None]:
    try:
        import newrelic.agent  # pyright: ignore[reportMissingImports]

        return newrelic.agent.current_trace_id(), newrelic.agent.current_span_id()
    except Exception:  # noqa: BLE001
        return None, None


def _set_trace_headers(response: Response, trace_id: str | None, span_id: str | None) -> None:
    if trace_id:
        response.headers[TRACE_ID_HEADER] = trace_id
    if span_id:
        response.headers[SPAN_ID_HEADER] = span_id


def _request_url(request: Request, include_query_params: bool) -> str:
    if include_query_params:
        return str(request.url)
    return f"{request.url.scheme}://{request.url.netloc}{request.url.path}"


def _request_log_kwargs(
    request: Request,
    response: Response,
    duration_ms: float,
    trace_id: str | None,
    span_id: str | None,
    include_query_params: bool,
) -> dict[str, Any]:
    log_kwargs: dict[str, Any] = {
        "http.method": request.method,
        "http.route": request.url.path,
        "http.status_code": response.status_code,
        "http.url": _request_url(request, include_query_params),
        "duration_ms": round(duration_ms, 2),
        "client.address": request.client.host if request.client else None,
    }

    if include_query_params:
        query_params = dict(request.query_params)
        if query_params:
            log_kwargs["http.query_params"] = query_params

    if trace_id:
        log_kwargs["trace.id"] = trace_id
    if span_id:
        log_kwargs["span.id"] = span_id

    return log_kwargs


def _log_request(status_code: int, log_kwargs: dict[str, Any]) -> None:
    if status_code >= 500:
        logger.error(_HTTP_REQUEST_LOG_MESSAGE, **log_kwargs)
    elif status_code >= 400:
        logger.warning(_HTTP_REQUEST_LOG_MESSAGE, **log_kwargs)
    else:
        logger.info(_HTTP_REQUEST_LOG_MESSAGE, **log_kwargs)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every HTTP request with semantic fields and inject trace headers.

    Combines the previous ``TraceCorrelationMiddleware`` with per-request
    structured logging so that New Relic (NRQL) can query on fields like
    ``http.method``, ``http.route``, ``http.status_code``, and ``duration_ms``.
    """

    def __init__(self, app: Any, config: Config | None = None) -> None:
        super().__init__(app)
        self._log_query_params = config.log_http_query_params if config else True

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000.0

        trace_id, span_id = _current_trace_ids()
        _set_trace_headers(response, trace_id, span_id)

        path = request.url.path
        if path not in _EXCLUDED_PATHS:
            log_kwargs = _request_log_kwargs(
                request,
                response,
                duration_ms,
                trace_id,
                span_id,
                self._log_query_params,
            )
            _log_request(response.status_code, log_kwargs)

        return response
