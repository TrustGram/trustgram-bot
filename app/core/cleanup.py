"""
Background cleanup of undelivered messages.

A message stays in the recipient's inbox until they call DELETE /message/{id}
after decrypting it. If a recipient never opens TrustGram, their inbox would
grow forever. We expire anything older than INBOX_TTL_DAYS to bound storage.

Run as a background asyncio task started in the FastAPI lifespan. Survives
single-iteration failures (logged + retried on next tick).
"""

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from app.core.database import async_session_factory
from app.core.logger import logger
from app.models.models import Message

# How long an undelivered message lives. Picked to cover users who open the app
# infrequently but still bound storage for ones who never come back.
INBOX_TTL_DAYS = 30
# How often the sweeper runs. An hour is plenty — TTL is measured in days.
SWEEP_INTERVAL_SECONDS = 3600


async def _sweep_once() -> int:
    """Delete messages older than the TTL. Returns the row-count deleted."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=INBOX_TTL_DAYS)
    async with async_session_factory() as session:
        result = await session.execute(delete(Message).where(Message.timestamp < cutoff))
        await session.commit()
        return result.rowcount or 0


async def inbox_cleanup_loop(stop_event: asyncio.Event) -> None:
    """Sweep forever until `stop_event` is set."""
    logger.info("Inbox cleanup loop started (ttl=%dd, interval=%ds)", INBOX_TTL_DAYS, SWEEP_INTERVAL_SECONDS)
    while not stop_event.is_set():
        try:
            deleted = await _sweep_once()
            if deleted:
                logger.info("Inbox cleanup: deleted %d expired message(s)", deleted)
            else:
                logger.debug("Inbox cleanup: nothing expired")
        except Exception:
            logger.exception("Inbox cleanup sweep failed; will retry next tick")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=SWEEP_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass  # normal — tick elapsed
    logger.info("Inbox cleanup loop stopped")
