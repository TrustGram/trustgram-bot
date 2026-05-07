"""
aiogram bot setup — dispatcher, handlers, and lifecycle hooks.

The bot serves two purposes:
  1. Set the Telegram MenuButton so users can open the Mini App.
  2. (Future) Send push notifications when new messages arrive.
"""

from aiogram import Bot, Dispatcher, types
from aiogram.types import MenuButtonWebApp, WebAppInfo

from app.core.config import settings

bot = Bot(token=settings.bot_token)
dp = Dispatcher()


# ── Handlers ──────────────────────────────────────────────────

@dp.message()
async def fallback_handler(message: types.Message) -> None:
    """
    Catch-all handler — nudges users toward the Mini App instead of
    interacting via the regular chat interface.
    """
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
    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(
            text="Open TrustGram",
            web_app=WebAppInfo(url=settings.webapp_url),
        ),
    )


async def on_shutdown() -> None:
    """
    Graceful cleanup — close the bot HTTP session.
    """
    await bot.session.close()
