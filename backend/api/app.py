from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router
from infra.http_client import close_client, get_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_client()
    yield
    await close_client()


def _normalize_origin(origin: str) -> str:
    origin = origin.strip().rstrip("/")
    if origin and "://" not in origin:
        origin = f"https://{origin}"
    return origin


def _allowed_origins() -> list[str]:
    # Comma-separated list, e.g. "https://qol-indicator.vercel.app,https://qol.example.com".
    # Defaults to the Vite dev server so local development needs no configuration.
    # Entries are normalized (trailing slash stripped, scheme defaulted to https) since a
    # CORS Origin header is always exactly scheme://host with no path or trailing slash.
    raw = os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173")
    return [_normalize_origin(origin) for origin in raw.split(",") if origin.strip()]


def create_app() -> FastAPI:
    app = FastAPI(title="Quality of Life Indicator", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins(),
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app


app = create_app()
