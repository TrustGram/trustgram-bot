"""
Application configuration loaded from environment variables.

Uses pydantic-settings for type-safe validation with .env file support.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central settings — one source of truth for every config knob."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Telegram ──────────────────────────────────────────────
    bot_token: str
    webapp_url: str

    # ── Database ──────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./trustgram.db"

    # ── API ───────────────────────────────────────────────────
    api_v1_prefix: str = "/api/v1"
    project_name: str = "TrustGram"
    debug: bool = False


settings = Settings()  # type: ignore[call-arg]
