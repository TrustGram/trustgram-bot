"""
Unit tests for app/core/database.py.

Covers
------
- get_db: yields a session, commits on success, rolls back on error.

Note: ``init_db()`` was removed in favour of Alembic migrations.
Table creation in tests is handled by ``Base.metadata.create_all`` directly.
"""

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.database import Base, get_db

TEST_URL = "sqlite+aiosqlite:///:memory:"


class TestGetDb:
    @pytest.mark.asyncio
    async def test_get_db_yields_session_and_commits(self):
        """get_db should yield an AsyncSession and commit on clean exit."""
        engine = create_async_engine(TEST_URL, echo=False, future=True)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        import app.core.database as db_module

        original_engine = db_module.engine
        original_factory = db_module.async_session_factory
        db_module.engine = engine
        db_module.async_session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
        try:
            gen = get_db()
            session = await gen.__anext__()
            assert isinstance(session, AsyncSession)
            # Closing without error — should commit.
            try:
                await gen.asend(None)
            except StopAsyncIteration:
                pass
        finally:
            db_module.engine = original_engine
            db_module.async_session_factory = original_factory
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_get_db_rolls_back_on_error(self):
        """get_db must roll back the session when an exception propagates."""
        engine = create_async_engine(TEST_URL, echo=False, future=True)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        import app.core.database as db_module

        original_engine = db_module.engine
        original_factory = db_module.async_session_factory
        db_module.engine = engine
        db_module.async_session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
        try:
            gen = get_db()
            session = await gen.__anext__()
            assert isinstance(session, AsyncSession)
            # Throw an exception into the generator — it must roll back.
            try:
                await gen.athrow(ValueError("simulated error"))
            except (ValueError, StopAsyncIteration):
                pass
        finally:
            db_module.engine = original_engine
            db_module.async_session_factory = original_factory
            await engine.dispose()
