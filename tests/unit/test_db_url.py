"""Unit tests for database URL normalization (app/core/database._normalize_async_url)."""

import pytest

from app.core.database import _normalize_async_url


@pytest.mark.parametrize(
    "raw, expected",
    [
        # Render hands out postgres:// or postgresql:// (sync) — both must be
        # rewritten to the asyncpg driver.
        (
            "postgres://u:p@host:5432/db",
            "postgresql+asyncpg://u:p@host:5432/db",
        ),
        (
            "postgresql://u:p@host:5432/db",
            "postgresql+asyncpg://u:p@host:5432/db",
        ),
        # Already-async and SQLite URLs pass through untouched.
        (
            "postgresql+asyncpg://u:p@host/db",
            "postgresql+asyncpg://u:p@host/db",
        ),
        (
            "sqlite+aiosqlite:///./trustgram.db",
            "sqlite+aiosqlite:///./trustgram.db",
        ),
    ],
)
def test_normalize_async_url(raw, expected):
    assert _normalize_async_url(raw) == expected
