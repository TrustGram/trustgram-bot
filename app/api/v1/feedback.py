"""
Feedback endpoint — relays user bug reports to the admin Telegram chat.

POST /feedback — accepts a short report (category + free text + client
metadata) and forwards it to ``settings.admin_chat_id`` via the bot.

The server never persists reports; it is a thin relay. Reports carry only what
the user typed plus client metadata (app version, platform) — no message
content and no key material ever reach this path.
"""

from aiogram.exceptions import TelegramAPIError
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.bot.bot import bot
from app.core.config import settings
from app.core.logger import logger
from app.core.rate_limit import limiter
from app.core.security import get_current_user
from app.schemas.schemas import FeedbackRequest, StatusResponse

router = APIRouter(prefix="/feedback", tags=["feedback"])


def _format_report(body: FeedbackRequest, user: dict) -> str:
    """Build the plain-text admin message.

    Sent without parse_mode, so user-supplied text is treated literally — no
    HTML/Markdown injection is possible and no escaping is needed.
    """
    username = f"@{user['username']}" if user.get("username") else "(no username)"
    return (
        "🐛 TrustGram bug report\n"
        f"\nCategory: {body.category}"
        f"\nFrom: {user['id']} {username}"
        f"\nVersion: {body.app_version or '?'}"
        f"\nPlatform: {body.platform or '?'}"
        f"\n\n{body.message}"
    )


@router.post(
    "",
    response_model=StatusResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a bug report",
)
@limiter.limit("5/minute")
async def submit_feedback(
    request: Request,
    body: FeedbackRequest,
    user: dict = Depends(get_current_user),
):
    """Forward a user bug report to the configured admin chat."""
    if not settings.admin_chat_id:
        logger.warning("Feedback received but ADMIN_CHAT_ID is not configured; dropping report")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Feedback channel is not configured",
        )

    try:
        await bot.send_message(chat_id=settings.admin_chat_id, text=_format_report(body, user))
    except TelegramAPIError as e:
        logger.warning("Failed to deliver feedback to admin chat: %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not deliver feedback",
        ) from e

    logger.info("Feedback relayed (category=%s)", body.category)
    return StatusResponse(detail="Feedback received")
