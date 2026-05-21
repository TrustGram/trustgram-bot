"""
Unit tests for app/bot/bot.py lifecycle functions and the fallback handler.

Covers
------
- fallback_handler: sends the Mini App nudge reply.
- on_startup: calls bot.set_chat_menu_button.
- on_shutdown: calls bot.session.close.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestFallbackHandler:
    @pytest.mark.asyncio
    async def test_fallback_handler_replies_with_nudge(self):
        """The catch-all handler should reply with the Mini App prompt."""
        from app.bot.bot import fallback_handler

        mock_message = MagicMock()
        mock_message.answer = AsyncMock()

        await fallback_handler(mock_message)

        mock_message.answer.assert_called_once()
        call_args = mock_message.answer.call_args[0][0]
        assert "TrustGram" in call_args


class TestOnStartup:
    @pytest.mark.asyncio
    async def test_on_startup_sets_menu_button(self):
        """on_startup must call bot.set_chat_menu_button once."""
        from app.bot import bot as bot_module

        mock_bot = MagicMock()
        mock_bot.set_chat_menu_button = AsyncMock()

        with patch.object(bot_module, "bot", mock_bot):
            await bot_module.on_startup()

        mock_bot.set_chat_menu_button.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_startup_handles_exception_gracefully(self):
        """on_startup should catch exceptions during menu button setup and log a warning."""
        from app.bot import bot as bot_module

        mock_bot = MagicMock()
        mock_bot.set_chat_menu_button = AsyncMock(side_effect=Exception("API Error"))

        with patch.object(bot_module, "bot", mock_bot):
            # This should not raise an exception
            await bot_module.on_startup()

        mock_bot.set_chat_menu_button.assert_called_once()


class TestOnStartupWebhook:
    @pytest.mark.asyncio
    async def test_set_webhook_called_when_url_and_secret_present(self):
        """When both URL and secret are configured, on_startup must register the webhook."""
        from app.bot import bot as bot_module

        mock_bot = MagicMock()
        mock_bot.set_chat_menu_button = AsyncMock()
        mock_bot.set_webhook = AsyncMock()

        with (
            patch.object(bot_module, "bot", mock_bot),
            patch.object(bot_module.settings, "telegram_webhook_url", "https://example.com/webhook"),
            patch.object(bot_module.settings, "telegram_webhook_secret", "s3cret"),
        ):
            await bot_module.on_startup()

        mock_bot.set_webhook.assert_called_once()
        kwargs = mock_bot.set_webhook.call_args.kwargs
        assert kwargs["url"] == "https://example.com/webhook"
        assert kwargs["secret_token"] == "s3cret"

    @pytest.mark.asyncio
    async def test_set_webhook_exception_does_not_crash_startup(self):
        """on_startup must log and continue if set_webhook fails."""
        from app.bot import bot as bot_module

        mock_bot = MagicMock()
        mock_bot.set_chat_menu_button = AsyncMock()
        mock_bot.set_webhook = AsyncMock(side_effect=Exception("Telegram down"))

        with (
            patch.object(bot_module, "bot", mock_bot),
            patch.object(bot_module.settings, "telegram_webhook_url", "https://example.com/webhook"),
            patch.object(bot_module.settings, "telegram_webhook_secret", "s3cret"),
        ):
            # Must not raise.
            await bot_module.on_startup()

        mock_bot.set_webhook.assert_called_once()

    @pytest.mark.asyncio
    async def test_secret_without_url_warns_and_skips(self):
        """Secret configured but no URL is a misconfiguration — must not call set_webhook."""
        from app.bot import bot as bot_module

        mock_bot = MagicMock()
        mock_bot.set_chat_menu_button = AsyncMock()
        mock_bot.set_webhook = AsyncMock()

        with (
            patch.object(bot_module, "bot", mock_bot),
            patch.object(bot_module.settings, "telegram_webhook_url", None),
            patch.object(bot_module.settings, "telegram_webhook_secret", "s3cret"),
        ):
            await bot_module.on_startup()

        mock_bot.set_webhook.assert_not_called()


class TestOnShutdown:
    @pytest.mark.asyncio
    async def test_on_shutdown_closes_session(self):
        """on_shutdown must close the bot's HTTP session."""
        from app.bot import bot as bot_module

        mock_session = MagicMock()
        mock_session.close = AsyncMock()
        mock_bot = MagicMock()
        mock_bot.session = mock_session

        with patch.object(bot_module, "bot", mock_bot):
            await bot_module.on_shutdown()

        mock_session.close.assert_called_once()
