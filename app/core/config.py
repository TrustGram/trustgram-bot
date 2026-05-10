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
    # ── Logging ───────────────────────────────────────────────
    log_level: str = "INFO"
    log_format: str = "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d - %(message)s"
    log_file_path: str = "logs/trustgram.log"
    log_to_file: bool = True
    log_to_console: bool = True

    debug: bool = False


settings = Settings()  # type: ignore[call-arg]
