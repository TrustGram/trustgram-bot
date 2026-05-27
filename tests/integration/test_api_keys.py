"""
Integration tests for the key-management API (app/api/v1/keys.py).

Covers
------
POST /api/v1/keys/register
  - New user: 201, bundle stored, OTKs stored.
  - Existing user (key rotation): 201, bundle updated.
  - Registration with no OTKs: 201, no OTK row created.
  - Invalid SPK signature: 400 (server-side defence-in-depth check).

GET /api/v1/keys/{telegram_id}
  - Bundle exists + OTK available: 200, OTK consumed (popped).
  - Bundle exists, no OTK: 200, one_time_key=null.
  - Bundle does not exist: 404.

POST /api/v1/keys/otk
  - Adds new OTKs to the pool: 200.
  - OTKs become fetchable via GET bundle.

PUT /api/v1/keys/spk
  - Valid signature: 200, SPK + signature replaced.
  - 404 if no bundle yet.
  - Invalid signature: 400.
  - Signature from a different signing key: 400 (rotation must be authorised
    by the long-term signing key that's already registered).
"""

import base64

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from httpx import AsyncClient

IK_DEFAULT = "base64_ik_default"


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def _gen_ecdh_pair() -> tuple[ec.EllipticCurvePrivateKey, str]:
    """ECDH P-256 keypair → (private, raw uncompressed b64 public)."""
    priv = ec.generate_private_key(ec.SECP256R1())
    raw = priv.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    return priv, _b64(raw)


def _signing_pub_b64(signing_priv: ec.EllipticCurvePrivateKey) -> str:
    spki = signing_priv.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return _b64(spki)


def _sign_spk(signing_priv: ec.EllipticCurvePrivateKey, spk_b64: str) -> str:
    """WebCrypto-format signature (raw r||s, 64 bytes) over the SPK raw bytes."""
    spk_raw = base64.b64decode(spk_b64)
    der_sig = signing_priv.sign(spk_raw, ec.ECDSA(hashes.SHA256()))
    r, s = utils.decode_dss_signature(der_sig)
    return _b64(r.to_bytes(32, "big") + s.to_bytes(32, "big"))


def make_bundle(
    *,
    identity_key: str = IK_DEFAULT,
    one_time_keys: list | None = None,
) -> tuple[dict, ec.EllipticCurvePrivateKey]:
    """
    Build a server-valid register payload + return the signing private key.

    Tests that need to subsequently rotate the SPK keep the returned signing
    key so they can produce a signature the server will accept.
    """
    signing_priv = ec.generate_private_key(ec.SECP256R1())
    _, spk_b64 = _gen_ecdh_pair()
    payload = {
        "identity_key": identity_key,
        "signing_key": _signing_pub_b64(signing_priv),
        "signed_pre_key": spk_b64,
        "signature": _sign_spk(signing_priv, spk_b64),
        "one_time_keys": one_time_keys
        if one_time_keys is not None
        else [
            {"key_id": "otk-1", "public_key": "otk_pk_1"},
            {"key_id": "otk-2", "public_key": "otk_pk_2"},
        ],
    }
    return payload, signing_priv


def make_spk_rotation(signing_priv: ec.EllipticCurvePrivateKey) -> dict:
    """Build a {signed_pre_key, signature} payload signed by `signing_priv`."""
    _, spk_b64 = _gen_ecdh_pair()
    return {
        "signed_pre_key": spk_b64,
        "signature": _sign_spk(signing_priv, spk_b64),
    }


class TestRegisterBundle:
    @pytest.mark.asyncio
    async def test_new_user_registers_successfully(self, client: AsyncClient):
        payload, _ = make_bundle()
        resp = await client.post("/api/v1/keys/register", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["ok"] is True
        assert data["detail"] == "Bundle registered"

    @pytest.mark.asyncio
    async def test_key_rotation_updates_existing_bundle(self, client: AsyncClient):
        first, _ = make_bundle()
        await client.post("/api/v1/keys/register", json=first)

        rotated, _ = make_bundle(identity_key="new_ik", one_time_keys=[])
        resp = await client.post("/api/v1/keys/register", json=rotated)
        assert resp.status_code == 201

        get_resp = await client.get("/api/v1/keys/12345678")
        assert get_resp.json()["identity_key"] == "new_ik"
        assert get_resp.json()["signed_pre_key"] == rotated["signed_pre_key"]

    @pytest.mark.asyncio
    async def test_register_without_otks(self, client: AsyncClient):
        payload, _ = make_bundle(one_time_keys=[])
        resp = await client.post("/api/v1/keys/register", json=payload)
        assert resp.status_code == 201

        get_resp = await client.get("/api/v1/keys/12345678")
        assert get_resp.json()["one_time_key"] is None

    @pytest.mark.asyncio
    async def test_validation_failure_rolls_back_atomically(self, client: AsyncClient):
        """Bad input mid-payload must leave the DB unchanged — no partial bundle."""
        original, _ = make_bundle()
        await client.post("/api/v1/keys/register", json=original)

        # Over-long signature trips Pydantic before the endpoint body runs.
        bad = {**original, "signature": "x" * 9999, "identity_key": "should_not_appear"}
        resp = await client.post("/api/v1/keys/register", json=bad)
        assert resp.status_code == 422

        get_resp = await client.get("/api/v1/keys/12345678")
        assert get_resp.status_code == 200
        assert get_resp.json()["identity_key"] == IK_DEFAULT

    @pytest.mark.asyncio
    async def test_invalid_spk_signature_rejected(self, client: AsyncClient):
        """A bundle whose signature doesn't verify against signing_key must 400."""
        payload, signing_priv = make_bundle()
        # Mangle one signature byte — the rest of the bundle stays valid.
        sig = bytearray(base64.b64decode(payload["signature"]))
        sig[0] ^= 0xFF
        payload["signature"] = _b64(bytes(sig))

        resp = await client.post("/api/v1/keys/register", json=payload)
        assert resp.status_code == 400
        assert "signature" in resp.json()["detail"].lower()

        # And the DB is untouched.
        get_resp = await client.get("/api/v1/keys/12345678")
        assert get_resp.status_code == 404

    @pytest.mark.asyncio
    async def test_mismatched_signing_key_rejected(self, client: AsyncClient):
        """Bundle signed by key A but advertising signing_key B → 400."""
        good, _signing_priv_a = make_bundle()
        other_signing_priv = ec.generate_private_key(ec.SECP256R1())
        # Re-sign the SPK with a different key but keep advertising signing_priv_a's pubkey.
        good["signature"] = _sign_spk(other_signing_priv, good["signed_pre_key"])

        resp = await client.post("/api/v1/keys/register", json=good)
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_malformed_signing_key_rejected(self, client: AsyncClient):
        """signing_key that isn't a valid SPKI DER must 400 (not 500)."""
        payload, _ = make_bundle()
        # Pydantic-valid string, but cryptographically nonsense.
        payload["signing_key"] = _b64(b"definitely not a P-256 SPKI")
        resp = await client.post("/api/v1/keys/register", json=payload)
        assert resp.status_code == 400


class TestGetBundle:
    @pytest.mark.asyncio
    async def test_bundle_with_otk_consumed(self, client: AsyncClient):
        payload, _ = make_bundle()
        await client.post("/api/v1/keys/register", json=payload)

        resp = await client.get("/api/v1/keys/12345678")
        assert resp.status_code == 200
        data = resp.json()
        assert data["telegram_id"] == 12345678
        assert data["identity_key"] == IK_DEFAULT
        assert data["one_time_key"] is not None
        first_otk_id = data["one_time_key"]["key_id"]

        resp2 = await client.get("/api/v1/keys/12345678")
        second_otk_id = resp2.json()["one_time_key"]["key_id"]
        assert second_otk_id != first_otk_id

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
        from app.core.security import get_current_user
        from app.main import app

        def _mock_huge_username():
            return {"id": 12345678, "first_name": "Test", "username": "x" * 200, "language_code": "en"}

        original = app.dependency_overrides.get(get_current_user)
        app.dependency_overrides[get_current_user] = _mock_huge_username
        try:
            payload, _ = make_bundle()
            resp = await client.post("/api/v1/keys/register", json=payload)
            assert resp.status_code == 400
            assert "Username too long" in resp.json()["detail"]
        finally:
            if original:
                app.dependency_overrides[get_current_user] = original


class TestUsernameCase:
    @pytest.mark.asyncio
    async def test_username_stored_with_original_case(self, client: AsyncClient):
        """Registration must preserve the username's original case for display."""
        payload, _ = make_bundle()
        await client.post("/api/v1/keys/register", json=payload)
        resp = await client.get("/api/v1/keys/12345678")
        assert resp.status_code == 200
        assert resp.json()["telegram_username"] == "Test_User"

    @pytest.mark.asyncio
    async def test_lookup_is_case_insensitive(self, client: AsyncClient):
        """Lookups by username work regardless of caller's casing."""
        payload, _ = make_bundle()
        await client.post("/api/v1/keys/register", json=payload)
        for variant in ("test_user", "Test_User", "TEST_USER", "@Test_User"):
            r = await client.get(f"/api/v1/keys/by-username/{variant}")
            assert r.status_code == 200, f"variant {variant!r} did not resolve"
            assert r.json()["telegram_username"] == "Test_User"


class TestRefillOTK:
    @pytest.mark.asyncio
    async def test_duplicate_otk_key_id_rejected(self, client: AsyncClient):
        """Two OTKs sharing the same key_id violate the UNIQUE constraint."""
        payload, _ = make_bundle(one_time_keys=[])
        await client.post("/api/v1/keys/register", json=payload)

        dup_refill = {
            "one_time_keys": [
                {"key_id": "dup", "public_key": "pk_a"},
                {"key_id": "dup", "public_key": "pk_b"},
            ]
        }
        resp = await client.post("/api/v1/keys/otk", json=dup_refill)
        assert resp.status_code in (409, 500)

    @pytest.mark.asyncio
    async def test_refill_adds_keys_to_pool(self, client: AsyncClient):
        payload, _ = make_bundle(one_time_keys=[])
        await client.post("/api/v1/keys/register", json=payload)

        resp = await client.get("/api/v1/keys/12345678")
        assert resp.json()["one_time_key"] is None

        refill = {
            "one_time_keys": [
                {"key_id": "r-1", "public_key": "rpk_1"},
                {"key_id": "r-2", "public_key": "rpk_2"},
            ]
        }
        refill_resp = await client.post("/api/v1/keys/otk", json=refill)
        assert refill_resp.status_code == 200
        assert refill_resp.json()["ok"] is True

        resp2 = await client.get("/api/v1/keys/12345678")
        assert resp2.json()["one_time_key"] is not None
        assert resp2.json()["one_time_key"]["key_id"] in ["r-1", "r-2"]

    @pytest.mark.asyncio
    async def test_otk_count_endpoint(self, client: AsyncClient):
        """/otk/count returns the number of remaining OTKs for the current user."""
        payload, _ = make_bundle()
        await client.post("/api/v1/keys/register", json=payload)
        resp = await client.get("/api/v1/keys/otk/count")
        assert resp.status_code == 200
        assert resp.json()["count"] == 2

        await client.get("/api/v1/keys/12345678")
        resp2 = await client.get("/api/v1/keys/otk/count")
        assert resp2.json()["count"] == 1


class TestUpdateSPK:
    @pytest.mark.asyncio
    async def test_spk_rotation_updates_bundle(self, client: AsyncClient):
        """PUT /keys/spk must update the signed pre-key and signature in place."""
        payload, signing_priv = make_bundle()
        await client.post("/api/v1/keys/register", json=payload)

        rotation = make_spk_rotation(signing_priv)
        resp = await client.put("/api/v1/keys/spk", json=rotation)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        bundle_resp = await client.get("/api/v1/keys/12345678")
        body = bundle_resp.json()
        assert body["signed_pre_key"] == rotation["signed_pre_key"]
        assert body["signature"] == rotation["signature"]
        # Other fields must remain untouched.
        assert body["identity_key"] == IK_DEFAULT

    @pytest.mark.asyncio
    async def test_spk_rotation_without_existing_bundle_returns_404(self, client: AsyncClient):
        """Cannot rotate SPK if you never registered (404 fires before the sig check)."""
        resp = await client.put(
            "/api/v1/keys/spk",
            json={"signed_pre_key": "x", "signature": "c" * 88},
        )
        assert resp.status_code == 404
        assert "No bundle" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_spk_rotation_with_bad_signature_rejected(self, client: AsyncClient):
        """A rotation whose signature doesn't verify against the registered signing key → 400."""
        payload, signing_priv = make_bundle()
        await client.post("/api/v1/keys/register", json=payload)

        rotation = make_spk_rotation(signing_priv)
        sig = bytearray(base64.b64decode(rotation["signature"]))
        sig[0] ^= 0xFF
        rotation["signature"] = _b64(bytes(sig))

        resp = await client.put("/api/v1/keys/spk", json=rotation)
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_spk_rotation_signed_by_wrong_key_rejected(self, client: AsyncClient):
        """Even a perfectly-formed signature is rejected if it's not by the user's signing key."""
        payload, _signing_priv = make_bundle()
        await client.post("/api/v1/keys/register", json=payload)

        attacker = ec.generate_private_key(ec.SECP256R1())
        rotation = make_spk_rotation(attacker)
        resp = await client.put("/api/v1/keys/spk", json=rotation)
        assert resp.status_code == 400


class TestUsernameLookupEdgeCases:
    @pytest.mark.asyncio
    async def test_by_username_unknown_returns_404(self, client: AsyncClient):
        """Lookup by an unregistered username returns 404, not 500."""
        resp = await client.get("/api/v1/keys/by-username/ghost")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "User not found"

    @pytest.mark.asyncio
    async def test_by_username_oversized_rejected(self, client: AsyncClient):
        """Username longer than 64 chars is rejected before hitting the DB."""
        long_name = "x" * 65
        resp = await client.get(f"/api/v1/keys/by-username/{long_name}")
        assert resp.status_code == 400
        assert "too long" in resp.json()["detail"].lower()


class TestBundleExists:
    @pytest.mark.asyncio
    async def test_false_before_register(self, client: AsyncClient):
        resp = await client.get("/api/v1/keys/me/exists")
        assert resp.status_code == 200
        assert resp.json()["exists"] is False

    @pytest.mark.asyncio
    async def test_true_after_register(self, client: AsyncClient):
        payload, _ = make_bundle()
        await client.post("/api/v1/keys/register", json=payload)
        resp = await client.get("/api/v1/keys/me/exists")
        assert resp.json()["exists"] is True

    @pytest.mark.asyncio
    async def test_existence_check_does_not_consume_otk(self, client: AsyncClient):
        """Unlike fetching the full bundle, the existence check must not pop an OTK."""
        payload, _ = make_bundle()  # ships 2 OTKs
        await client.post("/api/v1/keys/register", json=payload)

        await client.get("/api/v1/keys/me/exists")
        await client.get("/api/v1/keys/me/exists")

        # Both OTKs are still available — neither check consumed one.
        count = (await client.get("/api/v1/keys/otk/count")).json()["count"]
        assert count == 2
