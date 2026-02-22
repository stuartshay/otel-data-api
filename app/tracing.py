"""OpenTelemetry tracing setup with auto-instrumentation.

Initializes a ``TracerProvider`` with OTLP gRPC export and applies
auto-instrumentors for FastAPI, asyncpg, and httpx.  Gated on the
``OTEL_TRACES_ENABLED`` environment variable so tracing is opt-in.
"""

from __future__ import annotations

import structlog
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.config import Config

logger = structlog.get_logger(__name__)


def setup_tracing(app: FastAPI, config: Config) -> None:
    """Configure OpenTelemetry tracing and instrument the application.

    Does nothing when ``config.otel_traces_enabled`` is ``False``.
    """
    if not config.otel_traces_enabled:
        logger.info("OpenTelemetry tracing disabled (OTEL_TRACES_ENABLED != true)")
        return

    resource = Resource.create(
        {
            "service.name": config.service_name,
            "service.namespace": config.service_namespace,
            "deployment.environment": config.environment,
            "service.version": config.app_version,
        }
    )

    provider = TracerProvider(resource=resource)

    exporter = OTLPSpanExporter(
        endpoint=config.otel_endpoint,
        insecure=True,
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)

    # Auto-instrument FastAPI (creates spans for every request)
    FastAPIInstrumentor.instrument_app(app)

    # Auto-instrument asyncpg (creates spans for every SQL query)
    AsyncPGInstrumentor().instrument()

    # Auto-instrument httpx (creates spans for outbound HTTP calls)
    HTTPXClientInstrumentor().instrument()

    logger.info(
        "OpenTelemetry tracing initialized",
        otel_endpoint=config.otel_endpoint,
        service_name=config.service_name,
    )
