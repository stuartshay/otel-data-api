"""Tests for FastAPI application factory and lifespan handling."""

from __future__ import annotations

import pytest
from fastapi.middleware.cors import CORSMiddleware

import app as app_module
from app.config import Config


def _config_with_cors() -> Config:
    return Config(
        db_user="user",
        db_password="pass",  # pragma: allowlist secret - test fixture
        cors_origins=("https://app.example.com",),
        cognito_issuer="https://issuer",  # pragma: allowlist secret - test fixture
        cognito_client_id="client123",  # pragma: allowlist secret - test fixture
        oauth2_enabled=True,
        app_version="2.0.1",
    )


@pytest.mark.asyncio
async def test_create_app_runs_lifespan_and_configures_middleware(monkeypatch: pytest.MonkeyPatch):
    auth_calls: dict[str, str | bool] = {}

    def _fake_auth(issuer: str, client_id: str, enabled: bool) -> None:
        auth_calls["issuer"] = issuer
        auth_calls["client_id"] = client_id
        auth_calls["enabled"] = enabled

    class DummyDB:
        def __init__(self, cfg: Config) -> None:
            self.cfg = cfg
            self.initialized = False
            self.closed = False

        async def initialize(self) -> None:
            self.initialized = True

        async def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(app_module, "DatabaseService", DummyDB)
    monkeypatch.setattr(app_module, "configure_auth", _fake_auth)

    cfg = _config_with_cors()
    app = app_module.create_app(cfg)

    assert any(m.cls is app_module.RequestLoggingMiddleware for m in app.user_middleware)
    assert any(m.cls is CORSMiddleware for m in app.user_middleware)

    async with app.router.lifespan_context(app):
        assert isinstance(app.state.db, DummyDB)
        assert app.state.db.initialized is True

    assert app.state.db.closed is True
    assert auth_calls == {"issuer": "https://issuer", "client_id": "client123", "enabled": True}


@pytest.mark.asyncio
async def test_create_app_handles_db_initialization_failure(monkeypatch: pytest.MonkeyPatch):
    events: list[str] = []

    class FailingDB:
        def __init__(self, cfg: Config) -> None:
            self.cfg = cfg
            self.closed = False

        async def initialize(self) -> None:
            events.append("init")
            raise RuntimeError("db down")

        async def close(self) -> None:
            events.append("close")
            self.closed = True

    monkeypatch.setattr(app_module, "DatabaseService", FailingDB)
    monkeypatch.setattr(app_module, "configure_auth", lambda *_args, **_kwargs: None)

    cfg = Config(db_user="user", db_password="pass")  # pragma: allowlist secret - test fixture
    app = app_module.create_app(cfg)

    async with app.router.lifespan_context(app):
        assert isinstance(app.state.db, FailingDB)

    assert events == ["init", "close"]
    assert app.state.db.closed is True
    assert not any(m.cls is CORSMiddleware for m in app.user_middleware)
