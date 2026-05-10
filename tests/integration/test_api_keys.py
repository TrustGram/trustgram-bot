"""
Integration tests for the key-management API (app/api/v1/keys.py).

Covers
------
POST /api/v1/keys/register
  - New user: 201, bundle stored, OTKs stored.
  - Existing user (key rotation): 201, bundle updated.
  - Registration with no OTKs: 201, no OTK row created.

GET /api/v1/keys/{telegram_id}
  - Bundle exists + OTK available: 200, OTK consumed (popped).
  - Bundle exists, no OTK: 200, one_time_key=null.
  - Bundle does not exist: 404.

POST /api/v1/keys/otk
  - Adds new OTKs to the pool: 200.
  - OTKs become fetchable via GET bundle.
"""

import pytest
from httpx import AsyncClient

BUNDLE_PAYLOAD = {
    "identity_key": "base64_ik",
    "signed_pre_key": "base64_spk",
    "signature": "base64_sig",
    "one_time_keys": [
        {"key_id": "otk-1", "public_key": "otk_pk_1"},
        {"key_id": "otk-2", "public_key": "otk_pk_2"},
    ],
}


class TestRegisterBundle:
    @pytest.mark.asyncio
    async def test_new_user_registers_successfully(self, client: AsyncClient):
        resp = await client.post("/api/v1/keys/register", json=BUNDLE_PAYLOAD)
        assert resp.status_code == 201
        data = resp.json()
        assert data["ok"] is True
        assert data["detail"] == "Bundle registered"

    @pytest.mark.asyncio
    async def test_key_rotation_updates_existing_bundle(self, client: AsyncClient):
        # First registration
        await client.post("/api/v1/keys/register", json=BUNDLE_PAYLOAD)

        # Rotation with different keys
        rotated = {
            "identity_key": "new_ik",
            "signed_pre_key": "new_spk",
            "signature": "new_sig",
            "one_time_keys": [],
        }
        resp = await client.post("/api/v1/keys/register", json=rotated)
        assert resp.status_code == 201

        # Verify the fetched bundle reflects the new keys
        get_resp = await client.get("/api/v1/keys/12345678")
        assert get_resp.json()["identity_key"] == "new_ik"
        assert get_resp.json()["signed_pre_key"] == "new_spk"

    @pytest.mark.asyncio
    async def test_register_without_otks(self, client: AsyncClient):
        payload = {**BUNDLE_PAYLOAD, "one_time_keys": []}
        resp = await client.post("/api/v1/keys/register", json=payload)
        assert resp.status_code == 201

        get_resp = await client.get("/api/v1/keys/12345678")
        assert get_resp.json()["one_time_key"] is None


class TestGetBundle:
    @pytest.mark.asyncio
    async def test_bundle_with_otk_consumed(self, client: AsyncClient):
        await client.post("/api/v1/keys/register", json=BUNDLE_PAYLOAD)

        resp = await client.get("/api/v1/keys/12345678")
        assert resp.status_code == 200
        data = resp.json()
        assert data["telegram_id"] == 12345678
        assert data["identity_key"] == "base64_ik"
        assert data["one_time_key"] is not None
        first_otk_id = data["one_time_key"]["key_id"]

        # Second fetch should get the other OTK (first was consumed)
        resp2 = await client.get("/api/v1/keys/12345678")
        second_otk_id = resp2.json()["one_time_key"]["key_id"]
        assert second_otk_id != first_otk_id

        # Third fetch — pool exhausted
        resp3 = await client.get("/api/v1/keys/12345678")
        assert resp3.json()["one_time_key"] is None

    @pytest.mark.asyncio
    async def test_bundle_not_found_returns_404(self, client: AsyncClient):
        resp = await client.get("/api/v1/keys/99999999")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "User has no registered bundle"


class TestRefillOTK:
    @pytest.mark.asyncio
    async def test_refill_adds_keys_to_pool(self, client: AsyncClient):
        # Register without OTKs first
        payload = {**BUNDLE_PAYLOAD, "one_time_keys": []}
        await client.post("/api/v1/keys/register", json=payload)

        # Pool should be empty
        resp = await client.get("/api/v1/keys/12345678")
        assert resp.json()["one_time_key"] is None

        # Refill
        refill = {
            "one_time_keys": [
                {"key_id": "r-1", "public_key": "rpk_1"},
                {"key_id": "r-2", "public_key": "rpk_2"},
            ]
        }
        refill_resp = await client.post("/api/v1/keys/otk", json=refill)
        assert refill_resp.status_code == 200
        assert refill_resp.json()["ok"] is True

        # Now an OTK should be available
        resp2 = await client.get("/api/v1/keys/12345678")
        assert resp2.json()["one_time_key"] is not None
        assert resp2.json()["one_time_key"]["key_id"] in ["r-1", "r-2"]
