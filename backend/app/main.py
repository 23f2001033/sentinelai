from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .db import SessionLocal, init_db
from .routers import agents, approvals, policies, runs, telemetry
from .seed import seed_defaults

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    async with SessionLocal() as session:
        await seed_defaults(session)
    yield


settings = get_settings()

app = FastAPI(
    title="SentinelAI",
    version="1.0.0",
    summary="Governance layer for AI employees that operate real software.",
    description=(
        "SentinelAI plans browser actions with Claude, checks each one against a policy "
        "engine, pauses risky steps for human approval, and writes an immutable audit "
        "trail of everything the agent did and why."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(policies.router)
app.include_router(agents.router)
app.include_router(runs.router)
app.include_router(approvals.router)
app.include_router(telemetry.router)

app.mount("/demo", StaticFiles(directory=STATIC_DIR / "demo", html=True), name="demo")


@app.get("/api/health", tags=["meta"])
async def health() -> dict[str, object]:
    from .operator.providers import ProviderError, resolve_provider

    try:
        provider = resolve_provider(settings)
    except ProviderError as exc:
        return {"status": "ok", "planner_configured": False, "planner_error": str(exc)}

    return {
        "status": "ok",
        "planner_provider": provider.label,
        "planner_model": provider.model,
        "planner_configured": provider.configured,
        "planner_signup_url": "" if provider.configured else provider.signup,
    }


SPA_DIR = STATIC_DIR / "app"
SPA_INDEX = SPA_DIR / "index.html"

if SPA_INDEX.exists():
    app.mount("/app/assets", StaticFiles(directory=SPA_DIR / "assets"), name="spa-assets")

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse("/app/")

    @app.get("/app/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        """Serve the dashboard shell so client-side routes survive a refresh."""
        candidate = (SPA_DIR / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(SPA_DIR.resolve()):
            return FileResponse(candidate)
        return FileResponse(SPA_INDEX)
