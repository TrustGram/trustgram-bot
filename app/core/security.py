"""
Telegram WebApp `initData` validation.

Every Mini App request carries an `initData` query-string that is HMAC-signed
by Telegram.  We verify that signature here so that no unauthenticated request
can reach the API.

Reference: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""

import hashlib
import hmac
import json
from urllib.parse import parse_qs

from fastapi import Header, HTTPException, status

from app.core.config import settings


def _validate_init_data(init_data: str) -> dict:
    """
    Validate the Telegram `initData` string and return the parsed user info.

    Steps
    -----
    1. Parse the query-string.
    2. Build the data-check string (sorted key=value, excluding `hash`).
    3. HMAC-SHA256 with secret_key = HMAC-SHA256("WebAppData", bot_token).
    4. Compare against the received `hash`.

    Returns the parsed `user` dict on success.
    Raises ``HTTPException(403)`` on failure.
    """
    parsed = parse_qs(init_data, keep_blank_values=True)

    received_hash = parsed.pop("hash", [None])[0]
    if not received_hash:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing hash in initData",
        )

    # Build the check-string: sorted key=value pairs joined by newlines.
    data_check_parts = sorted(f"{k}={v[0]}" for k, v in parsed.items())
    data_check_string = "\n".join(data_check_parts)

    # Two-stage HMAC per Telegram specification.
    secret_key = hmac.new(b"WebAppData", settings.bot_token.encode(), hashlib.sha256).digest()

    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid initData signature",
        )

    # Extract user object.
    user_raw = parsed.get("user", [None])[0]
    if not user_raw:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No user payload in initData",
        )

    return json.loads(user_raw)


async def get_current_user(
    x_init_data: str | None = Header(None, alias="X-Init-Data"),
) -> dict:
    """
    FastAPI dependency that extracts and validates the Telegram user.
    """
    if not x_init_data:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing X-Init-Data header",
        )

    return _validate_init_data(x_init_data)
