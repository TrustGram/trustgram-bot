"""
Unit tests for Pydantic schemas (app/schemas/schemas.py).

Covers
------
- Happy-path construction of every schema class.
- Field-level validation errors (missing required fields, wrong types).
- Default values behave as specified.
"""

import pytest
from pydantic import ValidationError

from app.schemas.schemas import (
    InboxResponse,
    MessageResponse,
    OneTimeKeySchema,
    PublicBundleResponse,
    RefillOTKRequest,
    RegisterBundleRequest,
    SendMessageRequest,
    StatusResponse,
)
from datetime import datetime, timezone


# ── OneTimeKeySchema ─────────────────────────────────────────────────────────

class TestOneTimeKeySchema:
    def test_valid(self):
        otk = OneTimeKeySchema(key_id="k1", public_key="pk_base64")
        assert otk.key_id == "k1"
        assert otk.public_key == "pk_base64"

    def test_missing_key_id(self):
        with pytest.raises(ValidationError):
            OneTimeKeySchema(public_key="pk")

    def test_missing_public_key(self):
        with pytest.raises(ValidationError):
            OneTimeKeySchema(key_id="k1")


# ── RegisterBundleRequest ────────────────────────────────────────────────────

class TestRegisterBundleRequest:
    def test_valid_with_otks(self):
        req = RegisterBundleRequest(
            identity_key="ik",
            signed_pre_key="spk",
            signature="sig",
            one_time_keys=[{"key_id": "1", "public_key": "pk1"}],
        )
        assert len(req.one_time_keys) == 1

    def test_defaults_to_empty_otks(self):
        req = RegisterBundleRequest(
            identity_key="ik",
            signed_pre_key="spk",
            signature="sig",
        )
        assert req.one_time_keys == []

    def test_missing_identity_key(self):
        with pytest.raises(ValidationError):
            RegisterBundleRequest(signed_pre_key="spk", signature="sig")


# ── PublicBundleResponse ─────────────────────────────────────────────────────

class TestPublicBundleResponse:
    def test_valid_with_otk(self):
        resp = PublicBundleResponse(
            telegram_id=123,
            identity_key="ik",
            signed_pre_key="spk",
            signature="sig",
            one_time_key={"key_id": "k1", "public_key": "pk1"},
        )
        assert resp.one_time_key is not None
        assert resp.one_time_key.key_id == "k1"

    def test_valid_without_otk(self):
        resp = PublicBundleResponse(
            telegram_id=123,
            identity_key="ik",
            signed_pre_key="spk",
            signature="sig",
        )
        assert resp.one_time_key is None


# ── RefillOTKRequest ─────────────────────────────────────────────────────────

class TestRefillOTKRequest:
    def test_valid(self):
        req = RefillOTKRequest(
            one_time_keys=[{"key_id": "1", "public_key": "pk"}]
        )
        assert len(req.one_time_keys) == 1

    def test_empty_list_rejected(self):
        """min_length=1 must reject an empty list."""
        with pytest.raises(ValidationError):
            RefillOTKRequest(one_time_keys=[])

    def test_missing_field(self):
        with pytest.raises(ValidationError):
            RefillOTKRequest()


# ── SendMessageRequest ───────────────────────────────────────────────────────

class TestSendMessageRequest:
    def test_valid(self):
        req = SendMessageRequest(recipient_id=999, encrypted_payload="blob")
        assert req.recipient_id == 999

    def test_missing_recipient(self):
        with pytest.raises(ValidationError):
            SendMessageRequest(encrypted_payload="blob")


# ── MessageResponse ──────────────────────────────────────────────────────────

class TestMessageResponse:
    def test_valid(self):
        now = datetime.now(timezone.utc)
        resp = MessageResponse(
            id=1,
            sender_id=42,
            encrypted_payload="cipher",
            timestamp=now,
        )
        assert resp.id == 1
        assert resp.sender_id == 42


# ── InboxResponse ────────────────────────────────────────────────────────────

class TestInboxResponse:
    def test_empty_inbox(self):
        resp = InboxResponse(messages=[])
        assert resp.messages == []

    def test_with_messages(self):
        now = datetime.now(timezone.utc)
        resp = InboxResponse(
            messages=[
                {"id": 1, "sender_id": 2, "encrypted_payload": "x", "timestamp": now}
            ]
        )
        assert len(resp.messages) == 1


# ── StatusResponse ───────────────────────────────────────────────────────────

class TestStatusResponse:
    def test_defaults(self):
        resp = StatusResponse()
        assert resp.ok is True
        assert resp.detail == ""

    def test_custom_values(self):
        resp = StatusResponse(ok=False, detail="something went wrong")
        assert resp.ok is False
        assert resp.detail == "something went wrong"
