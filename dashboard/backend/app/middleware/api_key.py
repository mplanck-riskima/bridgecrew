"""FastAPI dependency for validating bot → webapp API calls."""

from __future__ import annotations

from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings

_bearer = HTTPBearer(auto_error=False)


def require_api_key(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> None:
    """Raise 403 if the request does not carry the correct Bearer token."""
    if not settings.BRIDGECREW_API_KEY:
        return
    if credentials is None or credentials.credentials != settings.BRIDGECREW_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid or missing API key")
