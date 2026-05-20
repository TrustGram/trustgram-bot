"""
Unit tests for app/core/security.py.

Covers
------
- _validate_init_data: valid HMAC → returns user dict
- _validate_init_data: missing hash → 403
- _validate_init_data: invalid hash → 403
- _validate_init_data: missing user field → 403
- get_current_user: missing header → 403
- get_current_user: valid header in production mode → delegates to _validate_init_data
"""

import hashlib
import hmac
import json
import time
import urllib.parse
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.core.security import _validate_init_data, get_current_user

# ── Helpers ───────────────────────────────────────────────────────────────────


def _build_valid_init_data(bot_token: str, user_payload: dict, auth_date: int | None = None) -> str:
    """Build a correctly HMAC-signed initData string matching Telegram's spec."""
    user_json = json.dumps(user_payload, separators=(",", ":"))
    params = {
        "user": user_json,
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "chat_instance": "-99999",
    }
    # Build the check string.
    data_check_parts = sorted(f"{k}={v}" for k, v in params.items())
    data_check_string = "\n".join(data_check_parts)

    # Compute the HMAC.
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    hash_value = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

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
            mock_settings.init_data_max_age_seconds = 86400
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
        tampered = init_data.replace("hash=", "hash=00000000")
        with patch("app.core.security.settings") as mock_settings:
            mock_settings.bot_token = FAKE_TOKEN
            with pytest.raises(HTTPException) as exc:
                _validate_init_data(tampered)
        assert exc.value.status_code == 403
        assert "Invalid initData signature" in exc.value.detail

    def test_expired_auth_date_raises_403(self):
        # 48 hours old → past the 24h ceiling
        old_ts = int(time.time()) - 48 * 3600
        init_data = _build_valid_init_data(FAKE_TOKEN, FAKE_USER, auth_date=old_ts)
        with patch("app.core.security.settings") as mock_settings:
            mock_settings.bot_token = FAKE_TOKEN
            mock_settings.init_data_max_age_seconds = 86400
            with pytest.raises(HTTPException) as exc:
                _validate_init_data(init_data)
        assert exc.value.status_code == 403
        assert "expired" in exc.value.detail

    def test_future_auth_date_raises_403(self):
        # 1 hour in the future → outside the +5min clock-skew window
        future_ts = int(time.time()) + 3600
        init_data = _build_valid_init_data(FAKE_TOKEN, FAKE_USER, auth_date=future_ts)
        with patch("app.core.security.settings") as mock_settings:
            mock_settings.bot_token = FAKE_TOKEN
            mock_settings.init_data_max_age_seconds = 86400
            with pytest.raises(HTTPException) as exc:
                _validate_init_data(init_data)
        assert exc.value.status_code == 403
        assert "expired" in exc.value.detail

    def test_missing_user_field_raises_403(self):
        """Build a valid HMAC but without the user field."""
        params = {"auth_date": str(int(time.time()))}
        data_check_parts = sorted(f"{k}={v}" for k, v in params.items())
        data_check_string = "\n".join(data_check_parts)
        secret_key = hmac.new(b"WebAppData", FAKE_TOKEN.encode(), hashlib.sha256).digest()
        hash_value = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        params["hash"] = hash_value
        init_data = urllib.parse.urlencode(params)

        with patch("app.core.security.settings") as mock_settings:
            mock_settings.bot_token = FAKE_TOKEN
            mock_settings.init_data_max_age_seconds = 86400
            with pytest.raises(HTTPException) as exc:
                _validate_init_data(init_data)
        assert exc.value.status_code == 403
        assert "No user payload" in exc.value.detail


# ── get_current_user ──────────────────────────────────────────────────────────


class TestGetCurrentUser:
    @pytest.mark.asyncio
    async def test_no_header_raises_403(self):
        with pytest.raises(HTTPException) as exc:
            await get_current_user(x_init_data=None)
        assert exc.value.status_code == 403
        assert "Missing X-Init-Data" in exc.value.detail

    @pytest.mark.asyncio
    async def test_valid_header_delegates_to_validate(self):
        init_data = _build_valid_init_data(FAKE_TOKEN, FAKE_USER)
        with patch("app.core.security.settings") as mock_settings:
            mock_settings.bot_token = FAKE_TOKEN
            mock_settings.init_data_max_age_seconds = 86400
            result = await get_current_user(x_init_data=init_data)
        assert result["id"] == 42
