"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    """Application configuration.

    All settings are loaded from environment variables via `from_env()`.
    """

    # Server
    port: int = 8080

    # Database (PgBouncer)
    db_host: str = "192.168.1.175"
    db_port: int = 6432
    db_name: str = "owntracks"
    db_user: str | None = None
    db_password: str | None = None
    db_pool_min: int = 2
    db_pool_max: int = 10
    db_connect_timeout: int = 5
    db_statement_timeout_ms: int = 15000

    # OpenTelemetry
    otel_endpoint: str = "localhost:4317"
    otel_traces_enabled: bool = False
    service_name: str = "otel-data-api"
    service_namespace: str = "otel-data-api"
    environment: str = "homelab"

    # Application metadata
    app_version: str = "1.0.0"
    build_number: str = "0"
    build_date: str = "unknown"

    # OAuth2/Cognito
    cognito_issuer: str = ""
    cognito_client_id: str = ""
    oauth2_enabled: bool = False

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"
    log_sql: bool = True
    log_sql_params: bool = False
    log_http_query_params: bool = True

    # CORS
    cors_origins: tuple[str, ...] = ()

    # Garmin sync proxy (to garmin-sync agent service)
    garmin_sync_base_url: str = "http://garmin-sync.garmin-sync.svc.cluster.local:8080"
    garmin_sync_timeout_seconds: float = 10.0

    @classmethod
    def from_env(cls) -> Config:
        """Create configuration from environment variables."""
        cors_origins_str = os.getenv("CORS_ORIGINS", "")
        cors_origins = tuple(s.strip() for s in cors_origins_str.split(",") if s.strip())

        return cls(
            port=int(os.getenv("PORT", "8080")),
            # Database
            db_host=os.getenv("PGBOUNCER_HOST", "192.168.1.175"),
            db_port=int(os.getenv("PGBOUNCER_PORT", "6432")),
            db_name=os.getenv("POSTGRES_DB", "owntracks"),
            db_user=os.getenv("POSTGRES_USER"),
            db_password=os.getenv("POSTGRES_PASSWORD"),
            db_pool_min=int(os.getenv("DB_POOL_MIN", "2")),
            db_pool_max=int(os.getenv("DB_POOL_MAX", "10")),
            db_connect_timeout=int(os.getenv("DB_CONNECT_TIMEOUT", "5")),
            db_statement_timeout_ms=int(os.getenv("DB_STATEMENT_TIMEOUT_MS", "15000")),
            # OpenTelemetry
            otel_endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "localhost:4317"),
            otel_traces_enabled=os.getenv("OTEL_TRACES_ENABLED", "false").lower() == "true",
            service_name=os.getenv("OTEL_SERVICE_NAME", "otel-data-api"),
            service_namespace=os.getenv("OTEL_SERVICE_NAMESPACE", "otel-data-api"),
            environment=os.getenv("OTEL_ENVIRONMENT", "homelab"),
            # Metadata
            app_version=os.getenv("APP_VERSION", "1.0.0"),
            build_number=os.getenv("BUILD_NUMBER", "0"),
            build_date=os.getenv("BUILD_DATE", "unknown"),
            # OAuth2/Cognito
            cognito_issuer=os.getenv("COGNITO_ISSUER", ""),
            cognito_client_id=os.getenv("COGNITO_CLIENT_ID", ""),
            oauth2_enabled=os.getenv("OAUTH2_ENABLED", "false").lower() == "true",
            # Logging
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            log_format=os.getenv("LOG_FORMAT", "json").lower(),
            log_sql=os.getenv("LOG_SQL", "true").lower() == "true",
            log_sql_params=os.getenv("LOG_SQL_PARAMS", "false").lower() == "true",
            log_http_query_params=os.getenv("LOG_HTTP_QUERY_PARAMS", "true").lower() == "true",
            # CORS
            cors_origins=cors_origins,
            # Garmin sync proxy
            garmin_sync_base_url=os.getenv(
                "GARMIN_SYNC_BASE_URL",
                "http://garmin-sync.garmin-sync.svc.cluster.local:8080",
            ),
            garmin_sync_timeout_seconds=float(os.getenv("GARMIN_SYNC_TIMEOUT_SECONDS", "10")),
        )

    def validate_database(self) -> None:
        """Validate database configuration."""
        if not self.db_user or not self.db_password:
            raise RuntimeError(
                "Database credentials not configured. Set POSTGRES_USER and POSTGRES_PASSWORD environment variables."
            )
