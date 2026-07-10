"""Tests for Cognito/JWT authentication helpers."""

from __future__ import annotations

import base64
import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials

from app import auth


def _token_with_header(header: dict[str, object]) -> str:
    encoded_header = base64.urlsafe_b64encode(json.dumps(header).encode("utf-8")).decode("ascii").rstrip("=")
    return f"{encoded_header}.payload.signature"


@pytest.fixture(autouse=True)
def reset_auth_state(monkeypatch: pytest.MonkeyPatch):
    """Reset module globals between tests to avoid cross-test leakage."""
    monkeypatch.setattr(auth, "_jwks_cache", {}, raising=False)
    auth.configure_auth("", "", False)


@pytest.mark.asyncio
async def test_get_current_user_returns_none_when_disabled():
    auth.configure_auth("", "", False)
    assert await auth.get_current_user(None) is None


@pytest.mark.asyncio
async def test_get_current_user_requires_header_when_enabled():
    auth.configure_auth("https://issuer", "client123", True)

    with pytest.raises(HTTPException) as exc:
        await auth.get_current_user(None)

    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc.value.detail == "Authorization header required"


@pytest.mark.asyncio
async def test_get_current_user_missing_signing_key(monkeypatch: pytest.MonkeyPatch):
    auth.configure_auth("https://issuer", "client123", True)

    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer", credentials=_token_with_header({"alg": "RS256", "kid": "missing"})
    )
    monkeypatch.setattr(auth, "_get_jwks", AsyncMock(return_value={"keys": [{"kid": "other"}]}))

    with pytest.raises(HTTPException) as exc:
        await auth.get_current_user(credentials)

    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc.value.detail == "Unable to find matching signing key"


@pytest.mark.asyncio
async def test_get_current_user_success(monkeypatch: pytest.MonkeyPatch):
    auth.configure_auth("https://issuer", "client123", True)

    token = _token_with_header({"alg": "RS256", "kid": "kid1"})
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    monkeypatch.setattr(auth, "_get_jwks", AsyncMock(return_value={"keys": [{"kid": "kid1"}]}))

    class DummyKey:
        def to_pem(self) -> bytes:
            return b"pem-key"

    monkeypatch.setattr(auth.jwk, "construct", lambda _key: DummyKey())
    decode_mock = MagicMock(return_value={"sub": "user1"})
    monkeypatch.setattr(auth.jwt, "decode", decode_mock)

    claims = await auth.get_current_user(credentials)

    decode_mock.assert_called_once_with(
        token,
        "pem-key",
        algorithms=["RS256"],
        audience="client123",
        issuer="https://issuer",
    )
    assert claims == {"sub": "user1"}


@pytest.mark.asyncio
async def test_get_current_user_jwks_failure(monkeypatch: pytest.MonkeyPatch):
    auth.configure_auth("https://issuer", "client123", True)
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials=_token_with_header({"alg": "RS256", "kid": "kid1"}),
    )

    monkeypatch.setattr(auth, "_get_jwks", AsyncMock(side_effect=httpx.HTTPError("offline")))

    with pytest.raises(HTTPException) as exc:
        await auth.get_current_user(credentials)

    assert exc.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert exc.value.detail == "Authentication service unavailable"


@pytest.mark.asyncio
async def test_get_current_user_rejects_malformed_jwt_header(monkeypatch: pytest.MonkeyPatch):
    auth.configure_auth("https://issuer", "client123", True)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="not-a-jwt")
    monkeypatch.setattr(auth, "_get_jwks", AsyncMock(return_value={"keys": [{"kid": "kid1"}]}))

    with pytest.raises(HTTPException) as exc:
        await auth.get_current_user(credentials)

    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc.value.detail == "Invalid token header"


@pytest.mark.asyncio
async def test_get_current_user_rejects_unexpected_jwt_algorithm(monkeypatch: pytest.MonkeyPatch):
    auth.configure_auth("https://issuer", "client123", True)
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials=_token_with_header({"alg": "none", "kid": "kid1"}),
    )
    monkeypatch.setattr(auth, "_get_jwks", AsyncMock(return_value={"keys": [{"kid": "kid1"}]}))

    with pytest.raises(HTTPException) as exc:
        await auth.get_current_user(credentials)

    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc.value.detail == "Invalid token header"


@pytest.mark.asyncio
async def test_require_auth_enforces_auth_flag():
    auth.configure_auth("https://issuer", "client123", True)
    with pytest.raises(HTTPException):
        await auth.require_auth(None)

    auth.configure_auth("https://issuer", "client123", False)
    assert await auth.require_auth(None) == {}
