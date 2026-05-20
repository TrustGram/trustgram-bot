"""Reset all user data + ensure signing_key column exists.

Recovery migration after a botched 003 rollout where the new signing_key
column didn't actually land in production but some stale bundles remained.
Wipes all user data (still in early dev, no users to preserve) and adds
signing_key idempotently so a fresh registration round can proceed.

Revision ID: 004_reset_data
Revises: 003_add_signing_key
Create Date: 2026-05-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "004_reset_data"
down_revision: str | None = "003_add_signing_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Wipe all data (FK CASCADE makes order forgiving, but be explicit).
    op.execute("DELETE FROM messages")
    op.execute("DELETE FROM one_time_keys")
    op.execute("DELETE FROM public_bundles")
    op.execute("DELETE FROM users")

    # Add signing_key if 003 didn't actually land — Postgres ≥ 9.6.
    op.execute("ALTER TABLE public_bundles ADD COLUMN IF NOT EXISTS signing_key TEXT NOT NULL")


def downgrade() -> None:
    # Data wipe is irreversible; column drop mirrors 003's downgrade.
    op.execute("ALTER TABLE public_bundles DROP COLUMN IF EXISTS signing_key")
