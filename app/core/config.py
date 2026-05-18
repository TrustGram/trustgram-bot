"""
Application configuration loaded from environment variables.

Uses pydantic-settings for type-safe validation with .env file support.

Docs access is controlled by two variables:
  ENVIRONMENT   — "development" (default) or "production"
  DOCS_API_KEY  — secret header value required to access /docs, /redoc,
                  and /openapi.json when ENVIRONMENT=production.
                  Leave unset to keep docs completely inaccessible on prod.
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

    # ── CORS ──────────────────────────────────────────────────
    cors_origins: list[str] = [
        "http://localhost:5173",
        "https://trustgram-ui.pages.dev",
        "https://trustgram-ui.stacksurfer.workers.dev",
    ]
    cors_origin_regex: str = r"https://.*\.trustgram-ui\.pages\.dev"

    # ── Docs access ───────────────────────────────────────────
    environment: str = "development"  # "development" | "production"
    docs_api_key: str | None = None  # required to access /docs on prod


settings = Settings()  # type: ignore[call-arg]
