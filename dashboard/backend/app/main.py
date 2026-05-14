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
