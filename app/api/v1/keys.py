"""
Key management endpoints — X3DH public bundle CRUD.

POST /keys/register   — upload identity key, signed pre-key, signature + OTKs.
GET  /keys/{tg_id}    — fetch a user's public bundle (+ consume one OTK).
POST /keys/otk        — refill one-time pre-keys.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.logger import logger
from app.core.security import get_current_user
from app.models.models import OneTimeKey, PublicBundle, User
from app.schemas.schemas import (
    OneTimeKeySchema,
    PublicBundleResponse,
    RefillOTKRequest,
    RegisterBundleRequest,
    StatusResponse,
)

router = APIRouter(prefix="/keys", tags=["keys"])


@router.post(
    "/register",
    response_model=StatusResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register public key bundle",
)
async def register_bundle(
    body: RegisterBundleRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    First-time registration: upload identity key, signed pre-key,
    the signature, and an initial batch of one-time pre-keys.

    If the user already exists, the bundle is replaced (key rotation).
    """
    telegram_id: int = user["id"]

    # Upsert user row.
    existing_user = await db.get(User, telegram_id)
    if not existing_user:
        logger.info(f"New user registration: {telegram_id}")
        raw_username = user.get("username")
        db.add(User(
            telegram_id=telegram_id,
            username=raw_username.lower() if raw_username else None,
        ))
    else:
        logger.debug(f"Updating keys for existing user: {telegram_id}")

    # Upsert public bundle.
    stmt = select(PublicBundle).where(PublicBundle.user_id == telegram_id)
    result = await db.execute(stmt)
    bundle = result.scalar_one_or_none()

    if bundle:
        bundle.identity_key = body.identity_key
        bundle.signed_pre_key = body.signed_pre_key
        bundle.signature = body.signature
    else:
        db.add(
            PublicBundle(
                user_id=telegram_id,
                identity_key=body.identity_key,
                signed_pre_key=body.signed_pre_key,
                signature=body.signature,
            )
        )

    # Store one-time pre-keys.
    for otk in body.one_time_keys:
        db.add(
            OneTimeKey(
                user_id=telegram_id,
                key_id=otk.key_id,
                public_key=otk.public_key,
            )
        )

    logger.info(f"Bundle registered for {telegram_id} with {len(body.one_time_keys)} OTKs")
    return StatusResponse(detail="Bundle registered")


@router.get(
    "/by-username/{username}",
    response_model=PublicBundleResponse,
    summary="Fetch a user's public bundle by username",
)
async def get_bundle_by_username(
    username: str,
    _user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    username = username.lstrip("@").lower()
    stmt = select(User).where(User.username == username)
    result = await db.execute(stmt)
    found_user = result.scalar_one_or_none()

    if not found_user:
        logger.warning(f"Key bundle requested for unknown username: {username}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    return await get_bundle(found_user.telegram_id, _user, db)


@router.get(
    "/{telegram_id}",
    response_model=PublicBundleResponse,
    summary="Fetch a user's public bundle",
)
async def get_bundle(
    telegram_id: int,
    _user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Return the target user's identity key, signed pre-key, signature,
    and — if available — **one** one-time pre-key (consumed from the pool).

    This is what Alice calls before initiating an X3DH session with Bob.
    """
    stmt = select(PublicBundle).where(PublicBundle.user_id == telegram_id)
    result = await db.execute(stmt)
    bundle = result.scalar_one_or_none()

    if not bundle:
        logger.warning(f"Key bundle requested for unknown user: {telegram_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User has no registered bundle",
        )

    # Pop one OTK (first-come, first-served).
    otk_stmt = select(OneTimeKey).where(OneTimeKey.user_id == telegram_id).limit(1)
    otk_result = await db.execute(otk_stmt)
    otk = otk_result.scalar_one_or_none()

    otk_out: OneTimeKeySchema | None = None
    if otk:
        logger.debug(f"Consuming OTK {otk.key_id} for user {telegram_id}")
        otk_out = OneTimeKeySchema(key_id=otk.key_id, public_key=otk.public_key)
        await db.delete(otk)
    else:
        logger.warning(f"User {telegram_id} has exhausted all One-Time Keys!")

    return PublicBundleResponse(
        telegram_id=telegram_id,
        identity_key=bundle.identity_key,
        signed_pre_key=bundle.signed_pre_key,
        signature=bundle.signature,
        one_time_key=otk_out,
    )


@router.post(
    "/otk",
    response_model=StatusResponse,
    summary="Refill one-time pre-keys",
)
async def refill_otk(
    body: RefillOTKRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    The client calls this when its local OTK counter runs low.
    Appends new keys to the server-side pool.
    """
    telegram_id: int = user["id"]

    for otk in body.one_time_keys:
        db.add(
            OneTimeKey(
                user_id=telegram_id,
                key_id=otk.key_id,
                public_key=otk.public_key,
            )
        )

    logger.info(f"User {telegram_id} refilled {len(body.one_time_keys)} OTKs")
    return StatusResponse(detail=f"Added {len(body.one_time_keys)} one-time keys")
