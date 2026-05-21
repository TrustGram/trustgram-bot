"""
aiogram bot setup — dispatcher, handlers, and lifecycle hooks.

The bot serves two purposes:
  1. Set the Telegram MenuButton so users can open the Mini App.
  2. (Future) Send push notifications when new messages arrive.
"""

from aiogram import Bot, Dispatcher, types
from aiogram.types import MenuButtonWebApp, WebAppInfo

from app.core.config import settings
from app.core.logger import logger

bot = Bot(token=settings.bot_token)
dp = Dispatcher()


# ── Handlers ──────────────────────────────────────────────────


@dp.message()
async def fallback_handler(message: types.Message) -> None:
    """
    Catch-all handler — nudges users toward the Mini App instead of
    interacting via the regular chat interface.
    """
    logger.info(f"Received message from user {message.from_user.id}: {message.text[:50]}...")
    await message.answer(
        "👋 Open TrustGram using the button below to start a secure conversation.",
    )


# ── Lifecycle ─────────────────────────────────────────────────


async def on_startup() -> None:
    """
    Called once when the FastAPI application starts.

    - Sets the Telegram MenuButton to launch the Mini App.
    - Registers the webhook so Telegram sends updates to our server.
    """
    try:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="Open TrustGram",
                web_app=WebAppInfo(url=settings.webapp_url),
            ),
        )
        logger.info(f"Successfully set Chat Menu Button to: {settings.webapp_url}")
    except Exception as e:
        # If the WebApp URL is invalid or the bot is restricted,
        # we don't want to crash the whole backend.
        logger.warning(f"Could not set chat menu button: {e}")

    # Register the webhook with a secret token so Telegram authenticates each
    # delivery. Without a secret anyone with the URL can POST fake updates.
    if settings.telegram_webhook_url and settings.telegram_webhook_secret:
        try:
            await bot.set_webhook(
                url=settings.telegram_webhook_url,
                secret_token=settings.telegram_webhook_secret,
                drop_pending_updates=False,
            )
            logger.info(f"Webhook registered with secret token at {settings.telegram_webhook_url}")
        except Exception as e:
            logger.error(f"Could not register webhook: {e}")
    elif settings.telegram_webhook_secret and not settings.telegram_webhook_url:
        logger.warning("telegram_webhook_secret set without telegram_webhook_url — webhook not registered")
    else:
        logger.warning("Webhook is unauthenticated — set TELEGRAM_WEBHOOK_URL + TELEGRAM_WEBHOOK_SECRET")


async def on_shutdown() -> None:
    """
    Graceful cleanup — close the bot HTTP session.
    """
    logger.info("Closing bot HTTP session...")
    await bot.session.close()
