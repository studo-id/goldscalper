"""Authentication helpers.

Supports:
1. Multi-user JWT Bearer tokens (issued via `/api/auth/login` or `/api/auth/register`).
2. Legacy / system master Bearer token (``API_TOKEN``) for server-to-server or admin CLI.
"""

from __future__ import annotations

import datetime
import hmac
from typing import Any

import jwt
from fastapi import Depends, Header, HTTPException, Query, status

from config.logging import get_logger
from config.settings import settings

log = get_logger("api.auth")
JWT_ALGORITHM = "HS256"


def _get_jwt_secret() -> str:
    # Use api_token as default HMAC signing secret (40 chars)
    return settings.api_token or "goldscalper_default_jwt_secret_min_32_bytes_ok"


def create_access_token(user_id: str, email: str, role: str = "user", days: int = 30) -> str:
    """Issue a signed JWT access token."""
    expire = datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=days)
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "exp": expire,
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any] | None:
    """Decode and validate a JWT access token. Returns None on failure."""
    try:
        payload = jwt.decode(token, _get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        return payload
    except Exception:
        return None


def _matches(candidate: str | None) -> bool:
    """Check if token matches master API_TOKEN or is a valid JWT."""
    if not candidate:
        return False
    # Check master token
    if hmac.compare_digest(candidate, settings.api_token):
        return True
    # Check JWT
    decoded = decode_access_token(candidate)
    return decoded is not None


def extract_token_from_header(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


async def require_token(authorization: str | None = Header(default=None)) -> None:
    """FastAPI dependency enforcing a valid bearer token or JWT."""
    token = extract_token_from_header(authorization)
    if not _matches(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing token",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """FastAPI dependency returning the authenticated user info."""
    token = extract_token_from_header(authorization)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Master token fallback (acts as superadmin)
    if hmac.compare_digest(token, settings.api_token):
        return {
            "id": "master-admin",
            "email": "master@goldscalper.local",
            "full_name": "Master Operator",
            "role": "admin",
            "is_active": True,
        }

    decoded = decode_access_token(token)
    if not decoded:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired or invalid",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = decoded.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token payload missing user identifier",
            headers={"WWW-Authenticate": "Bearer"},
        )
    from data.user_repo import UserRepository
    repo = UserRepository()
    user = await repo.get_by_id(str(user_id))
    if not user or not user.get("is_active"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account disabled or not found",
        )
    return user


def verify_ws_token(token: str | None = Query(default=None)) -> bool:
    """Validate a WebSocket query token; raises HTTPException on failure."""
    if not _matches(token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return True


__all__ = [
    "require_token",
    "get_current_user",
    "verify_ws_token",
    "create_access_token",
    "decode_access_token",
    "Depends",
]
