"""Structured logging configuration using structlog.

Provides dual-mode rendering:
- ``json``  — one-line JSON per event (production / New Relic ingest)
- ``console`` — colorized human-readable output via *rich* (local development)

Call ``configure_logging(config)`` once at startup (before any logger is used).
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from opentelemetry import _logs as otel_logs
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource

from app.config import Config


def _add_service_context(config: Config) -> structlog.types.Processor:
    """Return a processor that injects service metadata into every log event."""

    def _processor(
        logger: Any,
        method_name: str,
        event_dict: structlog.types.EventDict,
    ) -> structlog.types.EventDict:
        event_dict["service.name"] = config.service_name
        event_dict["service.namespace"] = config.service_namespace
        event_dict["environment"] = config.environment
        return event_dict

    return _processor


def _add_trace_context(
    logger: Any,
    method_name: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    """Inject trace.id and span.id from OTel SDK with optional NR fallback."""
    trace_id: str | None = None
    span_id: str | None = None

    # Prefer OTel-native context
    try:
        from opentelemetry import trace as otel_trace

        span = otel_trace.get_current_span()
        ctx = span.get_span_context()
        if ctx and ctx.trace_id:
            trace_id = format(ctx.trace_id, "032x")
            span_id = format(ctx.span_id, "016x")
    except Exception:  # noqa: BLE001
        pass

    # Optional fallback for environments that still provide New Relic context.
    if not trace_id:
        try:
            import newrelic.agent  # pyright: ignore[reportMissingImports]

            trace_id = newrelic.agent.current_trace_id()
            span_id = newrelic.agent.current_span_id()
        except Exception:  # noqa: BLE001
            pass

    if trace_id:
        event_dict["trace.id"] = trace_id
    if span_id:
        event_dict["span.id"] = span_id
    return event_dict


def _ensure_message_field(
    logger: Any,
    method_name: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    """Populate ``message`` from structlog ``event`` for log UIs expecting it."""
    if "message" not in event_dict and "event" in event_dict:
        event_dict["message"] = event_dict["event"]
    return event_dict


def _build_otel_resource(config: Config) -> Resource:
    return Resource.create(
        {
            "service.name": config.service_name,
            "service.namespace": config.service_namespace,
            "deployment.environment": config.environment,
            "service.version": config.app_version,
        }
    )


def _configure_otel_log_export(config: Config, log_level: int) -> LoggerProvider:
    """Attach an OTLP log handler so logs flow via the collector."""
    provider = LoggerProvider(resource=_build_otel_resource(config))
    exporter = OTLPLogExporter(endpoint=config.otel_endpoint, insecure=True)
    provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
    otel_logs.set_logger_provider(provider)

    otel_handler = LoggingHandler(level=log_level, logger_provider=provider)
    logging.getLogger().addHandler(otel_handler)
    return provider


def configure_logging(config: Config) -> LoggerProvider | None:
    """Configure structlog with stdlib bridging.

    Parameters
    ----------
    config:
        Application configuration — ``log_level`` and ``log_format`` control
        verbosity and output format.
    """
    log_level = getattr(logging, config.log_level, logging.INFO)

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _add_service_context(config),
        _add_trace_context,
        _ensure_message_field,
    ]

    if config.log_format == "console":
        renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer(colors=True)
    else:
        renderer = structlog.processors.JSONRenderer()

    # -- Configure structlog itself (for structlog.get_logger()) ---------------
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # -- Configure stdlib root logger so all loggers (uvicorn, asyncpg, etc.)
    #    flow through the same structured pipeline. ---------------------
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        foreign_pre_chain=shared_processors,
    )

    root_logger = logging.getLogger()
    root_logger.handlers.clear()

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)

    # Quiet noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    if not config.otel_logs_enabled:
        return None

    try:
        provider = _configure_otel_log_export(config, log_level)
        logging.getLogger(__name__).info(
            "OpenTelemetry log export enabled",
            extra={"otel_endpoint": config.otel_endpoint},
        )
        return provider
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).exception(
            "Failed to configure OpenTelemetry log export; continuing with stdout logging only"
        )
        return None
