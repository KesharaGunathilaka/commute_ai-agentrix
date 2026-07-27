"""FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from commute_agent.api.routes import router
from commute_agent.core.config import get_settings
from commute_agent.core.logging import get_logger, setup_logging

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info("Commute Agent API starting up (env=%s)", get_settings().app_env)
    yield
    logger.info("Commute Agent API shutting down.")


app = FastAPI(
    title="Disruption-Aware Commute Agent",
    description="Sri Lanka Railways multilingual commute assistant — AGENTRIX 2026 Team 23",
    version="0.1.0",
    lifespan=lifespan,
)

# The Next.js frontend is served from a different origin (:3000) than the API
# (:8000), so the browser blocks its requests without this. Origins come from
# the CORS_ORIGINS env var — never "*", since credentials may be added later
# and a wildcard would silently stop working at that point.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


if __name__ == "__main__":
    import uvicorn
    settings = get_settings()
    uvicorn.run("commute_agent.api.main:app", host=settings.api_host, port=settings.api_port, reload=True)
