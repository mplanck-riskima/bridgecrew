"""FastAPI application — monitoring dashboard backend."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routers import activity, costs, features, projects, prompts, schedules

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


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
    """Health check endpoint."""
    return {"status": "ok"}

# API routers
app.include_router(projects.router, prefix="/api")
app.include_router(features.router, prefix="/api")
app.include_router(costs.router, prefix="/api")
app.include_router(prompts.router, prefix="/api")
app.include_router(schedules.router, prefix="/api")
app.include_router(activity.router, prefix="/api")

# Serve frontend static files in production
if STATIC_DIR.exists():
    # Serve Vite assets directly (JS, CSS, images, etc.)
    assets_dir = STATIC_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    # Catch-all: serve index.html for any non-API path (SPA client-side routing)
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str) -> FileResponse:
        file_path = STATIC_DIR / full_path
        if file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(STATIC_DIR / "index.html"))
