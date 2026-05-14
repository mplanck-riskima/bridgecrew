"""Tests for the unified require_auth dependency and /auth/login endpoint."""

from __future__ import annotations

import time
from unittest.mock import patch

import jwt
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)

JWT_SECRET = "test-secret-key-for-unit-tests"
ALLOWED_EMAIL = "allowed@example.com"
API_KEY = "test-api-key-12345"


def make_valid_jwt() -> str:
    payload = {"email": ALLOWED_EMAIL, "exp": int(time.time()) + 3600}
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


# ── require_auth middleware tests ────────────────────────────────────────────


def test_protected_route_no_token():
    response = client.get("/api/projects")
    assert response.status_code == 401


def test_protected_route_valid_jwt():
    token = make_valid_jwt()
    response = client.get("/api/projects", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code != 401


def test_protected_route_valid_api_key():
    response = client.get("/api/projects", headers={"Authorization": f"Bearer {API_KEY}"})
    assert response.status_code != 401


def test_protected_route_expired_jwt():
    payload = {"email": ALLOWED_EMAIL, "exp": int(time.time()) - 1}
    expired = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
    response = client.get("/api/projects", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401


def test_protected_route_invalid_token():
    response = client.get("/api/projects", headers={"Authorization": "Bearer not-a-valid-token"})
    assert response.status_code == 401


def test_health_requires_no_auth():
    response = client.get("/health")
    assert response.status_code == 200


# ── /auth/login endpoint tests ───────────────────────────────────────────────


def test_login_valid_google_token():
    idinfo = {"email": ALLOWED_EMAIL, "sub": "google-uid-12345"}
    with patch("app.routers.auth.id_token.verify_oauth2_token", return_value=idinfo):
        response = client.post("/api/auth/login", json={"id_token": "fake-google-token"})
    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body
    assert "expires_in" in body
    decoded = jwt.decode(body["access_token"], JWT_SECRET, algorithms=["HS256"])
    assert decoded["email"] == ALLOWED_EMAIL


def test_login_invalid_google_token():
    with patch(
        "app.routers.auth.id_token.verify_oauth2_token",
        side_effect=ValueError("token invalid"),
    ):
        response = client.post("/api/auth/login", json={"id_token": "bad-token"})
    assert response.status_code == 401


def test_login_wrong_email():
    idinfo = {"email": "unauthorized@example.com", "sub": "google-uid-99"}
    with patch("app.routers.auth.id_token.verify_oauth2_token", return_value=idinfo):
        response = client.post("/api/auth/login", json={"id_token": "fake-google-token"})
    assert response.status_code == 403


def test_login_endpoint_requires_no_auth():
    """Login endpoint must be accessible without any Bearer token."""
    idinfo = {"email": ALLOWED_EMAIL, "sub": "google-uid-12345"}
    with patch("app.routers.auth.id_token.verify_oauth2_token", return_value=idinfo):
        response = client.post("/api/auth/login", json={"id_token": "fake-google-token"})
    assert response.status_code == 200
