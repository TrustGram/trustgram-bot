"""
Async SQLAlchemy engine & session factory.

All database access goes through `get_db()` which yields a scoped
`AsyncSession` and commits/rolls-back automatically.

Schema changes are managed by **Alembic** — see ``alembic/`` and run
``alembic upgrade head`` to apply pending migrations.
"""

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings
from app.core.logger import logger


def _normalize_async_url(url: str) -> str:
    """Coerce a sync Postgres URL to the asyncpg driver.

    Render's managed Postgres hands out ``postgres://`` / ``postgresql://``
    connection strings (the psycopg2/sync form). The async engine requires an
    async driver, so rewrite the scheme to ``postgresql+asyncpg://``. SQLite
    and already-async URLs pass through unchanged.
    """
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+asyncpg://" + url[len(prefix) :]
    return url


engine = create_async_engine(
    _normalize_async_url(settings.database_url),
    echo=False,
    future=True,
)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Shared declarative base for every ORM model."""

    pass


async def get_db() -> AsyncSession:  # type: ignore[misc]
    """FastAPI dependency — yields a transactional session."""
    logger.debug("Opening new database session")
    async with async_session_factory() as session:
        try:
            yield session  # type: ignore[misc]
            await session.commit()
            logger.debug("Database session committed")
        except HTTPException:
            # Expected business-level response (e.g. a 404) — roll back the
            # transaction but don't log it as a database failure.
            await session.rollback()
            raise
        except Exception as e:
            logger.error(f"Database session error: {e}")
            await session.rollback()
            logger.info("Database session rolled back")
            raise
