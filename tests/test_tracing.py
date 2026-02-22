"""Tests for OpenTelemetry tracing setup."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.config import Config
from app.tracing import setup_tracing


def _make_config(*, otel_traces_enabled: bool = False) -> Config:
    return Config(
        db_host="localhost",
        db_port=5432,
        db_name="test",
        db_user="test",
        db_password="test",  # noqa: S106  # pragma: allowlist secret
        otel_endpoint="localhost:4317",
        otel_traces_enabled=otel_traces_enabled,
        service_name="test-api",
        service_namespace="test-ns",
        environment="test",
    )


class TestSetupTracing:
    """Tests for setup_tracing()."""

    def test_tracing_disabled_does_nothing(self):
        """When otel_traces_enabled is False, no provider is configured."""
        app = MagicMock()
        config = _make_config(otel_traces_enabled=False)

        with patch("app.tracing.trace") as mock_trace:
            setup_tracing(app, config)
            mock_trace.set_tracer_provider.assert_not_called()

    @patch("app.tracing.HTTPXClientInstrumentor")
    @patch("app.tracing.AsyncPGInstrumentor")
    @patch("app.tracing.FastAPIInstrumentor")
    @patch("app.tracing.BatchSpanProcessor")
    @patch("app.tracing.OTLPSpanExporter")
    @patch("app.tracing.TracerProvider")
    @patch("app.tracing.trace")
    def test_tracing_enabled_configures_provider(
        self,
        mock_trace: MagicMock,
        mock_provider_cls: MagicMock,
        mock_exporter_cls: MagicMock,
        mock_processor_cls: MagicMock,
        mock_fastapi_inst: MagicMock,
        mock_asyncpg_inst: MagicMock,
        mock_httpx_inst: MagicMock,
    ) -> None:
        """When enabled, TracerProvider is created and instrumentors are applied."""
        app = MagicMock()
        config = _make_config(otel_traces_enabled=True)

        setup_tracing(app, config)

        # Provider configured and set
        mock_provider_cls.assert_called_once()
        mock_trace.set_tracer_provider.assert_called_once_with(mock_provider_cls.return_value)

        # OTLP exporter created with endpoint
        mock_exporter_cls.assert_called_once_with(endpoint="localhost:4317", insecure=True)

        # Span processor added
        mock_processor_cls.assert_called_once_with(mock_exporter_cls.return_value)
        mock_provider_cls.return_value.add_span_processor.assert_called_once_with(mock_processor_cls.return_value)

        # All three instrumentors applied
        mock_fastapi_inst.instrument_app.assert_called_once_with(app)
        mock_asyncpg_inst.return_value.instrument.assert_called_once()
        mock_httpx_inst.return_value.instrument.assert_called_once()


@pytest.mark.asyncio
async def test_app_with_tracing_disabled(client):
    """App starts normally when tracing is disabled (default test config)."""
    response = await client.get("/health")
    assert response.status_code == 200
