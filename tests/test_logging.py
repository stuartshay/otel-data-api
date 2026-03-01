"""Tests for structured logging configuration."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import structlog

from app.config import Config
from app.logging import configure_logging


def _make_config(**overrides: str | int | bool) -> Config:
    """Return a minimal Config with optional overrides."""
    return Config(
        db_host=str(overrides.get("db_host", "localhost")),
        db_port=int(overrides.get("db_port", 5432)),
        db_name=str(overrides.get("db_name", "test")),
        db_user=str(overrides.get("db_user", "test")),
        db_password=str(overrides.get("db_password", "test")),  # noqa: S106
        service_name=str(overrides.get("service_name", "test-service")),
        service_namespace=str(overrides.get("service_namespace", "test-ns")),
        environment=str(overrides.get("environment", "test")),
        log_level=str(overrides.get("log_level", "DEBUG")),
        log_format=str(overrides.get("log_format", "json")),
        log_sql=bool(overrides.get("log_sql", True)),
        log_sql_params=bool(overrides.get("log_sql_params", False)),
        log_http_query_params=bool(overrides.get("log_http_query_params", True)),
    )


class TestConfigureLogging:
    """Tests for the configure_logging() function."""

    def test_json_format_produces_valid_json(self, capfd):
        """JSON format should produce parseable JSON log lines."""
        config = _make_config(log_format="json")
        configure_logging(config)

        test_logger = structlog.get_logger("test.json")
        test_logger.info("hello", key="value")

        captured = capfd.readouterr()
        line = captured.err.strip().split("\n")[-1]
        data = json.loads(line)

        assert data["event"] == "hello"
        assert data["key"] == "value"
        assert data["level"] == "info"
        assert "timestamp" in data

    def test_console_format_produces_readable_output(self, capfd):
        """Console format should produce human-readable (non-JSON) output."""
        config = _make_config(log_format="console")
        configure_logging(config)

        test_logger = structlog.get_logger("test.console")
        test_logger.info("console_event")

        captured = capfd.readouterr()
        assert "console_event" in captured.err

    def test_service_context_injected(self, capfd):
        """Service context fields should appear in every log event."""
        config = _make_config(log_format="json", service_name="my-api", environment="staging")
        configure_logging(config)

        test_logger = structlog.get_logger("test.ctx")
        test_logger.info("ctx_test")

        captured = capfd.readouterr()
        line = captured.err.strip().split("\n")[-1]
        data = json.loads(line)

        assert data["service.name"] == "my-api"
        assert data["environment"] == "staging"

    def test_log_level_respected(self, capfd):
        """Messages below the configured level should not appear."""
        config = _make_config(log_format="json", log_level="WARNING")
        configure_logging(config)

        test_logger = structlog.get_logger("test.level")
        test_logger.info("should_not_appear")
        test_logger.warning("should_appear")

        captured = capfd.readouterr()
        assert "should_not_appear" not in captured.err
        assert "should_appear" in captured.err

    def test_new_relic_context_injected_when_active(self, capfd):
        """trace.id and span.id should be injected when New Relic is active."""
        config = _make_config(log_format="json")
        configure_logging(config)

        mock_nr = MagicMock()
        mock_nr.current_trace_id.return_value = "nr-trace-123"
        mock_nr.current_span_id.return_value = "nr-span-456"
        mock_parent = MagicMock()
        mock_parent.agent = mock_nr

        with patch.dict("sys.modules", {"newrelic": mock_parent, "newrelic.agent": mock_nr}):
            test_logger = structlog.get_logger("test.nr")
            test_logger.info("nr_test")

        captured = capfd.readouterr()
        line = captured.err.strip().split("\n")[-1]
        data = json.loads(line)

        assert data.get("trace.id") == "nr-trace-123"
        assert data.get("span.id") == "nr-span-456"

    def test_new_relic_context_skipped_when_unavailable(self, capfd):
        """Logging should work fine without New Relic."""
        config = _make_config(log_format="json")
        configure_logging(config)

        test_logger = structlog.get_logger("test.no_nr")
        test_logger.info("no_nr_test")

        captured = capfd.readouterr()
        line = captured.err.strip().split("\n")[-1]
        data = json.loads(line)

        assert data["event"] == "no_nr_test"
        # trace.id and span.id should not be present
        assert "trace.id" not in data or data["trace.id"] is None
