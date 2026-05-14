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
