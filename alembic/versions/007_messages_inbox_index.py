"""Composite index on messages(recipient_id, timestamp) for inbox queries.

GET /chat/inbox runs:
    SELECT ... FROM messages
    WHERE recipient_id = :uid
    ORDER BY timestamp ASC

The single-column index on recipient_id already gets the rows fast, but
Postgres still has to sort them. A composite index on (recipient_id, timestamp)
lets the planner return rows already ordered — important once inboxes grow.

Revision ID: 007_messages_inbox_index
Revises: 006_otk_unique_constraint
Create Date: 2026-05-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "007_messages_inbox_index"
down_revision: str | None = "006_otk_unique_constraint"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The composite supersedes the single-column index for any query that
    # filters on recipient_id (which is every inbox query).
    op.execute("CREATE INDEX IF NOT EXISTS messages_inbox_idx ON messages (recipient_id, timestamp ASC)")
    op.execute("DROP INDEX IF EXISTS ix_messages_recipient_id")


def downgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_messages_recipient_id ON messages (recipient_id)")
    op.execute("DROP INDEX IF EXISTS messages_inbox_idx")
