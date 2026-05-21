"""
Unit tests for app/core/rate_limit.py.

The limit key function chooses between Telegram user_id (extracted from
X-Init-Data) and remote IP. We exercise every branch to keep accidental
fall-through to IP from going unnoticed.
"""

import json
import urllib.parse
from unittest.mock import MagicMock

from app.core.rate_limit import _user_key


def _request(headers: dict, client_host: str = "203.0.113.7"):
    """Build a minimal Starlette-like Request stand-in for _user_key."""
    req = MagicMock()
    req.headers = headers
    # slowapi.util.get_remote_address reads request.client.host
    req.client = MagicMock(host=client_host)
    return req


class TestUserKey:
    def test_valid_init_data_returns_user_key(self):
        user = {"id": 555}
        init_data = urllib.parse.urlencode({"user": json.dumps(user), "auth_date": "1"})
        key = _user_key(_request({"x-init-data": init_data}))
        assert key == "user:555"

    def test_no_init_data_falls_back_to_ip(self):
        key = _user_key(_request({}, client_host="198.51.100.1"))
        assert key.startswith("ip:")

    def test_malformed_init_data_falls_back_to_ip(self):
        # `user=` field is not valid JSON → parse_qs returns it, json.loads raises.
        init_data = "user=not-json&auth_date=1"
        key = _user_key(_request({"x-init-data": init_data}, client_host="198.51.100.2"))
        assert key.startswith("ip:")

    def test_init_data_without_user_field_falls_back_to_ip(self):
        # Valid init-data shape but no `user` key — the extractor must fall through.
        init_data = urllib.parse.urlencode({"auth_date": "1"})
        key = _user_key(_request({"x-init-data": init_data}, client_host="198.51.100.3"))
        assert key.startswith("ip:")

    def test_user_without_id_falls_back_to_ip(self):
        # `user` present but missing the `id` field — still must fall through.
        init_data = urllib.parse.urlencode({"user": json.dumps({"first_name": "X"})})
        key = _user_key(_request({"x-init-data": init_data}, client_host="198.51.100.4"))
        assert key.startswith("ip:")
