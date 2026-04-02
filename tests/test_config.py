"""Tests for configuration loading and validation."""

import pytest

from app.config import Config


def test_from_env_parses_all_fields(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PORT", "9000")
    monkeypatch.setenv("PGBOUNCER_HOST", "db.local")
    monkeypatch.setenv("PGBOUNCER_PORT", "6543")
    monkeypatch.setenv("POSTGRES_DB", "telemetry")
    monkeypatch.setenv("POSTGRES_USER", "alice")
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret")  # pragma: allowlist secret - test fixture
    monkeypatch.setenv("DB_POOL_MIN", "3")
    monkeypatch.setenv("DB_POOL_MAX", "8")
    monkeypatch.setenv("DB_CONNECT_TIMEOUT", "7")
    monkeypatch.setenv("DB_STATEMENT_TIMEOUT_MS", "20000")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "otel:4317")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "svc")
    monkeypatch.setenv("OTEL_SERVICE_NAMESPACE", "svc-ns")
    monkeypatch.setenv("OTEL_ENVIRONMENT", "staging")
    monkeypatch.setenv("APP_VERSION", "2.1.0")
    monkeypatch.setenv("BUILD_NUMBER", "42")
    monkeypatch.setenv("BUILD_DATE", "2026-02-22")
    monkeypatch.setenv("COGNITO_ISSUER", "https://issuer")
    monkeypatch.setenv("COGNITO_CLIENT_ID", "client123")
    monkeypatch.setenv("OAUTH2_ENABLED", "true")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv("LOG_FORMAT", "console")
    monkeypatch.setenv("LOG_SQL", "false")
    monkeypatch.setenv("LOG_SQL_PARAMS", "true")
    monkeypatch.setenv("LOG_HTTP_QUERY_PARAMS", "false")
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com, https://api.example.com ")
    monkeypatch.setenv("GARMIN_SYNC_BASE_URL", "http://garmin-sync.example:8080")
    monkeypatch.setenv("GARMIN_SYNC_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("INTERNAL_ENDPOINTS_ENABLED", "true")

    cfg = Config.from_env()

    assert cfg.port == 9000
    assert cfg.db_host == "db.local"
    assert cfg.db_port == 6543
    assert cfg.db_name == "telemetry"
    assert cfg.db_user == "alice"
    assert cfg.db_password == "secret"  # pragma: allowlist secret - test fixture
    assert cfg.db_pool_min == 3
    assert cfg.db_pool_max == 8
    assert cfg.db_connect_timeout == 7
    assert cfg.db_statement_timeout_ms == 20000
    assert cfg.otel_endpoint == "otel:4317"
    assert cfg.service_name == "svc"
    assert cfg.service_namespace == "svc-ns"
    assert cfg.environment == "staging"
    assert cfg.app_version == "2.1.0"
    assert cfg.build_number == "42"
    assert cfg.build_date == "2026-02-22"
    assert cfg.cognito_issuer == "https://issuer"
    assert cfg.cognito_client_id == "client123"
    assert cfg.oauth2_enabled is True
    assert cfg.log_level == "WARNING"
    assert cfg.log_format == "console"
    assert cfg.log_sql is False
    assert cfg.log_sql_params is True
    assert cfg.log_http_query_params is False
    assert cfg.cors_origins == ("https://app.example.com", "https://api.example.com")
    assert cfg.garmin_sync_base_url == "http://garmin-sync.example:8080"
    assert cfg.garmin_sync_timeout_seconds == 12.5
    assert cfg.internal_endpoints_enabled is True


def test_validate_database_requires_credentials():
    cfg = Config()
    with pytest.raises(RuntimeError):
        cfg.validate_database()


def test_validate_database_passes_with_credentials():
    cfg = Config(db_user="user", db_password="pass")
    cfg.validate_database()  # Should not raise
