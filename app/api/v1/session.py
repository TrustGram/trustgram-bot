"""
Session request endpoints.

POST /session/init     — send a chat initiation request.
GET  /session/pending  — fetch incoming pending requests.
POST /session/accept   — accept a request (removes it from pending).
POST /session/decline  — decline a request (removes it from pending).
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.bot import bot
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import SessionRequest, User
from app.schemas.schemas import (
    PendingSessionsResponse,
    SessionInitRequest,
    SessionPendingItem,
    SessionRespondRequest,
    StatusResponse,
)

router = APIRouter(prefix="/session", tags=["session"])


@router.post(
    "/init",
    response_model=StatusResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send a chat initiation request",
)
async def init_session(
    body: SessionInitRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from_id: int = user["id"]

    # Replace any existing request from the same sender
    stmt = select(SessionRequest).where(
        SessionRequest.from_id == from_id,
        SessionRequest.to_id == body.to_id,
    )
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing:
        await db.delete(existing)

    sender = await db.get(User, from_id)
    from_username = sender.username if sender else None

    db.add(SessionRequest(
        from_id=from_id,
        to_id=body.to_id,
        from_username=from_username,
    ))
    await db.flush()

    sender_name = f"@{from_username}" if from_username else str(from_id)
    try:
        await bot.send_message(
            chat_id=body.to_id,
            text=(
                f"🔐 <b>{sender_name}</b> wants to start an encrypted chat.\n"
                f"Open TrustGram to accept."
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass

    return StatusResponse(detail="Session request sent")


@router.get(
    "/pending",
    response_model=PendingSessionsResponse,
    summary="Get pending incoming session requests",
)
async def get_pending(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    to_id: int = user["id"]
    stmt = (
        select(SessionRequest)
        .where(SessionRequest.to_id == to_id)
        .order_by(SessionRequest.created_at.asc())
    )
    result = await db.execute(stmt)
    requests = result.scalars().all()

    return PendingSessionsResponse(
        requests=[
            SessionPendingItem(
                from_id=r.from_id,
                from_username=r.from_username,
                created_at=r.created_at,
            )
            for r in requests
        ]
    )


@router.post("/accept", response_model=StatusResponse, summary="Accept a session request")
async def accept_session(
    body: SessionRespondRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    to_id: int = user["id"]
    stmt = select(SessionRequest).where(
        SessionRequest.from_id == body.from_id,
        SessionRequest.to_id == to_id,
    )
    result = await db.execute(stmt)
    req = result.scalar_one_or_none()
    if req:
        await db.delete(req)
    return StatusResponse(detail="Session accepted")


@router.post("/decline", response_model=StatusResponse, summary="Decline a session request")
async def decline_session(
    body: SessionRespondRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    to_id: int = user["id"]
    stmt = select(SessionRequest).where(
        SessionRequest.from_id == body.from_id,
        SessionRequest.to_id == to_id,
    )
    result = await db.execute(stmt)
    req = result.scalar_one_or_none()
    if req:
        await db.delete(req)
    return StatusResponse(detail="Session declined")
