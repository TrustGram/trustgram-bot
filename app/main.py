"""
TrustGram — FastAPI application entry point.

Wires together:
  • Database lifecycle (create tables on startup)
  • API v1 routers  (keys + chat)
  • Telegram webhook endpoint
  • aiogram bot lifecycle

Start locally with:
    uvicorn app.main:app --reload
"""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html

from aiogram import types as aio_types

from app.api.v1.router import router as api_v1_router
from app.bot.bot import bot, dp, on_shutdown, on_startup
from app.core.config import settings
from app.core.database import init_db
from app.core.logger import setup_logging, logger

# Initialize logging as early as possible
setup_logging()


# ── Lifespan ──────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Modern lifespan handler (replaces deprecated on_event)."""
    logger.info("Application starting up...")
    try:
        await init_db()
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise

    await on_startup()
    logger.info("Bot startup tasks completed.")
    yield
    logger.info("Application shutting down...")
    await on_shutdown()
    logger.info("Shutdown sequence complete.")


# ── Application ───────────────────────────────────────────────

app = FastAPI(
    title=settings.project_name,
    version="0.1.0",
    description=(
        "Zero-trust key server and encrypted message relay for TrustGram. "
        "All encryption happens client-side; the server never sees plaintext."
    ),
    lifespan=lifespan,
    # Disable default doc routes — re-exposed with access control below.
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


# ── Health check ──────────────────────────────────────────────

@app.get("/health", tags=["meta"])
async def health_check():
    """Simple liveness probe for Render / load-balancer."""
    logger.debug("Health check requested")
    return {"status": "ok", "service": settings.project_name}


# ── API v1 ────────────────────────────────────────────────────

app.include_router(api_v1_router, prefix=settings.api_v1_prefix)


# ── Telegram webhook ─────────────────────────────────────────

@app.post("/webhook", include_in_schema=False)
async def telegram_webhook(request: Request):
    """
    Receives Telegram updates via webhook and feeds them into
    the aiogram dispatcher.
    """
    data = await request.json()
    update = aio_types.Update(**data)
    await dp.feed_update(bot, update)
    return {"ok": True}


# ── Docs access control ───────────────────────────────────────

def _require_docs_access(
    x_docs_key: str | None = Header(default=None),
) -> None:
    """
    Dependency that gates /docs, /redoc, and /openapi.json.

    Behaviour by environment:
      - development : no key required — always allowed.
      - production  : ``X-Docs-Key`` header must match ``DOCS_API_KEY``.
                      Returns 404 (not 401) so the path looks non-existent
                      to automated scanners.
    """
    if settings.environment == "production":
        if not settings.docs_api_key or x_docs_key != settings.docs_api_key:
            raise HTTPException(status_code=404, detail="Not found")


@app.get("/docs", include_in_schema=False, dependencies=[Depends(_require_docs_access)])
async def swagger_ui():
    """Swagger UI — requires ``X-Docs-Key`` header in production."""
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title=f"{settings.project_name} — Swagger UI",
    )


@app.get("/redoc", include_in_schema=False, dependencies=[Depends(_require_docs_access)])
async def redoc_ui():
    """ReDoc — requires ``X-Docs-Key`` header in production."""
    return get_redoc_html(
        openapi_url="/openapi.json",
        title=f"{settings.project_name} — ReDoc",
    )


@app.get("/openapi.json", include_in_schema=False, dependencies=[Depends(_require_docs_access)])
async def openapi_schema():
    """Raw OpenAPI schema — requires ``X-Docs-Key`` header in production."""
    return app.openapi()
