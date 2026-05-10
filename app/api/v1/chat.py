"""
Chat / messaging endpoints — encrypted blob relay.

POST   /chat/send          — upload an encrypted payload for a recipient.
GET    /chat/inbox          — fetch all pending encrypted messages.
DELETE /chat/message/{id}   — acknowledge & delete a consumed message.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.logger import logger
from app.core.security import get_current_user
from app.models.models import Message
from app.schemas.schemas import (
    InboxResponse,
    MessageResponse,
    SendMessageRequest,
    StatusResponse,
)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post(
    "/send",
    response_model=StatusResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send an encrypted message",
)
async def send_message(
    body: SendMessageRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Alice sends an opaque encrypted payload to Bob's inbox.
    The server stores it and (in the future) triggers a Telegram notification.
    """
    sender_id: int = user["id"]

    db.add(Message(
        recipient_id=body.recipient_id,
        sender_id=sender_id,
        encrypted_payload=body.encrypted_payload,
    ))

    logger.info(f"Message relay: {sender_id} -> {body.recipient_id}")
    # TODO: send Telegram notification to recipient via aiogram bot instance.

    return StatusResponse(detail="Message delivered to inbox")


@router.get(
    "/inbox",
    response_model=InboxResponse,
    summary="Fetch pending messages",
)
async def get_inbox(
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
        select(Message)
        .where(Message.recipient_id == telegram_id)
        .order_by(Message.timestamp.asc())
    )
    result = await db.execute(stmt)
    messages = result.scalars().all()

    logger.debug(f"User {telegram_id} fetched inbox: {len(messages)} messages")
    return InboxResponse(
        messages=[
            MessageResponse(
                id=m.id,
                sender_id=m.sender_id,
                encrypted_payload=m.encrypted_payload,
                timestamp=m.timestamp,
            )
            for m in messages
        ]
    )


@router.delete(
    "/message/{message_id}",
    response_model=StatusResponse,
    summary="Acknowledge & delete a message",
)
async def delete_message(
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
        logger.error(f"Unauthorized delete attempt: User {telegram_id} tried to delete message {message_id} belonging to {msg.recipient_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found",
        )

    await db.delete(msg)
    logger.info(f"Message {message_id} acknowledged and deleted by {telegram_id}")
    return StatusResponse(detail="Message deleted")
