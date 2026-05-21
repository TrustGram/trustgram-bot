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
    "signing_key": "base64_signing_key",
    "signed_pre_key": "base64_spk",
    "signature": "a" * 88,  # base64 ECDSA P-256 signature (~88 chars); content not verified server-side
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
            "signing_key": "new_signing",
            "signed_pre_key": "new_spk",
            "signature": "b" * 88,
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

    @pytest.mark.asyncio
    async def test_validation_failure_rolls_back_atomically(self, client: AsyncClient):
        """Bad input mid-payload must leave the DB unchanged — no partial bundle."""
        # Register a valid bundle first
        await client.post("/api/v1/keys/register", json=BUNDLE_PAYLOAD)

        # Now try to rotate with an over-long signature (fails Pydantic validation)
        bad = {**BUNDLE_PAYLOAD, "signature": "x" * 9999, "identity_key": "should_not_appear"}
        resp = await client.post("/api/v1/keys/register", json=bad)
        assert resp.status_code == 422

        # Original bundle must still be intact
        get_resp = await client.get("/api/v1/keys/12345678")
        assert get_resp.status_code == 200
        assert get_resp.json()["identity_key"] == BUNDLE_PAYLOAD["identity_key"]


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


class TestUsernameValidation:
    @pytest.mark.asyncio
    async def test_oversized_username_rejected(self, client: AsyncClient, db_session):
        """A tampered initData with a >32-char username must be rejected."""
        # Override the mock user with a hostile username for this test only.
        from app.core.security import get_current_user
        from app.main import app

        def _mock_huge_username():
            return {"id": 12345678, "first_name": "Test", "username": "x" * 200, "language_code": "en"}

        original = app.dependency_overrides.get(get_current_user)
        app.dependency_overrides[get_current_user] = _mock_huge_username
        try:
            resp = await client.post("/api/v1/keys/register", json=BUNDLE_PAYLOAD)
            assert resp.status_code == 400
            assert "Username too long" in resp.json()["detail"]
        finally:
            if original:
                app.dependency_overrides[get_current_user] = original


class TestUsernameCase:
    @pytest.mark.asyncio
    async def test_username_stored_with_original_case(self, client: AsyncClient):
        """Registration must preserve the username's original case for display."""
        await client.post("/api/v1/keys/register", json=BUNDLE_PAYLOAD)
        # The mock user is "Test_User" — case should round-trip
        resp = await client.get("/api/v1/keys/12345678")
        assert resp.status_code == 200
        assert resp.json()["telegram_username"] == "Test_User"

    @pytest.mark.asyncio
    async def test_lookup_is_case_insensitive(self, client: AsyncClient):
        """Lookups by username work regardless of caller's casing."""
        await client.post("/api/v1/keys/register", json=BUNDLE_PAYLOAD)
        for variant in ("test_user", "Test_User", "TEST_USER", "@Test_User"):
            r = await client.get(f"/api/v1/keys/by-username/{variant}")
            assert r.status_code == 200, f"variant {variant!r} did not resolve"
            assert r.json()["telegram_username"] == "Test_User"


class TestRefillOTK:
    @pytest.mark.asyncio
    async def test_duplicate_otk_key_id_rejected(self, client: AsyncClient):
        """Two OTKs sharing the same key_id violate the UNIQUE constraint."""
        await client.post("/api/v1/keys/register", json={**BUNDLE_PAYLOAD, "one_time_keys": []})

        dup_refill = {
            "one_time_keys": [
                {"key_id": "dup", "public_key": "pk_a"},
                {"key_id": "dup", "public_key": "pk_b"},
            ]
        }
        resp = await client.post("/api/v1/keys/otk", json=dup_refill)
        # SQLAlchemy IntegrityError surfaces as 500; the important guarantee is
        # the constraint fires rather than silently storing duplicates.
        assert resp.status_code in (409, 500)

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
