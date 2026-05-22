"""
TrustGram — FastAPI application entry point.

Wires together:
  • API v1 routers  (keys + chat)
  • Telegram webhook endpoint
  • aiogram bot lifecycle

Schema migrations are managed by Alembic and run automatically
before the server starts (see Dockerfile / render.yaml).

Start locally with:
    alembic upgrade head && uvicorn app.main:app --reload
"""

import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path

from aiogram import types as aio_types
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.v1.router import router as api_v1_router
from app.bot.bot import bot, dp, on_shutdown, on_startup
from app.core.cleanup import inbox_cleanup_loop
from app.core.config import settings
from app.core.database import Base, engine
from app.core.logger import logger, setup_logging
from app.core.rate_limit import limiter

# Initialize logging as early as possible
setup_logging()

# ── Version ───────────────────────────────────────────────────

_VERSION_FILE = Path(__file__).resolve().parent.parent / "VERSION"
__version__ = _VERSION_FILE.read_text(encoding="utf-8").strip() if _VERSION_FILE.exists() else "0.0.0-dev"


# ── Lifespan ──────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Modern lifespan handler (replaces deprecated on_event)."""
    logger.info("Application starting up...")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database schema ensured.")

    await on_startup()
    logger.info("Bot startup tasks completed.")

    cleanup_stop = asyncio.Event()
    cleanup_task = asyncio.create_task(inbox_cleanup_loop(cleanup_stop))

    yield

    logger.info("Application shutting down...")
    cleanup_stop.set()
    try:
        await asyncio.wait_for(cleanup_task, timeout=5)
    except asyncio.TimeoutError:
        logger.warning("Inbox cleanup task did not stop within 5s; cancelling")
        cleanup_task.cancel()
    await on_shutdown()
    logger.info("Shutdown sequence complete.")


# ── Application ───────────────────────────────────────────────

app = FastAPI(
    title=settings.project_name,
    version=__version__,
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


# ── Rate limiting ────────────────────────────────────────────
# Per-route enforcement is done by the @limiter.limit decorator. We deliberately
# do NOT register SlowAPIMiddleware: when it raises RateLimitExceeded it bypasses
# the ExceptionMiddleware (and therefore the registered handler), so the 429
# response never goes through CORSMiddleware and the browser sees a CORS error
# instead of the rate-limit JSON.

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ── Catch-all exception handler ──────────────────────────────
# Without this, uncaught exceptions are handled by ServerErrorMiddleware, which
# sits OUTSIDE the user-added CORSMiddleware. The resulting 500 response never
# picks up CORS headers, so the browser reports a CORS error and swallows the
# real cause. Registering a handler hooks into ExceptionMiddleware (inside CORS),
# letting the 500 response flow back through CORSMiddleware as it should.


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={"detail": f"{type(exc).__name__}: {exc}"},
    )


# ── CORS ─────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_origin_regex,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health check ──────────────────────────────────────────────


@app.get("/health", tags=["meta"])
async def health_check():
    """Simple liveness probe for Render / load-balancer."""
    logger.debug("Health check requested")
    return {"status": "ok", "service": settings.project_name, "version": __version__}


# ── API v1 ────────────────────────────────────────────────────

app.include_router(api_v1_router, prefix=settings.api_v1_prefix)


# ── Telegram webhook ─────────────────────────────────────────

# Throttle the bad-secret log: under sustained scanning we'd otherwise emit a
# WARNING per request. First N per minute stay at WARNING (still actionable),
# the rest drop to DEBUG. Per-process state — multi-worker is fine, each
# worker independently lets a few through.
_WEBHOOK_WARN_WINDOW_S = 60
_WEBHOOK_WARN_THRESHOLD = 3
_webhook_bad_token_window_start = 0.0
_webhook_bad_token_count = 0


def _log_webhook_bad_token() -> None:
    global _webhook_bad_token_window_start, _webhook_bad_token_count
    now = time.monotonic()
    if now - _webhook_bad_token_window_start > _WEBHOOK_WARN_WINDOW_S:
        _webhook_bad_token_window_start = now
        _webhook_bad_token_count = 0
    _webhook_bad_token_count += 1
    if _webhook_bad_token_count <= _WEBHOOK_WARN_THRESHOLD:
        logger.warning("Webhook called with missing/invalid secret token")
    else:
        logger.debug(
            "Webhook bad token (suppressed): %d hits in last %ds",
            _webhook_bad_token_count,
            _WEBHOOK_WARN_WINDOW_S,
        )


@app.post("/webhook", include_in_schema=False)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    """
    Receives Telegram updates via webhook and feeds them into
    the aiogram dispatcher.

    Telegram signs each delivery with the secret-token header we configured via
    setWebhook. When ``telegram_webhook_secret`` is set, mismatched requests are
    rejected as 404 (not 401) so the route looks non-existent to attackers.
    """
    expected = settings.telegram_webhook_secret
    if expected and x_telegram_bot_api_secret_token != expected:
        _log_webhook_bad_token()
        raise HTTPException(status_code=404, detail="Not found")

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
