"""Add UNIQUE constraint on one_time_keys(user_id, key_id).

A duplicate (user_id, key_id) row would let the same OTK be "popped" twice and
break X3DH session setup downstream. Before adding the constraint we
deduplicate any pre-existing rows by keeping the lowest id per (user_id, key_id).

Revision ID: 006_otk_unique_constraint
Revises: 005_username_lower_index
Create Date: 2026-05-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "006_otk_unique_constraint"
down_revision: str | None = "005_username_lower_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop any pre-existing duplicates (keep the earliest id per pair).
    op.execute(
        """
        DELETE FROM one_time_keys
        WHERE id NOT IN (
            SELECT MIN(id)
            FROM one_time_keys
            GROUP BY user_id, key_id
        )
        """
    )
    op.create_unique_constraint(
        "uq_otk_user_keyid",
        "one_time_keys",
        ["user_id", "key_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_otk_user_keyid", "one_time_keys", type_="unique")
