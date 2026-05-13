# Google OAuth Authentication Guard — Design Spec

**Date:** 2026-05-13  
**Status:** Approved

## Overview

Add a Google OAuth authentication guard to the dashboard. Unauthenticated users see a login page; authenticated users get a short-lived JWT that is validated on every API call. A single allowed email is configured via environment variable. Bot→API routes are unaffected.

---

## Architecture & Token Flow

```
User → /login page
  → clicks "Sign in with Google"
  → Google OAuth popup (hosted by Google)
  → Google returns an ID token to the browser

Frontend → POST /auth/login { id_token }
  Backend: verify ID token signature with Google's public keys
  Backend: check email == ALLOWED_EMAIL env var
  Backend: issue own JWT (HS256, signed with JWT_SECRET, 24h expiry)
  ← { access_token, expires_in }

Frontend stores JWT in sessionStorage + AuthContext
Every subsequent API call: Authorization: Bearer <our-jwt>
Backend dependency validates JWT on all dashboard routes

On 401 from any call → clear auth state → redirect to /login
On page refresh → read token from sessionStorage → validate expiry locally
```

---

## Environment Variables

| Variable | Side | Purpose |
|---|---|---|
| `VITE_GOOGLE_CLIENT_ID` | Frontend (Vite) | Identifies the OAuth app to Google |
| `GOOGLE_CLIENT_ID` | Backend | Used to verify the Google ID token |
| `ALLOWED_EMAIL` | Backend | Single email permitted to access the dashboard |
| `JWT_SECRET` | Backend | HS256 signing secret for dashboard JWTs |
| `JWT_EXPIRE_HOURS` | Backend | JWT lifetime in hours (default: 24) |

Existing `BRIDGECREW_API_KEY` is unchanged — bot routes keep their current auth.

---

## Frontend

### New package
- `@react-oauth/google`

### New files

**`src/context/AuthContext.tsx`**  
React context holding `{ token, login(token), logout() }`. Reads/writes `sessionStorage` so the session survives page refresh but not a new tab. Exposes a `useAuth()` hook.

**`src/pages/Login.tsx`**  
Full-page Google Sign-In button using the `GoogleLogin` component. On credential response, POSTs the Google ID token to `/auth/login`. On success, calls `login(token)` and navigates to `/`. On failure (403 wrong email, 401 bad token), shows an error message.

**`src/components/RequireAuth.tsx`**  
Wrapper component. Reads token from AuthContext; if absent or expired → `<Navigate to="/login" replace />`. Otherwise renders children.

### Modified files

**`main.tsx`**  
Wrap the app tree with `<GoogleOAuthProvider clientId={import.meta.env.VITE_GOOGLE_CLIENT_ID}>` and `<AuthProvider>`.

**`App.tsx`**  
Add a public `/login` route. Wrap all existing routes (under `<Layout>`) with `<RequireAuth>`.

**`src/lib/api.ts`** *(modified)*  
Already exists as a centralized `request()` wrapper. Modify `request()` to read the JWT from `sessionStorage` and inject `Authorization: Bearer <token>` on every request. Intercept 401 responses by calling `logout()` and redirecting to `/login`. No changes needed in individual page components.

**`src/components/Layout.tsx`** *(modified)*  
Add a logout button that calls `logout()` from AuthContext (clears sessionStorage, navigates to `/login`).

---

## Backend

### New packages
- `google-auth` — ID token verification against Google's public keys
- `PyJWT` — issuing and validating our own HS256 JWTs

### Config additions (`app/config.py`)

```python
GOOGLE_CLIENT_ID: str = ""
ALLOWED_EMAIL: str = ""
JWT_SECRET: str = ""
JWT_EXPIRE_HOURS: int = 24
```

### New files

**`app/routers/auth.py`**  
Single endpoint: `POST /auth/login`  
- Accepts `{ id_token: str }`
- Verifies with `google.oauth2.id_token.verify_oauth2_token(id_token, Request(), GOOGLE_CLIENT_ID)`
- Checks `idinfo["email"] == settings.ALLOWED_EMAIL`
- Returns `{ access_token: str, expires_in: int }` (our own JWT, HS256)
- Returns 401 on invalid/expired Google token
- Returns 403 on email mismatch

**`app/middleware/user_auth.py`**  
`require_dashboard_auth` FastAPI dependency.  
- Extracts Bearer token from `Authorization` header
- Decodes and validates our JWT with `PyJWT`
- Raises 401 on missing, expired, or invalid token

### Modified files

**`app/main.py`** (FastAPI app entrypoint)  
- Register `/auth` router with no auth dependency (it's the public login endpoint)
- Add `require_dashboard_auth` as a router-level dependency on all existing routers: `projects`, `features`, `costs`, `prompts`, `schedules`, `activity`
- `/health` endpoint remains public (no auth)
- Bot routes using `require_api_key` are unchanged

---

## Error Handling

| Scenario | Behaviour |
|---|---|
| Google token invalid/expired | Backend 401; frontend shows "Sign-in failed, please try again" |
| Email not in `ALLOWED_EMAIL` | Backend 403; frontend shows "This Google account is not authorized" |
| Dashboard JWT expired | Backend 401 on next API call; frontend clears auth + redirects to `/login` |
| `JWT_SECRET` not set | Backend startup log warning; `/auth/login` returns 500 |
| `GOOGLE_CLIENT_ID` not set | Google Sign-In button fails to render; frontend shows config error |

---

## What Is Not In Scope

- Multi-user support (only one `ALLOWED_EMAIL`)
- Refresh tokens (re-login after 24h is acceptable)
- Role-based access control
- Audit logging of login events
