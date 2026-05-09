"""
Integration tests for GET /api/v1/auth/me.

Covers
------
- Authenticated request → returns the mock user dict injected by conftest.
"""

import pytest
from httpx import AsyncClient


class TestAuthMe:
    @pytest.mark.asyncio
    async def test_get_me_returns_mock_user(self, client: AsyncClient):
        response = await client.get("/api/v1/auth/me")
        assert response.status_code == 200
        data = response.json()
        # The conftest mock user has id=12345678 and username="test_user"
        assert data["id"] == 12345678
        assert data["username"] == "test_user"
        assert data["first_name"] == "Test"
