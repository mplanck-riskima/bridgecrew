"""Auth endpoints — Google ID token exchange for a dashboard JWT."""

from __future__ import annotations

import time

import jwt
from fastapi import APIRouter, HTTPException
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from pydantic import BaseModel

from app.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    id_token: str


class LoginResponse(BaseModel):
    access_token: str
    expires_in: int


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest) -> LoginResponse:
    """Exchange a Google ID token for a short-lived dashboard JWT."""
    try:
        idinfo = id_token.verify_oauth2_token(
            body.id_token,
            google_requests.Request(),
            settings.GOOGLE_CLIENT_ID,
        )
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Google token")

    if idinfo.get("email") not in settings.allowed_emails_list:
        raise HTTPException(status_code=403, detail="This Google account is not authorized")

    expires_in = settings.JWT_EXPIRE_HOURS * 3600
    payload = {"email": idinfo["email"], "exp": int(time.time()) + expires_in}
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")

    return LoginResponse(access_token=token, expires_in=expires_in)
