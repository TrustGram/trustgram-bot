"""
Chat / messaging endpoints — encrypted blob relay.

POST   /chat/send          — upload an encrypted payload for a recipient.
GET    /chat/inbox          — fetch all pending encrypted messages.
DELETE /chat/message/{id}   — acknowledge & delete a consumed message.
"""

import time
from datetime import datetime, timezone

from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.bot import bot
from app.core.database import get_db
from app.core.logger import logger
from app.core.rate_limit import limiter
from app.core.security import get_current_user
from app.models.models import Message, User
from app.schemas.schemas import (
    InboxResponse,
    MessageResponse,
    SendMessageRequest,
    StatusResponse,
)

router = APIRouter(prefix="/chat", tags=["chat"])

# In-process notification throttle. Maps (sender_id, recipient_id) → last-sent
# epoch seconds. Multi-worker deployments will throttle per-worker — good
# enough for now (worst case is N notifications per N workers per window).
_NOTIFY_COOLDOWN_SECONDS = 60
_last_notified: dict[tuple[int, int], float] = {}


def _should_notify(sender_id: int, recipient_id: int) -> bool:
    """True if we haven't pinged this recipient on behalf of this sender in the last minute."""
    key = (sender_id, recipient_id)
    now = time.monotonic()
    last = _last_notified.get(key, 0.0)
    if now - last < _NOTIFY_COOLDOWN_SECONDS:
        return False
    _last_notified[key] = now
    return True


@router.post(
    "/send",
    response_model=StatusResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send an encrypted message",
)
@limiter.limit("60/minute")
async def send_message(
    request: Request,
    body: SendMessageRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Alice sends an opaque encrypted payload to Bob's inbox.
    The server stores it and (in the future) triggers a Telegram notification.
    """
    sender_id: int = user["id"]

    db.add(
        Message(
            recipient_id=body.recipient_id,
            sender_id=sender_id,
            encrypted_payload=body.encrypted_payload,
        )
    )
    await db.flush()

    # Metadata-minimal log: don't write the (sender, recipient) pair anywhere.
    # The communication graph is exactly what an adversary with disk access
    # would want; a per-message-relay counter is enough for ops.
    logger.info("Message relayed")

    if _should_notify(sender_id, body.recipient_id):
        sender = await db.get(User, sender_id)
        sender_name = f"@{sender.username}" if sender and sender.username else str(sender_id)
        try:
            await bot.send_message(
                chat_id=body.recipient_id,
                text=f"🔒 New encrypted message from {sender_name}\n\nOpen TrustGram to read it.",
            )
        except TelegramForbiddenError:
            # Recipient hasn't started the bot or has blocked it — expected, ignore.
            logger.debug("Notification skipped: recipient has not started the bot")
        except TelegramAPIError as e:
            # Real Telegram error — surface for debugging but never fail the send.
            logger.warning("Telegram notification failed: %s", e)

    return StatusResponse(detail="Message delivered to inbox")


@router.get(
    "/inbox",
    response_model=InboxResponse,
    summary="Fetch pending messages",
)
@limiter.limit("120/minute")
async def get_inbox(
    request: Request,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Return all encrypted blobs waiting in the current user's inbox.
    The client is expected to call ``DELETE /chat/message/{id}`` after
    successfully decrypting each one.
    """
    telegram_id: int = user["id"]

    stmt = (
        select(Message, User.username)
        .outerjoin(User, Message.sender_id == User.telegram_id)
        .where(Message.recipient_id == telegram_id)
        .order_by(Message.timestamp.asc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    # Stamp first_fetched_at so the cleanup sweeper can short-TTL these rows.
    # Idempotent — only updates rows where the column is still NULL, so a
    # poll/retry from the same client doesn't reset the clock. The UPDATE
    # runs in the same transaction as the read; if the response never makes
    # it to the client they'll just see the same messages next time (and
    # those messages will already be stamped, which is harmless — the short
    # TTL only fires when the cleanup sweep runs ~1 hour later).
    if rows:
        await db.execute(
            update(Message)
            .where(
                Message.recipient_id == telegram_id,
                Message.first_fetched_at.is_(None),
            )
            .values(first_fetched_at=datetime.now(timezone.utc))
        )

    logger.debug(f"User {telegram_id} fetched inbox: {len(rows)} messages")
    return InboxResponse(
        messages=[
            MessageResponse(
                id=m.id,
                sender_id=m.sender_id,
                sender_username=username,
                encrypted_payload=m.encrypted_payload,
                timestamp=m.timestamp,
            )
            for m, username in rows
        ]
    )


@router.delete(
    "/message/{message_id}",
    response_model=StatusResponse,
    summary="Acknowledge & delete a message",
)
@limiter.limit("300/minute")
async def delete_message(
    request: Request,
    message_id: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    The client calls this after successfully decrypting a message,
    confirming the server can discard it.
    """
    telegram_id: int = user["id"]

    msg = await db.get(Message, message_id)
    if not msg:
        logger.warning(f"Delete requested for non-existent message: {message_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found",
        )

    if msg.recipient_id != telegram_id:
        # Counter-attack signal, not an operational error — keep at debug so we
        # don't accumulate a who-tried-to-delete-whose-message graph in prod logs.
        logger.debug("Unauthorized delete attempt: msg=%s requester=%s", message_id, telegram_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found",
        )

    await db.delete(msg)
    logger.info(f"Message {message_id} acknowledged and deleted by {telegram_id}")
    return StatusResponse(detail="Message deleted")
