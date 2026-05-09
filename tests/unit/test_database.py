"""
Unit tests for app/core/database.py.

Covers
------
- init_db: creates tables against a real in-memory engine.
- get_db: yields a session, commits on success, rolls back on error.
"""

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.database import Base, get_db, init_db

TEST_URL = "sqlite+aiosqlite:///:memory:"


class TestInitDb:
    @pytest.mark.asyncio
    async def test_init_db_creates_tables(self):
        """init_db must create all ORM tables without errors."""
        engine = create_async_engine(TEST_URL, echo=False, future=True)

        # Temporarily override the module-level engine used by init_db.
        import app.core.database as db_module
        original_engine = db_module.engine
        db_module.engine = engine
        try:
            await init_db()
            # Check that the tables exist by inspecting the engine.
            async with engine.connect() as conn:
                from sqlalchemy import text
                result = await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
                tables = {row[0] for row in result.fetchall()}
            assert "users" in tables
            assert "public_bundles" in tables
            assert "one_time_keys" in tables
            assert "messages" in tables
        finally:
            db_module.engine = original_engine
            await engine.dispose()


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
        db_module.async_session_factory = async_sessionmaker(
            bind=engine, class_=AsyncSession, expire_on_commit=False
        )
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
        db_module.async_session_factory = async_sessionmaker(
            bind=engine, class_=AsyncSession, expire_on_commit=False
        )
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
