"""
Key management endpoints — X3DH public bundle CRUD.

POST /keys/register   — upload identity key, signed pre-key, signature + OTKs.
GET  /keys/{tg_id}    — fetch a user's public bundle (+ consume one OTK).
POST /keys/otk        — refill one-time pre-keys.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.logger import logger
from app.core.rate_limit import limiter
from app.core.security import get_current_user
from app.core.spk_verify import verify_spk_signature
from app.models.models import OneTimeKey, PublicBundle, User
from app.schemas.schemas import (
    OneTimeKeySchema,
    OTKCountResponse,
    PublicBundleResponse,
    RefillOTKRequest,
    RegisterBundleRequest,
    StatusResponse,
    UpdateSPKRequest,
)

router = APIRouter(prefix="/keys", tags=["keys"])


@router.post(
    "/register",
    response_model=StatusResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register public key bundle",
)
@limiter.limit("20/hour")
async def register_bundle(
    request: Request,
    body: RegisterBundleRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    First-time registration: upload identity key, signed pre-key,
    the signature, and an initial batch of one-time pre-keys.

    If the user already exists, the bundle is replaced (key rotation).

    Atomicity: the whole endpoint runs inside one transaction held by
    `get_db()`. Any exception (including an inserted-OTK conflict) rolls back
    the user upsert, bundle upsert, OTK deletion, and OTK inserts together —
    a partial state (bundle without OTKs, etc.) cannot be observed by readers.
    """
    telegram_id: int = user["id"]

    # Defence-in-depth: receivers re-verify, but rejecting bad signatures here
    # keeps the OTK pool and storage clean.
    if not verify_spk_signature(body.signing_key, body.signed_pre_key, body.signature):
        logger.warning(f"Bundle rejected for {telegram_id}: invalid SPK signature")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid SPK signature",
        )

    # Upsert user row. Username is stored with its original case for display;
    # lookups are case-insensitive (see get_bundle_by_username).
    raw_username = user.get("username")
    # Telegram caps usernames at 32 chars. Defensively reject anything larger
    # (a 1000-char value would have to come from a tampered initData).
    if raw_username and len(raw_username) > 32:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username too long",
        )
    existing_user = await db.get(User, telegram_id)
    if not existing_user:
        logger.info(f"New user registration: {telegram_id}")
        db.add(
            User(
                telegram_id=telegram_id,
                username=raw_username or None,
            )
        )
    else:
        logger.debug(f"Updating keys for existing user: {telegram_id}")
        # Keep username in sync with the latest case from Telegram.
        existing_user.username = raw_username or None

    # Upsert public bundle.
    stmt = select(PublicBundle).where(PublicBundle.user_id == telegram_id)
    result = await db.execute(stmt)
    bundle = result.scalar_one_or_none()

    if bundle:
        bundle.identity_key = body.identity_key
        bundle.signing_key = body.signing_key
        bundle.signed_pre_key = body.signed_pre_key
        bundle.signature = body.signature
    else:
        db.add(
            PublicBundle(
                user_id=telegram_id,
                identity_key=body.identity_key,
                signing_key=body.signing_key,
                signed_pre_key=body.signed_pre_key,
                signature=body.signature,
            )
        )

    # Replace OTKs: old keys are invalid after bundle rotation.
    await db.execute(delete(OneTimeKey).where(OneTimeKey.user_id == telegram_id))

    # Store new one-time pre-keys.
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
@limiter.limit("20/minute")
async def get_bundle_by_username(
    request: Request,
    username: str,
    _user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if len(username) > 64:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username too long")
    needle = username.lstrip("@").lower()
    # Case-insensitive lookup so callers can use any casing.
    stmt = select(User).where(func.lower(User.username) == needle)
    result = await db.execute(stmt)
    found_user = result.scalar_one_or_none()

    if not found_user:
        logger.warning(f"Key bundle requested for unknown username: {username}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    return await get_bundle(request, found_user.telegram_id, _user, db)


@router.get(
    "/{telegram_id}",
    response_model=PublicBundleResponse,
    summary="Fetch a user's public bundle",
)
@limiter.limit("20/minute")
async def get_bundle(
    request: Request,
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

    user_result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = user_result.scalar_one_or_none()

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
        telegram_username=user.username if user else None,
        identity_key=bundle.identity_key,
        signing_key=bundle.signing_key,
        signed_pre_key=bundle.signed_pre_key,
        signature=bundle.signature,
        one_time_key=otk_out,
    )


@router.get(
    "/otk/count",
    response_model=OTKCountResponse,
    summary="Get remaining OTK count for the current user",
)
@limiter.limit("30/minute")
async def get_otk_count(
    request: Request,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    telegram_id: int = user["id"]
    result = await db.execute(select(func.count()).select_from(OneTimeKey).where(OneTimeKey.user_id == telegram_id))
    count = result.scalar_one()
    return OTKCountResponse(count=count)


@router.put(
    "/spk",
    response_model=StatusResponse,
    summary="Rotate signed pre-key without touching OTKs",
)
@limiter.limit("10/hour")
async def update_spk(
    request: Request,
    body: UpdateSPKRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    telegram_id: int = user["id"]
    stmt = select(PublicBundle).where(PublicBundle.user_id == telegram_id)
    result = await db.execute(stmt)
    bundle = result.scalar_one_or_none()

    if not bundle:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No bundle registered for this user",
        )

    # The signing key is the long-term trust anchor — it's stored at register
    # time and never rotates here, so we verify the new SPK against the one
    # already in the DB. A client that has the matching private signing key
    # can rotate; nobody else can.
    if not verify_spk_signature(bundle.signing_key, body.signed_pre_key, body.signature):
        logger.warning(f"SPK rotation rejected for {telegram_id}: invalid signature")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid SPK signature",
        )

    bundle.signed_pre_key = body.signed_pre_key
    bundle.signature = body.signature
    logger.info(f"SPK rotated for user {telegram_id}")
    return StatusResponse(detail="SPK updated")


@router.post(
    "/otk",
    response_model=StatusResponse,
    summary="Refill one-time pre-keys",
)
@limiter.limit("10/hour")
async def refill_otk(
    request: Request,
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

    # Flush now so a UNIQUE(user_id, key_id) collision turns into a clean 409
    # for the client instead of leaking out of the dependency teardown.
    try:
        await db.flush()
    except IntegrityError as e:
        logger.warning(f"OTK refill rejected for {telegram_id}: duplicate key_id")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Duplicate OTK key_id",
        ) from e

    logger.info(f"User {telegram_id} refilled {len(body.one_time_keys)} OTKs")
    return StatusResponse(detail=f"Added {len(body.one_time_keys)} one-time keys")
