"""Middleware for trace correlation headers and request context."""

from __future__ import annotations

import logging
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

# Response header names for trace correlation
TRACE_ID_HEADER = "X-Trace-Id"
SPAN_ID_HEADER = "X-Span-Id"


class TraceCorrelationMiddleware(BaseHTTPMiddleware):
    """Inject New Relic trace/span IDs into response headers.

    Enables distributed tracing correlation between services by exposing
    trace context in HTTP response headers. When New Relic agent is not
    active, the middleware is a no-op.
    """

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        response = await call_next(request)
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
        return response
