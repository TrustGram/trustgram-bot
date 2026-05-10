"""Initial schema — users, public_bundles, one_time_keys, messages.

Revision ID: 001_initial
Revises: None
Create Date: 2026-05-10
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── users ─────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column(
            "registration_date",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("telegram_id"),
    )
    op.create_index(
        op.f("ix_users_telegram_id"), "users", ["telegram_id"], unique=False
    )

    # ── public_bundles ────────────────────────────────────────
    op.create_table(
        "public_bundles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("identity_key", sa.Text(), nullable=False),
        sa.Column("signed_pre_key", sa.Text(), nullable=False),
        sa.Column("signature", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.telegram_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index(
        op.f("ix_public_bundles_user_id"),
        "public_bundles",
        ["user_id"],
        unique=True,
    )

    # ── one_time_keys ─────────────────────────────────────────
    op.create_table(
        "one_time_keys",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("key_id", sa.String(length=255), nullable=False),
        sa.Column("public_key", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.telegram_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_one_time_keys_user_id"),
        "one_time_keys",
        ["user_id"],
        unique=False,
    )

    # ── messages ──────────────────────────────────────────────
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("recipient_id", sa.BigInteger(), nullable=False),
        sa.Column("sender_id", sa.BigInteger(), nullable=False),
        sa.Column("encrypted_payload", sa.Text(), nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id"],
            ["users.telegram_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_messages_recipient_id"),
        "messages",
        ["recipient_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_messages_recipient_id"), table_name="messages")
    op.drop_table("messages")
    op.drop_index(
        op.f("ix_one_time_keys_user_id"), table_name="one_time_keys"
    )
    op.drop_table("one_time_keys")
    op.drop_index(
        op.f("ix_public_bundles_user_id"), table_name="public_bundles"
    )
    op.drop_table("public_bundles")
    op.drop_index(op.f("ix_users_telegram_id"), table_name="users")
    op.drop_table("users")
