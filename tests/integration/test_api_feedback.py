"""
Integration tests for the feedback API (app/api/v1/feedback.py).

Covers
------
POST /api/v1/feedback
  - Relays a report to the admin chat → 201.
  - Report text carries the user id, category, version, platform.
  - 503 when ADMIN_CHAT_ID is unconfigured.
  - 502 when Telegram delivery fails.
  - 422 on missing/oversized fields.
"""

from unittest.mock import patch

import pytest
from aiogram.exceptions import TelegramAPIError
from httpx import AsyncClient

from app.core.config import settings


@pytest.fixture()
def admin_chat():
    """Point feedback at a known admin chat for the duration of a test."""
    with patch.object(settings, "admin_chat_id", 555000111):
        yield 555000111


class TestSubmitFeedback:
    @pytest.mark.asyncio
    async def test_relays_to_admin_chat(self, client: AsyncClient, admin_chat):
        from app.bot import bot as bot_mod

        bot_mod.bot.send_message.reset_mock()
        payload = {
            "category": "crypto",
            "message": "Decryption fails after PIN change",
            "app_version": "abc123",
            "platform": "android",
        }
        resp = await client.post("/api/v1/feedback", json=payload)

        assert resp.status_code == 201
        assert resp.json()["ok"] is True

        bot_mod.bot.send_message.assert_awaited_once()
        kwargs = bot_mod.bot.send_message.await_args.kwargs
        assert kwargs["chat_id"] == admin_chat
        text = kwargs["text"]
        assert "crypto" in text
        assert "Decryption fails after PIN change" in text
        assert "12345678" in text  # MOCK_USER id
        assert "android" in text
        assert "abc123" in text

    @pytest.mark.asyncio
    async def test_503_when_admin_chat_unconfigured(self, client: AsyncClient):
        with patch.object(settings, "admin_chat_id", None):
            resp = await client.post(
                "/api/v1/feedback",
                json={"category": "ui", "message": "button overlaps"},
            )
        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_502_when_telegram_delivery_fails(self, client: AsyncClient, admin_chat):
        from app.bot import bot as bot_mod

        bot_mod.bot.send_message.reset_mock()
        bot_mod.bot.send_message.side_effect = TelegramAPIError(method=None, message="boom")
        try:
            resp = await client.post(
                "/api/v1/feedback",
                json={"category": "other", "message": "something"},
            )
            assert resp.status_code == 502
        finally:
            bot_mod.bot.send_message.side_effect = None

    @pytest.mark.asyncio
    async def test_empty_message_rejected(self, client: AsyncClient, admin_chat):
        resp = await client.post(
            "/api/v1/feedback",
            json={"category": "ui", "message": ""},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_oversized_message_rejected(self, client: AsyncClient, admin_chat):
        resp = await client.post(
            "/api/v1/feedback",
            json={"category": "ui", "message": "x" * 2001},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_version_and_platform_optional(self, client: AsyncClient, admin_chat):
        from app.bot import bot as bot_mod

        bot_mod.bot.send_message.reset_mock()
        resp = await client.post(
            "/api/v1/feedback",
            json={"category": "other", "message": "minimal report"},
        )
        assert resp.status_code == 201
        text = bot_mod.bot.send_message.await_args.kwargs["text"]
        # Missing metadata is rendered as a placeholder, not blank.
        assert "Version: ?" in text
        assert "Platform: ?" in text
