"""JWT authentication using AWS Cognito."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwk, jwt

logger = logging.getLogger(__name__)

_security = HTTPBearer(auto_error=False)

# Cached JWKS keys
_jwks_cache: dict[str, Any] = {}
_cognito_issuer: str = ""
_cognito_client_id: str = ""
_oauth2_enabled: bool = False


def configure_auth(issuer: str, client_id: str, enabled: bool) -> None:
    """Configure Cognito auth settings. Called at startup."""
    global _cognito_issuer, _cognito_client_id, _oauth2_enabled
    _cognito_issuer = issuer
    _cognito_client_id = client_id
    _oauth2_enabled = enabled


async def _get_jwks() -> dict[str, Any]:
    """Fetch and cache JWKS from Cognito issuer."""
    global _jwks_cache
    if _jwks_cache:
        return _jwks_cache

    jwks_url = f"{_cognito_issuer}/.well-known/jwks.json"
    async with httpx.AsyncClient() as client:
        response = await client.get(jwks_url, timeout=10.0)
        response.raise_for_status()
        _jwks_cache = response.json()
    return _jwks_cache


def _get_signing_key(token: str, jwks_data: dict[str, Any]) -> dict[str, Any]:
    """Find the signing key for the given token from JWKS."""
    unverified_header = jwt.get_unverified_header(token)
    kid = unverified_header.get("kid")
    for key in jwks_data.get("keys", []):
        if key.get("kid") == kid:
            return key
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unable to find matching signing key",
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_security),
) -> dict[str, Any] | None:
    """Validate JWT and return user claims. Returns None if auth is disabled."""
    if not _oauth2_enabled:
        return None

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header required",
        )

    token = credentials.credentials
    try:
        jwks_data = await _get_jwks()
        signing_key = _get_signing_key(token, jwks_data)
        public_key = jwk.construct(signing_key)

        claims = jwt.decode(
            token,
            public_key.to_pem().decode("utf-8"),
            algorithms=["RS256"],
            audience=_cognito_client_id,
            issuer=_cognito_issuer,
        )
        return claims
    except JWTError as e:
        logger.warning("JWT validation failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from e
    except httpx.HTTPError as e:
        logger.error("Failed to fetch JWKS: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service unavailable",
        ) from e


async def require_auth(
    user: dict[str, Any] | None = Depends(get_current_user),
) -> dict[str, Any]:
    """Dependency that requires valid authentication when OAuth2 is enabled."""
    if _oauth2_enabled and user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return user or {}
