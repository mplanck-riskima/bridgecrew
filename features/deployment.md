# Deployment Feature

## What it does / problem it solves

Prepares the dashboard for production deployment on Railway. Previously the dashboard only had a dev-oriented Docker setup (docker-compose with volume mounts and hot reload) and no production build pipeline. This feature adds a multi-stage Dockerfile and a `railway.toml` so the full stack (React frontend + FastAPI backend) can be deployed as a single Railway service.

## Key files changed or created

- `dashboard/Dockerfile` — updated from a dev-only backend image to a multi-stage production build: Node 22 Alpine builds the React frontend, Python 3.12 slim serves it via FastAPI. The Vite output is copied to `/app/static/`, which FastAPI already mounts as a static file directory.
- `railway.toml` — new file at repo root; points Railway at the dashboard Dockerfile, sets `/health` as the healthcheck path, and lets Railway inject `$PORT` (uvicorn falls back to 8000).

## Design decisions and tradeoffs

- **Single service, not split frontend/backend**: FastAPI already includes static file serving (`app.mount("/", StaticFiles(...))` in `main.py`). Serving both from one Railway service avoids CORS config and is simpler to manage.
- **Build context is repo root**: The Dockerfile uses `dashboard/frontend/` and `dashboard/backend/` COPY paths, so the build context must be the repo root. This is Railway's default and matches how the existing Dockerfile was already structured.
- **`$PORT` fallback**: Railway injects a `PORT` env var; the CMD uses `${PORT:-8000}` so local `docker build` runs still work without setting the variable.
- **Local dev unaffected**: `docker-compose.yml` uses inline base images with volume mounts — it does not reference the Dockerfile — so dev workflow is unchanged.

## Known limitations / follow-up items

- `ALLOWED_ORIGINS` must be set to the Railway service URL after first deploy, otherwise CORS will block the frontend from calling `/api`.
- No `VITE_API_URL` build arg is needed (frontend calls same-origin `/api`), but if the backend is ever split to a separate service this will need revisiting.
- The Railway service requires `MONGODB_URI` and optionally `BRIDGECREW_API_KEY`, `DISCORD_BOT_TOKEN`, and `DISCORD_GUILD_ID` to be set manually in the Railway environment.
