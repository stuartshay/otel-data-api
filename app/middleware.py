"""Middleware for request logging, trace correlation headers, and request context."""

from __future__ import annotations

import time
from typing import Any

import structlog
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

        # --- Trace correlation headers (New Relic) ---
        trace_id: str | None = None
        span_id: str | None = None
        try:
            import newrelic.agent  # pyright: ignore[reportMissingImports]

            trace_id = newrelic.agent.current_trace_id()
            span_id = newrelic.agent.current_span_id()
            if trace_id:
                response.headers[TRACE_ID_HEADER] = trace_id
            if span_id:
                response.headers[SPAN_ID_HEADER] = span_id
        except Exception:  # noqa: BLE001
            pass  # New Relic not available — skip silently

        # --- Request logging ---
        path = request.url.path
        if path not in _EXCLUDED_PATHS:
            url = (
                str(request.url)
                if self._log_query_params
                else f"{request.url.scheme}://{request.url.netloc}{request.url.path}"
            )
            log_kwargs: dict[str, Any] = {
                "http.method": request.method,
                "http.route": path,
                "http.status_code": response.status_code,
                "http.url": url,
                "duration_ms": round(duration_ms, 2),
                "client.address": request.client.host if request.client else None,
            }

            # Include query parameters when present and allowed by config
            if self._log_query_params:
                query_params = dict(request.query_params)
                if query_params:
                    log_kwargs["http.query_params"] = query_params

            if trace_id:
                log_kwargs["trace.id"] = trace_id
            if span_id:
                log_kwargs["span.id"] = span_id

            status_code = response.status_code
            if status_code >= 500:
                logger.error("HTTP request", **log_kwargs)
            elif status_code >= 400:
                logger.warning("HTTP request", **log_kwargs)
            else:
                logger.info("HTTP request", **log_kwargs)

        return response
