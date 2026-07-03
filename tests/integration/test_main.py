"""
Integration tests for app/main.py top-level routes.

Covers
------
- GET  /health       → 200 {"status": "ok", ...}
- POST /webhook      → 200 {"ok": True} (aiogram dispatcher is mocked)
- Lifespan hooks     → on_startup / on_shutdown are called correctly
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


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


_FAKE_UPDATE = {
    "update_id": 1,
    "message": {
        "message_id": 1,
        "from": {"id": 42, "is_bot": False, "first_name": "Alice"},
        "chat": {"id": 42, "type": "private"},
        "date": 1700000000,
        "text": "hello",
    },
}


class TestWebhookEndpoint:
    @pytest.mark.asyncio
    async def test_webhook_feeds_update_when_no_secret_configured(self, client: AsyncClient):
        """With no telegram_webhook_secret set, the endpoint accepts everything (dev mode)."""
        with patch("app.main.settings.telegram_webhook_secret", None):
            with patch("app.main.dp.feed_update", new_callable=AsyncMock) as mock_feed:
                response = await client.post("/webhook", json=_FAKE_UPDATE)
        assert response.status_code == 200
        assert response.json() == {"ok": True}
        mock_feed.assert_called_once()

    @pytest.mark.asyncio
    async def test_webhook_accepts_matching_secret_token(self, client: AsyncClient):
        with patch("app.main.settings.telegram_webhook_secret", "s3cr3t"):
            with patch("app.main.dp.feed_update", new_callable=AsyncMock) as mock_feed:
                response = await client.post(
                    "/webhook",
                    json=_FAKE_UPDATE,
                    headers={"X-Telegram-Bot-Api-Secret-Token": "s3cr3t"},
                )
        assert response.status_code == 200
        mock_feed.assert_called_once()

    @pytest.mark.asyncio
    async def test_webhook_rejects_missing_secret_token(self, client: AsyncClient):
        with patch("app.main.settings.telegram_webhook_secret", "s3cr3t"):
            with patch("app.main.dp.feed_update", new_callable=AsyncMock) as mock_feed:
                response = await client.post("/webhook", json=_FAKE_UPDATE)
        assert response.status_code == 404
        mock_feed.assert_not_called()

    @pytest.mark.asyncio
    async def test_webhook_rejects_wrong_secret_token(self, client: AsyncClient):
        with patch("app.main.settings.telegram_webhook_secret", "s3cr3t"):
            with patch("app.main.dp.feed_update", new_callable=AsyncMock) as mock_feed:
                response = await client.post(
                    "/webhook",
                    json=_FAKE_UPDATE,
                    headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
                )
        assert response.status_code == 404
        mock_feed.assert_not_called()


class TestDocsAccess:
    @pytest.mark.asyncio
    async def test_docs_open_in_development(self, client: AsyncClient):
        """In development, /docs requires no key."""
        with patch("app.main.settings.environment", "development"):
            response = await client.get("/docs")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_docs_blocked_in_production_without_key(self, client: AsyncClient):
        """In production without the header, /docs returns 404 (not 401)."""
        with (
            patch("app.main.settings.environment", "production"),
            patch("app.main.settings.docs_api_key", "secret-key"),
        ):
            response = await client.get("/docs")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_docs_blocked_in_production_with_wrong_key(self, client: AsyncClient):
        with (
            patch("app.main.settings.environment", "production"),
            patch("app.main.settings.docs_api_key", "secret-key"),
        ):
            response = await client.get("/docs", headers={"X-Docs-Key": "wrong"})
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_docs_allowed_in_production_with_correct_key(self, client: AsyncClient):
        with (
            patch("app.main.settings.environment", "production"),
            patch("app.main.settings.docs_api_key", "secret-key"),
        ):
            response = await client.get("/docs", headers={"X-Docs-Key": "secret-key"})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_redoc_gated_same_way(self, client: AsyncClient):
        with patch("app.main.settings.environment", "development"):
            response = await client.get("/redoc")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_openapi_json_gated_same_way(self, client: AsyncClient):
        with patch("app.main.settings.environment", "development"):
            response = await client.get("/openapi.json")
        assert response.status_code == 200
        assert "openapi" in response.json()


class TestUnhandledExceptionHandler:
    @pytest.mark.asyncio
    async def test_uncaught_exception_returns_json_500(self):
        """
        The catch-all exception handler must turn uncaught errors into a JSON
        500 (so CORS headers flow back through the middleware stack and the
        browser sees a proper response instead of a CORS error) — while NOT
        leaking the exception type/message to the client (that detail is logged
        server-side only).

        We need a transport with raise_app_exceptions=False — by default httpx's
        ASGITransport re-raises any exception that bubbles past the registered
        handlers (even though our handler converted it into a 500 response).
        """
        from app.core.database import get_db
        from app.core.security import get_current_user
        from app.main import app
        from tests.conftest import MOCK_USER

        app.dependency_overrides[get_current_user] = lambda: MOCK_USER

        async def _noop_db():
            yield None

        app.dependency_overrides[get_db] = _noop_db

        try:
            transport = ASGITransport(app=app, raise_app_exceptions=False)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                with patch("app.main.dp.feed_update", new_callable=AsyncMock, side_effect=RuntimeError("kaboom")):
                    response = await ac.post("/webhook", json=_FAKE_UPDATE)
            assert response.status_code == 500
            body = response.json()
            # Generic body only — the exception type/message must NOT leak.
            assert body["detail"] == "Internal server error"
            assert "RuntimeError" not in body["detail"]
            assert "kaboom" not in body["detail"]
        finally:
            app.dependency_overrides.clear()


class TestLifespanCleanupTimeout:
    @pytest.mark.asyncio
    async def test_cleanup_task_timeout_triggers_cancel(self):
        """
        If the inbox cleanup task doesn't stop within the wait_for window,
        lifespan must cancel it instead of hanging shutdown forever.
        """
        from app.main import lifespan

        async def never_stop(stop_event):
            # Ignore the stop_event entirely — we want to force the timeout path.
            while True:
                await asyncio.sleep(60)

        with (
            patch("app.main.on_startup", new_callable=AsyncMock),
            patch("app.main.on_shutdown", new_callable=AsyncMock),
            patch("app.main.inbox_cleanup_loop", side_effect=never_stop),
            patch("app.main.asyncio.wait_for", side_effect=asyncio.TimeoutError),
        ):
            async with lifespan(None):
                pass
