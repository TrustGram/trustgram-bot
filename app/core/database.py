"""
Async SQLAlchemy engine & session factory.

All database access goes through `get_db()` which yields a scoped
`AsyncSession` and commits/rolls-back automatically.
"""

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings
from app.core.logger import logger

logger.info(f"Connecting to database at: {settings.database_url}")
engine = create_async_engine(
    settings.database_url,
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


async def init_db() -> None:
    """Create tables if they don't exist yet (MVP convenience)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncSession:  # type: ignore[misc]
    """FastAPI dependency — yields a transactional session."""
    logger.debug("Opening new database session")
    async with async_session_factory() as session:
        try:
            yield session  # type: ignore[misc]
            await session.commit()
            logger.debug("Database session committed")
        except Exception as e:
            logger.error(f"Database session error: {e}")
            await session.rollback()
            logger.info("Database session rolled back")
            raise
