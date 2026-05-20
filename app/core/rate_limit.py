"""
Rate limiting setup.

Keys requests by Telegram user_id (extracted from X-Init-Data) rather than IP —
every Mini App request comes through Telegram's infrastructure, so IPs are
useless. Falls back to client IP only for unauthenticated probes.

Backend is in-memory by default (single-instance deployments on Render free
tier). For multi-worker setups, set ``RATE_LIMIT_STORAGE_URI`` (e.g.
``redis://...``) — slowapi picks it up automatically.
"""

import json
from urllib.parse import parse_qs

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings


def _user_key(request: Request) -> str:
    """Use Telegram user_id as the limit key; fall back to IP."""
    init_data = request.headers.get("x-init-data")
    if init_data:
        try:
            parsed = parse_qs(init_data, keep_blank_values=True)
            user_raw = parsed.get("user", [None])[0]
            if user_raw:
                user = json.loads(user_raw)
                uid = user.get("id")
                if uid is not None:
                    return f"user:{uid}"
        except (ValueError, KeyError, json.JSONDecodeError):
            pass
    return f"ip:{get_remote_address(request)}"


limiter = Limiter(
    key_func=_user_key,
    storage_uri=settings.rate_limit_storage_uri,
    # headers_enabled would inject X-RateLimit-* headers into the endpoint's
    # response, but only if every decorated endpoint declares a
    # `response: Response` parameter — otherwise slowapi raises on every call.
    # We don't expose those headers to clients, so keep this off.
    headers_enabled=False,
)
