# oauth-dashboard

**Started:** 2026-05-17  
**Completed:** 2026-05-20  
**Cost:** $0.0000

## Summary

Locked the monitoring dashboard behind Google OAuth with a JWT-based auth layer. Users see a login page with a Google Sign-In button; the backend verifies the Google ID token, checks the email against ALLOWED_EMAILS (comma-separated env var, supporting multiple users), and issues a short-lived HS256 JWT. The React frontend stores the JWT in sessionStorage via AuthContext and injects it as a Bearer token on every API request; a 401 response clears auth state and redirects to /login. Key files added: dashboard/frontend/src/context/AuthContext.tsx, src/pages/Login.tsx, src/components/RequireAuth.tsx; modified: main.tsx (GoogleOAuthProvider + AuthProvider wrap), App.tsx (RequireAuth guard on all routes), src/lib/api.ts (token injection + 401 handling), src/components/Layout.tsx (logout button). Backend: dashboard/app/routers/auth.py (POST /auth/login endpoint), dashboard/app/middleware/user_auth.py (require_dashboard_auth dependency applied to all dashboard routers), dashboard/app/config.py (GOOGLE_CLIENT_ID, ALLOWED_EMAILS, JWT_SECRET, JWT_EXPIRE_HOURS). New packages: google-auth, PyJWT, @react-oauth/google. VITE_GOOGLE_CLIENT_ID is baked into the frontend bundle as a Docker build arg. Bot-to-API routes using BRIDGECREW_API_KEY remain unaffected.
