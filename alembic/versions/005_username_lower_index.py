"""Add functional lowercase index on users.username.

The username column now stores the original case for display, but lookups are
case-insensitive (`func.lower(User.username) == needle`). Without this index
the lookup forces a sequential scan; with it, Postgres can do an index scan
on `LOWER(username)`.

Revision ID: 005_username_lower_index
Revises: 004_reset_data
Create Date: 2026-05-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "005_username_lower_index"
down_revision: str | None = "004_reset_data"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS users_username_lower_idx "
        "ON users (LOWER(username))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS users_username_lower_idx")
