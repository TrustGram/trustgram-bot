"""
Unit tests for app/core/security.py.

Covers
------
- _validate_init_data: valid HMAC → returns user dict
- _validate_init_data: missing hash → 403
- _validate_init_data: invalid hash → 403
- _validate_init_data: missing user field → 403
- get_current_user: debug mode + no header → mock user
- get_current_user: no header, debug=False → 403
- get_current_user: valid header in production mode → delegates to _validate_init_data
"""

import hashlib
import hmac
import json
import urllib.parse

import pytest
from fastapi import HTTPException
from unittest.mock import patch

from app.core.security import _validate_init_data, get_current_user


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_valid_init_data(bot_token: str, user_payload: dict) -> str:
    """Build a correctly HMAC-signed initData string matching Telegram's spec."""
    user_json = json.dumps(user_payload, separators=(",", ":"))
    params = {
        "user": user_json,
        "auth_date": "1700000000",
        "chat_instance": "-99999",
    }
    # Build the check string.
    data_check_parts = sorted(f"{k}={v}" for k, v in params.items())
    data_check_string = "\n".join(data_check_parts)

    # Compute the HMAC.
    secret_key = hmac.new(
        b"WebAppData", bot_token.encode(), hashlib.sha256
    ).digest()
    hash_value = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    params["hash"] = hash_value
    return urllib.parse.urlencode(params)


FAKE_TOKEN = "123456789:ABCDEFghijklmnopqrst"
FAKE_USER = {"id": 42, "first_name": "Alice", "username": "alice"}


# ── _validate_init_data ───────────────────────────────────────────────────────

class TestValidateInitData:
    def test_valid_signature_returns_user(self):
        init_data = _build_valid_init_data(FAKE_TOKEN, FAKE_USER)
        with patch("app.core.security.settings") as mock_settings:
            mock_settings.bot_token = FAKE_TOKEN
            result = _validate_init_data(init_data)
        assert result["id"] == 42
        assert result["username"] == "alice"

    def test_missing_hash_raises_403(self):
        # initData without a hash field
        init_data = "user=%7B%7D&auth_date=1700000000"
        with pytest.raises(HTTPException) as exc:
            _validate_init_data(init_data)
        assert exc.value.status_code == 403
        assert "Missing hash" in exc.value.detail

    def test_invalid_hash_raises_403(self):
        init_data = _build_valid_init_data(FAKE_TOKEN, FAKE_USER)
        # Tamper the hash
        tampered = init_data.replace(
            "hash=", "hash=00000000"
        )
        with patch("app.core.security.settings") as mock_settings:
            mock_settings.bot_token = FAKE_TOKEN
            with pytest.raises(HTTPException) as exc:
                _validate_init_data(tampered)
        assert exc.value.status_code == 403
        assert "Invalid initData signature" in exc.value.detail

    def test_missing_user_field_raises_403(self):
        """Build a valid HMAC but without the user field."""
        params = {"auth_date": "1700000000"}
        data_check_parts = sorted(f"{k}={v}" for k, v in params.items())
        data_check_string = "\n".join(data_check_parts)
        secret_key = hmac.new(
            b"WebAppData", FAKE_TOKEN.encode(), hashlib.sha256
        ).digest()
        hash_value = hmac.new(
            secret_key, data_check_string.encode(), hashlib.sha256
        ).hexdigest()
        params["hash"] = hash_value
        init_data = urllib.parse.urlencode(params)

        with patch("app.core.security.settings") as mock_settings:
            mock_settings.bot_token = FAKE_TOKEN
            with pytest.raises(HTTPException) as exc:
                _validate_init_data(init_data)
        assert exc.value.status_code == 403
        assert "No user payload" in exc.value.detail


# ── get_current_user ──────────────────────────────────────────────────────────

class TestGetCurrentUser:
    @pytest.mark.asyncio
    async def test_debug_mode_no_header_returns_mock(self):
        with patch("app.core.security.settings") as mock_settings:
            mock_settings.debug = True
            result = await get_current_user(x_init_data=None)
        assert result["id"] == 12345678
        assert result["username"] == "test_user"

    @pytest.mark.asyncio
    async def test_production_no_header_raises_403(self):
        with patch("app.core.security.settings") as mock_settings:
            mock_settings.debug = False
            with pytest.raises(HTTPException) as exc:
                await get_current_user(x_init_data=None)
        assert exc.value.status_code == 403
        assert "Missing X-Init-Data" in exc.value.detail

    @pytest.mark.asyncio
    async def test_valid_header_delegates_to_validate(self):
        init_data = _build_valid_init_data(FAKE_TOKEN, FAKE_USER)
        with patch("app.core.security.settings") as mock_settings:
            mock_settings.debug = False
            mock_settings.bot_token = FAKE_TOKEN
            result = await get_current_user(x_init_data=init_data)
        assert result["id"] == 42
