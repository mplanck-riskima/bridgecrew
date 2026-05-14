# Google OAuth Authentication Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Google OAuth sign-in to the dashboard with full-stack enforcement — users must authenticate via Google before accessing any dashboard UI or API route, while bot API key access continues to work unchanged.

**Architecture:** Frontend uses `@react-oauth/google` to obtain a Google ID token; the backend verifies it, checks the email against `ALLOWED_EMAIL`, and returns a short-lived HS256 JWT. A unified `require_auth` dependency (accepting either the dashboard JWT or the existing bot API key) is applied at router-include level in `main.py`, replacing all per-route `require_api_key` usages.

**Tech Stack:** FastAPI, `google-auth`, `PyJWT`, `pytest`, React 19, `@react-oauth/google`, `sessionStorage`

---

## File Map

**Create:**
- `dashboard/backend/app/routers/auth.py` — `POST /api/auth/login` endpoint
- `dashboard/backend/app/middleware/user_auth.py` — unified `require_auth` dependency
- `dashboard/backend/tests/conftest.py` — test env var setup
- `dashboard/backend/tests/test_auth.py` — auth tests
- `dashboard/frontend/src/context/AuthContext.tsx` — JWT state + sessionStorage
- `dashboard/frontend/src/pages/Login.tsx` — Google Sign-In page
- `dashboard/frontend/src/components/RequireAuth.tsx` — route guard

**Modify:**
- `dashboard/backend/requirements.txt` — add `google-auth`, `PyJWT`, `pytest`
- `dashboard/backend/app/config.py` — add `GOOGLE_CLIENT_ID`, `ALLOWED_EMAIL`, `JWT_SECRET`, `JWT_EXPIRE_HOURS`
- `dashboard/backend/app/main.py` — register auth router; add `require_auth` to all API routers
- `dashboard/backend/app/routers/costs.py` — remove per-route `require_api_key`
- `dashboard/backend/app/routers/activity.py` — remove per-route `require_api_key`
- `dashboard/backend/app/routers/features.py` — remove per-route `require_api_key`
- `dashboard/backend/app/routers/projects.py` — remove per-route `require_api_key`
- `dashboard/backend/app/routers/prompts.py` — remove per-route `require_api_key`
- `dashboard/frontend/src/vite-env.d.ts` — declare `VITE_GOOGLE_CLIENT_ID`
- `dashboard/frontend/src/lib/api.ts` — inject `Authorization` header; handle 401
- `dashboard/frontend/src/main.tsx` — wrap with `GoogleOAuthProvider` + `AuthProvider`
- `dashboard/frontend/src/App.tsx` — add `/login` route; wrap layout in `RequireAuth`
- `dashboard/frontend/src/components/Layout.tsx` — add logout button

---

## Task 1: Backend packages and config

**Files:**
- Modify: `dashboard/backend/requirements.txt`
- Modify: `dashboard/backend/app/config.py`

- [ ] **Step 1: Add new packages to requirements.txt**

  Open `dashboard/backend/requirements.txt` and add three lines:

  ```
  google-auth>=2.30.0
  PyJWT>=2.9.0
  pytest>=8.0.0
  ```

  Final file should look like:
  ```
  fastapi>=0.115.0
  uvicorn[standard]>=0.32.0
  pymongo>=4.10.0
  pydantic>=2.10.0
  pydantic-settings>=2.0.0
  python-ulid>=2.0.0
  python-dotenv>=1.0.0
  httpx>=0.27.0
  apscheduler>=3.10.4
  google-auth>=2.30.0
  PyJWT>=2.9.0
  pytest>=8.0.0
  ```

- [ ] **Step 2: Install packages**

  ```bash
  cd dashboard/backend && pip install google-auth PyJWT pytest
  ```

- [ ] **Step 3: Add new settings to config.py**

  In `dashboard/backend/app/config.py`, add four fields to `BridgeCrewSettings` after `DISCORD_CHANNEL_ID`:

  ```python
  # Google OAuth + dashboard JWT
  GOOGLE_CLIENT_ID: str = ""
  ALLOWED_EMAIL: str = ""
  JWT_SECRET: str = ""
  JWT_EXPIRE_HOURS: int = 24
  ```

  Full updated class:
  ```python
  class BridgeCrewSettings(BaseSettings):
      model_config = SettingsConfigDict(
          env_file=".env",
          env_file_encoding="utf-8",
          extra="ignore",
      )

      MONGODB_URI: str = ""
      MONGODB_DATABASE: str = "bridgecrew_dev"
      BRIDGECREW_API_KEY: str = ""
      DISCORD_TOKEN: str = ""
      DISCORD_GUILD_ID: str = ""
      DISCORD_CHANNEL_ID: str = ""
      ALLOWED_ORIGINS: str = "http://localhost:5173"

      # Google OAuth + dashboard JWT
      GOOGLE_CLIENT_ID: str = ""
      ALLOWED_EMAIL: str = ""
      JWT_SECRET: str = ""
      JWT_EXPIRE_HOURS: int = 24

      @property
      def allowed_origins_list(self) -> list[str]:
          return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]
  ```

- [ ] **Step 4: Commit**

  ```bash
  git add dashboard/backend/requirements.txt dashboard/backend/app/config.py
  git commit -m "chore: add google-auth, PyJWT packages and auth config fields"
  ```

---

## Task 2: Unified require_auth middleware (TDD)

**Files:**
- Create: `dashboard/backend/tests/conftest.py`
- Create: `dashboard/backend/tests/test_auth.py`
- Create: `dashboard/backend/app/middleware/user_auth.py`

- [ ] **Step 1: Create test conftest.py**

  Create `dashboard/backend/tests/__init__.py` (empty file), then create `dashboard/backend/tests/conftest.py`:

  ```python
  import os

  # Set env vars before any app module is imported by test collection
  os.environ.setdefault("JWT_SECRET", "test-secret-key-for-unit-tests")
  os.environ.setdefault("ALLOWED_EMAIL", "allowed@example.com")
  os.environ.setdefault("GOOGLE_CLIENT_ID", "fake-client-id.apps.googleusercontent.com")
  os.environ.setdefault("BRIDGECREW_API_KEY", "test-api-key-12345")
  os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")
  ```

- [ ] **Step 2: Write failing tests for require_auth**

  Create `dashboard/backend/tests/test_auth.py`:

  ```python
  """Tests for the unified require_auth dependency and /auth/login endpoint."""

  from __future__ import annotations

  import time
  from unittest.mock import patch

  import jwt
  import pytest
  from fastapi.testclient import TestClient

  from app.main import app

  client = TestClient(app)

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
  ```

- [ ] **Step 3: Run tests — expect failures**

  ```bash
  cd dashboard/backend && pytest tests/test_auth.py -v -k "not login"
  ```

  Expected: 5 failures (`test_protected_route_*` fail because no auth is wired yet; `test_health_requires_no_auth` may pass).

- [ ] **Step 4: Create user_auth.py**

  Create `dashboard/backend/app/middleware/user_auth.py`:

  ```python
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
  ```

- [ ] **Step 5: Wire require_auth into main.py**

  Replace the router includes in `dashboard/backend/app/main.py` — add `dependencies=[Depends(require_auth)]` to every API router and register the (not-yet-created) auth router. Also add the necessary imports.

  Final `main.py`:

  ```python
  """FastAPI application — monitoring dashboard backend."""

  from __future__ import annotations

  from contextlib import asynccontextmanager
  from pathlib import Path

  from fastapi import Depends, FastAPI
  from fastapi.middleware.cors import CORSMiddleware
  from fastapi.responses import FileResponse
  from fastapi.staticfiles import StaticFiles

  from app import scheduler as sched
  from app.config import settings
  from app.middleware.user_auth import require_auth
  from app.routers import activity, auth, costs, features, projects, prompts, schedules

  STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


  @asynccontextmanager
  async def lifespan(app: FastAPI):
      sched.start()
      try:
          yield
      finally:
          sched.stop()


  app = FastAPI(title="BridgeCrew Dashboard", version="0.1.0", lifespan=lifespan)

  app.add_middleware(
      CORSMiddleware,
      allow_origins=settings.allowed_origins_list,
      allow_credentials=True,
      allow_methods=["*"],
      allow_headers=["*"],
  )


  @app.get("/health")
  async def health():
      """Health check endpoint — no auth required."""
      return {"status": "ok"}


  # Public auth endpoint (no require_auth dependency)
  app.include_router(auth.router, prefix="/api")

  # Dashboard + bot API routes — protected by require_auth
  _auth = [Depends(require_auth)]
  app.include_router(projects.router, prefix="/api", dependencies=_auth)
  app.include_router(features.router, prefix="/api", dependencies=_auth)
  app.include_router(costs.router, prefix="/api", dependencies=_auth)
  app.include_router(prompts.router, prefix="/api", dependencies=_auth)
  app.include_router(schedules.router, prefix="/api", dependencies=_auth)
  app.include_router(activity.router, prefix="/api", dependencies=_auth)

  # Serve frontend static files in production
  if STATIC_DIR.exists():
      assets_dir = STATIC_DIR / "assets"
      if assets_dir.exists():
          app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

      @app.get("/{full_path:path}")
      async def serve_spa(full_path: str) -> FileResponse:
          file_path = STATIC_DIR / full_path
          if file_path.is_file():
              return FileResponse(str(file_path))
          return FileResponse(str(STATIC_DIR / "index.html"))
  ```

  Note: `from app.routers import auth` will fail at import time until `auth.py` exists. Create a minimal stub now (Task 3 will flesh it out):

  Create `dashboard/backend/app/routers/auth.py` with just enough for the import to work:

  ```python
  from fastapi import APIRouter
  router = APIRouter(prefix="/auth", tags=["auth"])
  ```

- [ ] **Step 6: Remove per-route require_api_key from all routers**

  **`dashboard/backend/app/routers/costs.py`** — remove lines 11-12 and the `Depends(require_api_key)` param from `ingest_cost`:
  ```python
  # Remove these lines:
  from app.middleware.api_key import require_api_key
  # Remove from ingest_cost signature:
  _: None = Depends(require_api_key),
  ```

  Updated `ingest_cost` signature:
  ```python
  @router.post("/costs", status_code=201)
  def ingest_cost(body: CostCreate) -> dict:
  ```

  **`dashboard/backend/app/routers/activity.py`** — remove `require_api_key` import and dep from `ingest_activity`:
  ```python
  @router.post("/activity", status_code=201)
  def ingest_activity(body: ActivityCreate) -> dict:
  ```

  **`dashboard/backend/app/routers/features.py`** — remove `require_api_key` import and dep from `create_feature` and `update_feature`:
  ```python
  @router.post("/features", status_code=201)
  def create_feature(body: FeatureCreate) -> dict:

  @router.patch("/features/{feature_id}")
  def update_feature(feature_id: str, body: FeatureUpdate) -> dict:
  ```

  **`dashboard/backend/app/routers/projects.py`** — remove `require_api_key` import and dep from `get_project_prompt`:
  ```python
  @router.get("/projects/{project_id}/prompt")
  def get_project_prompt(project_id: str) -> dict:
  ```

  **`dashboard/backend/app/routers/prompts.py`** — remove `require_api_key` import and dep from `get_prompt`:
  ```python
  @router.get("/prompts/{prompt_id}")
  def get_prompt(prompt_id: str) -> dict:
  ```

  After editing each file, verify there are no remaining `require_api_key` references:
  ```bash
  grep -r "require_api_key" dashboard/backend/app/routers/
  ```
  Expected: no output.

- [ ] **Step 7: Commit**

  ```bash
  git add dashboard/backend/app/middleware/user_auth.py \
          dashboard/backend/app/main.py \
          dashboard/backend/app/routers/costs.py \
          dashboard/backend/app/routers/activity.py \
          dashboard/backend/app/routers/features.py \
          dashboard/backend/app/routers/projects.py \
          dashboard/backend/app/routers/prompts.py \
          dashboard/backend/tests/__init__.py \
          dashboard/backend/tests/conftest.py \
          dashboard/backend/tests/test_auth.py
  git commit -m "feat: add unified require_auth middleware; apply to all API routers"
  ```

---

## Task 3: /auth/login endpoint (TDD)

**Files:**
- Modify: `dashboard/backend/tests/test_auth.py`
- Create: `dashboard/backend/app/routers/auth.py`

- [ ] **Step 1: Add login tests to test_auth.py**

  Append to `dashboard/backend/tests/test_auth.py`:

  ```python
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
  ```

- [ ] **Step 2: Run tests — expect failures**

  ```bash
  cd dashboard/backend && pytest tests/test_auth.py::test_login_valid_google_token tests/test_auth.py::test_login_invalid_google_token tests/test_auth.py::test_login_wrong_email -v
  ```

  Expected: all 3 FAIL (`404` — the router doesn't exist yet).

- [ ] **Step 3: Create auth.py router**

  Create `dashboard/backend/app/routers/auth.py`:

  ```python
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

      if idinfo.get("email") != settings.ALLOWED_EMAIL:
          raise HTTPException(status_code=403, detail="This Google account is not authorized")

      expires_in = settings.JWT_EXPIRE_HOURS * 3600
      payload = {"email": idinfo["email"], "exp": int(time.time()) + expires_in}
      token = jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")

      return LoginResponse(access_token=token, expires_in=expires_in)
  ```

- [ ] **Step 4: Run all tests — expect all green**

  ```bash
  cd dashboard/backend && pytest tests/test_auth.py -v
  ```

  Expected output (all PASSED):
  ```
  tests/test_auth.py::test_protected_route_no_token PASSED
  tests/test_auth.py::test_protected_route_valid_jwt PASSED
  tests/test_auth.py::test_protected_route_valid_api_key PASSED
  tests/test_auth.py::test_protected_route_expired_jwt PASSED
  tests/test_auth.py::test_protected_route_invalid_token PASSED
  tests/test_auth.py::test_health_requires_no_auth PASSED
  tests/test_auth.py::test_login_valid_google_token PASSED
  tests/test_auth.py::test_login_invalid_google_token PASSED
  tests/test_auth.py::test_login_wrong_email PASSED
  tests/test_auth.py::test_login_endpoint_requires_no_auth PASSED
  ```

  If `test_protected_route_valid_jwt` or `test_protected_route_valid_api_key` fails with a DB-related error (can't connect to MongoDB), that's acceptable — the important thing is that the status code is NOT 401 (auth passed; the route handler failed for a different reason). The assertion `assert response.status_code != 401` will still pass.

- [ ] **Step 5: Commit**

  ```bash
  git add dashboard/backend/app/routers/auth.py dashboard/backend/tests/test_auth.py
  git commit -m "feat: add /api/auth/login endpoint (Google ID token → dashboard JWT)"
  ```

---

## Task 4: Frontend — install package and AuthContext

**Files:**
- Modify: `dashboard/frontend/package.json` (via npm install)
- Modify: `dashboard/frontend/src/vite-env.d.ts`
- Create: `dashboard/frontend/src/context/AuthContext.tsx`

- [ ] **Step 1: Install @react-oauth/google**

  ```bash
  cd dashboard/frontend && npm install @react-oauth/google
  ```

- [ ] **Step 2: Extend vite-env.d.ts**

  Replace `dashboard/frontend/src/vite-env.d.ts` with:

  ```typescript
  /// <reference types="vite/client" />

  declare const __COMMIT_HASH__: string;

  interface ImportMetaEnv {
    readonly VITE_GOOGLE_CLIENT_ID: string;
  }

  interface ImportMeta {
    readonly env: ImportMetaEnv;
  }
  ```

- [ ] **Step 3: Create AuthContext.tsx**

  Create `dashboard/frontend/src/context/AuthContext.tsx`:

  ```tsx
  import { createContext, useContext, useState, type ReactNode } from "react";

  export const TOKEN_KEY = "dashboard_token";

  interface AuthContextValue {
    token: string | null;
    login: (token: string) => void;
    logout: () => void;
  }

  const AuthContext = createContext<AuthContextValue | null>(null);

  export function AuthProvider({ children }: { children: ReactNode }) {
    const [token, setToken] = useState<string | null>(
      () => sessionStorage.getItem(TOKEN_KEY),
    );

    function login(newToken: string) {
      sessionStorage.setItem(TOKEN_KEY, newToken);
      setToken(newToken);
    }

    function logout() {
      sessionStorage.removeItem(TOKEN_KEY);
      setToken(null);
    }

    return (
      <AuthContext.Provider value={{ token, login, logout }}>
        {children}
      </AuthContext.Provider>
    );
  }

  export function useAuth(): AuthContextValue {
    const ctx = useContext(AuthContext);
    if (!ctx) throw new Error("useAuth must be used within AuthProvider");
    return ctx;
  }
  ```

- [ ] **Step 4: Commit**

  ```bash
  git add dashboard/frontend/package.json dashboard/frontend/package-lock.json \
          dashboard/frontend/src/vite-env.d.ts \
          dashboard/frontend/src/context/AuthContext.tsx
  git commit -m "feat: add AuthContext and install @react-oauth/google"
  ```

---

## Task 5: Frontend — Login page

**Files:**
- Create: `dashboard/frontend/src/pages/Login.tsx`

- [ ] **Step 1: Create Login.tsx**

  Create `dashboard/frontend/src/pages/Login.tsx`:

  ```tsx
  import { GoogleLogin } from "@react-oauth/google";
  import { useState } from "react";
  import { useNavigate } from "react-router";
  import { useAuth } from "@/context/AuthContext";

  export default function Login() {
    const { login } = useAuth();
    const navigate = useNavigate();
    const [error, setError] = useState<string | null>(null);

    async function handleCredential(credentialResponse: { credential?: string }) {
      if (!credentialResponse.credential) {
        setError("No credential returned from Google.");
        return;
      }
      setError(null);
      try {
        const res = await fetch("/api/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id_token: credentialResponse.credential }),
        });
        if (res.status === 403) {
          setError("This Google account is not authorized.");
          return;
        }
        if (!res.ok) {
          setError("Sign-in failed. Please try again.");
          return;
        }
        const { access_token } = await res.json();
        login(access_token);
        navigate("/", { replace: true });
      } catch {
        setError("Network error. Please try again.");
      }
    }

    return (
      <div className="h-screen bg-lcars-bg flex items-center justify-center">
        <div className="flex flex-col items-center gap-6">
          <div className="text-lcars-orange font-mono text-xs tracking-[0.4em] uppercase mb-2">
            BridgeCrew Access Control
          </div>
          <div className="w-48 h-1 bg-lcars-orange" />
          <GoogleLogin
            onSuccess={handleCredential}
            onError={() => setError("Google sign-in failed. Please try again.")}
          />
          {error && (
            <p className="text-red-400 font-mono text-xs tracking-wider">{error}</p>
          )}
        </div>
      </div>
    );
  }
  ```

- [ ] **Step 2: Commit**

  ```bash
  git add dashboard/frontend/src/pages/Login.tsx
  git commit -m "feat: add Login page with Google Sign-In button"
  ```

---

## Task 6: Frontend — RequireAuth and api.ts token injection

**Files:**
- Create: `dashboard/frontend/src/components/RequireAuth.tsx`
- Modify: `dashboard/frontend/src/lib/api.ts`

- [ ] **Step 1: Create RequireAuth.tsx**

  Create `dashboard/frontend/src/components/RequireAuth.tsx`:

  ```tsx
  import type { ReactNode } from "react";
  import { Navigate } from "react-router";
  import { useAuth } from "@/context/AuthContext";

  export default function RequireAuth({ children }: { children: ReactNode }) {
    const { token } = useAuth();
    if (!token) return <Navigate to="/login" replace />;
    return <>{children}</>;
  }
  ```

- [ ] **Step 2: Update api.ts to inject Authorization header and handle 401**

  Replace the `request` function and add the `TOKEN_KEY` import at the top of `dashboard/frontend/src/lib/api.ts`:

  Add this import at the top (after the existing type imports):
  ```typescript
  import { TOKEN_KEY } from "@/context/AuthContext";
  ```

  Replace the existing `request` function with:
  ```typescript
  async function request<T>(path: string, init?: RequestInit): Promise<T> {
    const token = sessionStorage.getItem(TOKEN_KEY);
    const baseHeaders: Record<string, string> = { "Content-Type": "application/json" };
    if (token) baseHeaders["Authorization"] = `Bearer ${token}`;

    const res = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { ...baseHeaders, ...(init?.headers as Record<string, string> | undefined) },
    });

    if (res.status === 401) {
      sessionStorage.removeItem(TOKEN_KEY);
      window.location.href = "/login";
      throw new Error("401: Unauthorized");
    }
    if (!res.ok) {
      const body = await res.text();
      throw new Error(`${res.status}: ${body}`);
    }
    if (res.status === 204) return undefined as T;
    return res.json() as Promise<T>;
  }
  ```

- [ ] **Step 3: Commit**

  ```bash
  git add dashboard/frontend/src/components/RequireAuth.tsx \
          dashboard/frontend/src/lib/api.ts
  git commit -m "feat: add RequireAuth guard and inject JWT into all API requests"
  ```

---

## Task 7: Frontend — wire providers, routes, and logout

**Files:**
- Modify: `dashboard/frontend/src/main.tsx`
- Modify: `dashboard/frontend/src/App.tsx`
- Modify: `dashboard/frontend/src/components/Layout.tsx`

- [ ] **Step 1: Update main.tsx with GoogleOAuthProvider and AuthProvider**

  Replace `dashboard/frontend/src/main.tsx` with:

  ```tsx
  import { GoogleOAuthProvider } from "@react-oauth/google";
  import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
  import { StrictMode } from "react";
  import { createRoot } from "react-dom/client";
  import { BrowserRouter } from "react-router";
  import App from "./App";
  import { AuthProvider } from "./context/AuthContext";
  import "./index.css";

  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchInterval: 60_000,
      },
    },
  });

  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <GoogleOAuthProvider clientId={import.meta.env.VITE_GOOGLE_CLIENT_ID}>
        <AuthProvider>
          <QueryClientProvider client={queryClient}>
            <BrowserRouter>
              <App />
            </BrowserRouter>
          </QueryClientProvider>
        </AuthProvider>
      </GoogleOAuthProvider>
    </StrictMode>,
  );
  ```

- [ ] **Step 2: Update App.tsx with /login route and RequireAuth**

  Replace `dashboard/frontend/src/App.tsx` with:

  ```tsx
  import { Route, Routes } from "react-router";
  import Layout from "./components/Layout";
  import RequireAuth from "./components/RequireAuth";
  import Costs from "./pages/Costs";
  import Dashboard from "./pages/Dashboard";
  import Login from "./pages/Login";
  import ProjectDetail from "./pages/ProjectDetail";
  import Projects from "./pages/Projects";
  import Prompts from "./pages/Prompts";
  import Schedules from "./pages/Schedules";

  export default function App() {
    return (
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          element={
            <RequireAuth>
              <Layout />
            </RequireAuth>
          }
        >
          <Route index element={<Dashboard />} />
          <Route path="projects" element={<Projects />} />
          <Route path="projects/:id" element={<ProjectDetail />} />
          <Route path="prompts" element={<Prompts />} />
          <Route path="schedules" element={<Schedules />} />
          <Route path="costs" element={<Costs />} />
        </Route>
      </Routes>
    );
  }
  ```

- [ ] **Step 3: Add logout button to Layout.tsx**

  In `dashboard/frontend/src/components/Layout.tsx`:

  Add imports at the top:
  ```tsx
  import { useNavigate } from "react-router";
  import { useAuth } from "@/context/AuthContext";
  ```

  Add these two lines inside the `Layout` component body, before the return statement:
  ```tsx
  const { logout } = useAuth();
  const navigate = useNavigate();
  ```

  Add a logout handler:
  ```tsx
  function handleLogout() {
    logout();
    navigate("/login", { replace: true });
  }
  ```

  In the **desktop sidebar**, replace the bottom corner piece `<div>` (the one containing `__COMMIT_HASH__`) with:
  ```tsx
  {/* Bottom corner piece */}
  <div className="flex shrink-0" style={{ height: "40px" }}>
    <div className="w-12 h-full bg-lcars-orange rounded-tr-[2rem] shrink-0" />
    <div className="flex-1 flex items-center justify-between pl-3 pr-2">
      <span className="text-lcars-muted text-xs font-mono tracking-widest opacity-60">
        {__COMMIT_HASH__}
      </span>
      <button
        onClick={handleLogout}
        className="text-lcars-muted text-xs font-mono tracking-widest uppercase hover:text-lcars-orange transition-colors"
      >
        Logout
      </button>
    </div>
  </div>
  ```

- [ ] **Step 4: Run TypeScript check**

  ```bash
  cd dashboard/frontend && npx tsc --noEmit
  ```

  Expected: no errors. If errors appear, fix them before committing.

- [ ] **Step 5: Commit**

  ```bash
  git add dashboard/frontend/src/main.tsx \
          dashboard/frontend/src/App.tsx \
          dashboard/frontend/src/components/Layout.tsx
  git commit -m "feat: wire Google OAuth providers, RequireAuth routes, and logout button"
  ```

---

## Task 8: Environment variable setup

**Files:**
- Create (git-ignored): `dashboard/backend/.env` additions
- Create (git-ignored): `dashboard/frontend/.env.local`

This task is setup only — no code changes. See the Google OAuth setup instructions provided separately.

- [ ] **Step 1: Add backend env vars**

  In `dashboard/backend/.env` (create if it doesn't exist), add:

  ```
  GOOGLE_CLIENT_ID=<your-client-id>.apps.googleusercontent.com
  ALLOWED_EMAIL=planckfamily@gmail.com
  JWT_SECRET=<generate with: python -c "import secrets; print(secrets.token_hex(32))">
  JWT_EXPIRE_HOURS=24
  ```

- [ ] **Step 2: Add frontend env var**

  Create `dashboard/frontend/.env.local`:

  ```
  VITE_GOOGLE_CLIENT_ID=<your-client-id>.apps.googleusercontent.com
  ```

  (Same client ID as above.)

- [ ] **Step 3: Verify .gitignore covers these files**

  ```bash
  git check-ignore -v dashboard/backend/.env dashboard/frontend/.env.local
  ```

  Both should be ignored. If not, add them to the root `.gitignore`.

- [ ] **Step 4: Final integration test**

  Start the backend:
  ```bash
  cd dashboard/backend && uvicorn app.main:app --reload
  ```

  Start the frontend (separate terminal):
  ```bash
  cd dashboard/frontend && npm run dev
  ```

  Verify:
  1. Navigating to `http://localhost:5173` redirects to `/login`
  2. Clicking "Sign in with Google" shows the Google popup
  3. Signing in with `planckfamily@gmail.com` redirects to the dashboard
  4. All dashboard pages load normally
  5. Refreshing the page keeps you logged in (sessionStorage persists within the tab)
  6. Clicking Logout redirects to `/login`
  7. `curl http://localhost:8000/api/projects` returns `401`
  8. `curl http://localhost:8000/health` returns `{"status":"ok"}`
  9. `curl -H "Authorization: Bearer <api-key>" http://localhost:8000/api/projects` returns `200`

- [ ] **Step 5: Final commit**

  ```bash
  git add .gitignore  # only if changes were needed
  git commit -m "feat: complete Google OAuth authentication guard"
  ```

---

## Google OAuth App Setup

See the setup instructions provided by the assistant for creating a Google OAuth 2.0 client ID at `console.cloud.google.com` with the correct origins for both localhost and `bridgecrew.riskima.com`.
