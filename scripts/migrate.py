"""
Migration bootstrap script.

Handles the one-time transition from create_all (main branch) to Alembic (develop).

If the database already has tables but no alembic_version table, it means
the schema was created by SQLAlchemy's create_all. In that case we stamp
the migration history as 'head' (marking all migrations as applied without
running them) so that future migrations apply cleanly.
"""

import subprocess
import sys

from sqlalchemy import create_engine, inspect, text

from app.core.config import settings


def sync_url(url: str) -> str:
    """Convert async driver URL to sync for inspection."""
    return url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "sqlite+aiosqlite://", "sqlite://"
    )


def main() -> None:
    engine = create_engine(sync_url(settings.database_url))

    with engine.connect() as conn:
        inspector = inspect(conn)
        tables = set(inspector.get_table_names())
        has_alembic = "alembic_version" in tables
        has_schema = "users" in tables

    engine.dispose()

    if has_schema and not has_alembic:
        print("Existing schema detected without Alembic version table — stamping head.")
        result = subprocess.run(["alembic", "stamp", "head"], check=True)
        print("Stamped.")

    print("Running alembic upgrade head...")
    subprocess.run(["alembic", "upgrade", "head"], check=True)
    print("Migrations complete.")


if __name__ == "__main__":
    main()
