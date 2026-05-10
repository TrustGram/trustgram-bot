"""
Shared pytest fixtures for the entire TrustGram test suite.

Strategy
--------
- Each test gets a **fresh in-memory SQLite database** (function scope) so
  tests are fully isolated from each other and from the production DB.
- The aiogram Bot instantiation is patched at import time to avoid token
  validation errors during testing.
- FastAPI dependencies (get_db, get_current_user) are overridden so every
  integration test runs against the in-memory DB and a mock Telegram user.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# ── Patch aiogram Bot BEFORE any app module is imported ──────────────────────
# The Bot validates the token immediately on __init__; we replace the whole
# class with a lightweight AsyncMock so tests never need a real token.
_mock_bot = MagicMock()
_mock_bot.session = MagicMock()
_mock_bot.session.close = AsyncMock()
_mock_bot.set_chat_menu_button = AsyncMock()

_bot_patch = patch("aiogram.Bot", return_value=_mock_bot)
_bot_patch.start()

# Now it's safe to import app code.
from app.core.database import Base, get_db  # noqa: E402
from app.core.security import get_current_user  # noqa: E402
from app.main import app  # noqa: E402

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

# ── Mock user ────────────────────────────────────────────────────────────────

MOCK_USER = {
    "id": 12345678,
    "first_name": "Test",
    "last_name": "User",
    "username": "test_user",
    "language_code": "en",
}


# ── Database fixtures ────────────────────────────────────────────────────────


@pytest.fixture()
async def async_engine():
    """Create a fresh async SQLite engine with all tables for each test."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture()
async def db_session(async_engine):
    """Yield a transactional AsyncSession backed by the in-memory engine."""
    factory = async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


# ── HTTP client fixture ──────────────────────────────────────────────────────


@pytest.fixture()
async def client(db_session):
    """
    AsyncClient wired to the FastAPI app with:
      - get_db  → in-memory session
      - get_current_user → MOCK_USER (no real Telegram initData needed)
    """

    async def _override_get_db():
        try:
            yield db_session
            await db_session.commit()
        except Exception:
            await db_session.rollback()
            raise

    def _override_get_current_user():
        return MOCK_USER

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_current_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
