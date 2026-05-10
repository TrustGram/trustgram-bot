"""
Integration tests for app/main.py top-level routes.

Covers
------
- GET  /health       → 200 {"status": "ok", ...}
- POST /webhook      → 200 {"ok": True} (aiogram dispatcher is mocked)
- Lifespan hooks     → on_startup / on_shutdown are called correctly
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health_returns_ok(self, client: AsyncClient):
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "service" in data
        assert "version" in data


class TestLifespan:
    @pytest.mark.asyncio
    async def test_lifespan_calls_bot_hooks(self):
        """
        The lifespan async context manager must call on_startup()
        on enter, and on_shutdown() on exit.

        Note: init_db() was removed — migrations are handled by Alembic
        before the server starts.
        """
        from app.main import lifespan

        with (
            patch("app.main.on_startup", new_callable=AsyncMock) as mock_startup,
            patch("app.main.on_shutdown", new_callable=AsyncMock) as mock_shutdown,
        ):
            async with lifespan(None):
                mock_startup.assert_called_once()
                mock_shutdown.assert_not_called()

            mock_shutdown.assert_called_once()


class TestWebhookEndpoint:
    @pytest.mark.asyncio
    async def test_webhook_feeds_update_to_dispatcher(self, client: AsyncClient):
        """
        The /webhook endpoint should pass the raw JSON to dp.feed_update and
        return {"ok": True}. We mock dp.feed_update so no real Telegram
        processing occurs.
        """
        fake_update = {
            "update_id": 1,
            "message": {
                "message_id": 1,
                "from": {"id": 42, "is_bot": False, "first_name": "Alice"},
                "chat": {"id": 42, "type": "private"},
                "date": 1700000000,
                "text": "hello",
            },
        }
        with patch("app.main.dp.feed_update", new_callable=AsyncMock) as mock_feed:
            response = await client.post("/webhook", json=fake_update)

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        mock_feed.assert_called_once()
