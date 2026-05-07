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

from fastapi import FastAPI, Request

from aiogram import types as aio_types

from app.api.v1.router import router as api_v1_router
from app.bot.bot import bot, dp, on_shutdown, on_startup
from app.core.config import settings
from app.core.database import init_db


# ── Lifespan ──────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Modern lifespan handler (replaces deprecated on_event)."""
    await init_db()
    await on_startup()
    yield
    await on_shutdown()


# ── Application ───────────────────────────────────────────────

app = FastAPI(
    title=settings.project_name,
    version="0.1.0",
    description=(
        "Zero-trust key server and encrypted message relay for TrustGram. "
        "All encryption happens client-side; the server never sees plaintext."
    ),
    lifespan=lifespan,
)


# ── Health check ──────────────────────────────────────────────

@app.get("/health", tags=["meta"])
async def health_check():
    """Simple liveness probe for Render / load-balancer."""
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
