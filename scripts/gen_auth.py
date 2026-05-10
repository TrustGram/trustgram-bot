#!/usr/bin/env python3
"""
TrustGram CLI Auth Generator

This utility generates valid Telegram `initData` strings for local API testing.
It uses the project's `BOT_TOKEN` to compute the HMAC-SHA256 signature required
 by the backend's security layer.

Usage:
    python scripts/gen_auth.py --id 12345 --username dev_user
"""

import argparse
import hashlib
import hmac
import json
import os
import sys
import time
from urllib.parse import quote, urlencode

from dotenv import load_dotenv


def generate_init_data(bot_token: str, user_id: int, username: str = None, 
                       first_name: str = "Dev", last_name: str = "User", 
                       auth_date: int = None) -> str:
    """
    Constructs a valid Telegram initData string and signs it.
    """
    if auth_date is None:
        auth_date = int(time.time())

    user_data = {
        "id": user_id,
        "first_name": first_name,
        "last_name": last_name,
    }
    if username:
        user_data["username"] = username

    # 1. Prepare fields (excluding hash)
    fields = {
        "auth_date": str(auth_date),
        "user": json.dumps(user_data, separators=(",", ":")),
    }

    # 2. Build data-check string: sorted key=value pairs joined by newlines
    data_check_parts = sorted(f"{k}={v}" for k, v in fields.items())
    data_check_string = "\n".join(data_check_parts)

    # 3. Compute secret key: HMAC-SHA256("WebAppData", bot_token)
    secret_key = hmac.new(
        b"WebAppData", bot_token.encode(), hashlib.sha256
    ).digest()

    # 4. Compute hash: HMAC-SHA256(secret_key, data_check_string)
    data_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    # 5. Build final query string
    fields["hash"] = data_hash
    
    # We use urlencode but we need to ensure the order doesn't matter for the final string
    # though Telegram usually sends them as they were constructed.
    return urlencode(fields)


def main():
    parser = argparse.ArgumentParser(
        description="Generate a valid X-Init-Data header for TrustGram API testing.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Example:\n  python scripts/gen_auth.py -i 12345 -u dev_tester"
    )
    
    parser.add_argument("-i", "--user-id", type=int, required=True, 
                        help="Telegram User ID (e.g., 12345678)")
    parser.add_argument("-u", "--username", type=str, 
                        help="Telegram username (without @)")
    parser.add_argument("-f", "--first-name", type=str, default="Dev",
                        help="User first name (default: Dev)")
    parser.add_argument("-l", "--last-name", type=str, default="User",
                        help="User last name (default: User)")
    parser.add_argument("-d", "--auth-date", type=int,
                        help="Unix timestamp for auth_date (defaults to now)")
    parser.add_argument("--env", type=str, default=".env",
                        help="Path to .env file (default: .env)")

    args = parser.parse_args()

    # Load environment variables
    if not os.path.exists(args.env):
        print(f"Error: Environment file '{args.env}' not found.", file=sys.stderr)
        sys.exit(1)
    
    load_dotenv(args.env)
    bot_token = os.getenv("BOT_TOKEN")

    if not bot_token:
        print("Error: BOT_TOKEN not found in environment.", file=sys.stderr)
        sys.exit(1)

    try:
        init_data = generate_init_data(
            bot_token=bot_token,
            user_id=args.user_id,
            username=args.username,
            first_name=args.first_name,
            last_name=args.last_name,
            auth_date=args.auth_date
        )
        print("\nGenerated X-Init-Data:\n")
        print(init_data)
        print("\n" + "-"*40)
        print("Copy the string above and use it in the 'X-Init-Data' header.")
    except Exception as e:
        print(f"Error generating initData: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
