"""Add messages.first_fetched_at for post-fetch TTL.

GET /chat/inbox stamps this column the first time a row is delivered to its
recipient. The cleanup sweeper then expires stamped rows after a short window
(currently 1 hour) instead of waiting for the full 30-day "never opened the
app" TTL. Reduces server-side exposure for messages whose recipient saw them
but never got to call DELETE (crash, kill -9, network drop mid-decrypt).

Nullable — pre-existing rows haven't been fetched yet (or were, but the server
didn't know to record it). They keep the old long-TTL behaviour until they're
actually fetched again.

Revision ID: 008_messages_first_fetched_at
Revises: 007_messages_inbox_index
Create Date: 2026-05-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "008_messages_first_fetched_at"
down_revision: str | None = "007_messages_inbox_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("first_fetched_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "first_fetched_at")
