# Google OAuth Setup

Steps to create the OAuth 2.0 client ID for the dashboard — covers both local dev and the deployed `bridgecrew.riskima.com` instance.

---

## 1. Create a Google Cloud project (skip if you have one)

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Click the project dropdown → **New Project**
3. Name it `BridgeCrew` (or anything you like) → **Create**

---

## 2. Configure the OAuth consent screen

1. In the left sidebar: **APIs & Services → OAuth consent screen**
2. User type: **External** → **Create**
3. Fill in:
   - App name: `BridgeCrew Dashboard`
   - User support email: `planckfamily@gmail.com`
   - Developer contact: `planckfamily@gmail.com`
4. Click **Save and Continue** through Scopes and Test Users (no changes needed)
5. Back on the consent screen, under **Test users**, add `planckfamily@gmail.com`

---

## 3. Create the OAuth 2.0 client ID

1. **APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID**
2. Application type: **Web application**
3. Name: `BridgeCrew Dashboard`
4. **Authorized JavaScript origins** — add both:
   ```
   http://localhost:5173
   https://bridgecrew.riskima.com
   ```
5. **Authorized redirect URIs** — leave empty (the app uses the popup/One Tap flow, not redirects)
6. Click **Create**
7. Copy the **Client ID** — it looks like `123456789-abc....apps.googleusercontent.com`

---

## 4. Set environment variables

### Backend (`dashboard/backend/.env`)

```env
GOOGLE_CLIENT_ID=<your-client-id>.apps.googleusercontent.com
ALLOWED_EMAIL=planckfamily@gmail.com
JWT_SECRET=<generate below>
JWT_EXPIRE_HOURS=24
```

Generate `JWT_SECRET`:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### Frontend — local dev (`dashboard/frontend/.env.local`)

```env
VITE_GOOGLE_CLIENT_ID=<your-client-id>.apps.googleusercontent.com
```

### Frontend — Railway (production)

In the Railway dashboard for your service, add a build-time environment variable:

```
VITE_GOOGLE_CLIENT_ID=<your-client-id>.apps.googleusercontent.com
```

Vite bakes this into the bundle at build time, so it must be set before the build runs.

---

## 5. Verify it works

### Local dev

```bash
# Terminal 1
cd dashboard/backend && uvicorn app.main:app --reload

# Terminal 2
cd dashboard/frontend && npm run dev
```

Open `http://localhost:5173` — you should be redirected to `/login`.

Sign in with `planckfamily@gmail.com` → should land on the dashboard.

### Quick API checks

```bash
# Should return 401
curl http://localhost:8000/api/projects

# Should return 200
curl http://localhost:8000/health

# Should return 200 (replace with your actual API key from .env)
curl -H "Authorization: Bearer <BRIDGECREW_API_KEY>" http://localhost:8000/api/projects
```
