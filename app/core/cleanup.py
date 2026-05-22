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

from sqlalchemy import delete, or_

from app.core.database import async_session_factory
from app.core.logger import logger
from app.models.models import Message

# How long an UNDELIVERED message lives. Picked to cover users who open the
# app infrequently but still bound storage for ones who never come back.
INBOX_TTL_DAYS = 30
# Short TTL applied AFTER a message has been delivered to the recipient at
# least once (GET /chat/inbox stamps first_fetched_at). One hour is enough
# for a normal client to decrypt + call DELETE, and small enough that crash-
# leftover messages don't linger forensically.
POST_FETCH_TTL_MINUTES = 60
# How often the sweeper runs. Aligned to the post-fetch TTL so a message
# can sit at most ~POST_FETCH_TTL + SWEEP_INTERVAL past delivery before purge.
SWEEP_INTERVAL_SECONDS = 3600


async def _sweep_once() -> int:
    """Delete expired messages. Returns the row-count deleted.

    Two TTL paths run in a single DELETE:
      - Never-fetched rows expire INBOX_TTL_DAYS after they were stored.
      - Fetched rows expire POST_FETCH_TTL_MINUTES after first_fetched_at.
    """
    now = datetime.now(timezone.utc)
    long_cutoff = now - timedelta(days=INBOX_TTL_DAYS)
    short_cutoff = now - timedelta(minutes=POST_FETCH_TTL_MINUTES)
    async with async_session_factory() as session:
        result = await session.execute(
            delete(Message).where(
                or_(
                    # Never delivered — long TTL.
                    Message.timestamp < long_cutoff,
                    # Delivered at least once — short TTL.
                    Message.first_fetched_at < short_cutoff,
                )
            )
        )
        await session.commit()
        return result.rowcount or 0


async def inbox_cleanup_loop(stop_event: asyncio.Event) -> None:
    """Sweep forever until `stop_event` is set."""
    logger.info(
        "Inbox cleanup loop started (long_ttl=%dd, post_fetch_ttl=%dmin, interval=%ds)",
        INBOX_TTL_DAYS,
        POST_FETCH_TTL_MINUTES,
        SWEEP_INTERVAL_SECONDS,
    )
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
