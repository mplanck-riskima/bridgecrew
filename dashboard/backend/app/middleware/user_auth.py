"""Unified FastAPI auth dependency — accepts a dashboard JWT or a bot API key."""

from __future__ import annotations

import jwt
from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings

_bearer = HTTPBearer(auto_error=False)


def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> None:
    """Raise 401 unless the request carries a valid dashboard JWT or bot API key."""
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = credentials.credentials

    # Accept a valid bot API key
    if settings.BRIDGECREW_API_KEY and token == settings.BRIDGECREW_API_KEY:
        return

    # Accept a valid dashboard JWT
    if settings.JWT_SECRET:
        try:
            jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
            return
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token expired")
        except jwt.InvalidTokenError:
            pass

    raise HTTPException(status_code=401, detail="Invalid credentials")
