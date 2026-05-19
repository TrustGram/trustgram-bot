"""Fix auto-increment sequences for id columns.

The initial migration created id columns as plain INTEGER NOT NULL without a
SERIAL/IDENTITY sequence, because the primary key was declared via
PrimaryKeyConstraint rather than primary_key=True on the column. This caused
every INSERT to land with id=1 after the previous row was deleted (and would
fail with a unique-key violation if the previous row was still present),
making messages collide in the client cache.

This migration attaches proper sequences to the existing tables and resets
each sequence past the current MAX(id) so future INSERTs auto-generate.

Revision ID: 002_fix_id_autoincrement
Revises: 001_initial
Create Date: 2026-05-19
"""

from collections.abc import Sequence

from alembic import op

revision: str = "002_fix_id_autoincrement"
down_revision: str | None = "001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TABLES = ("messages", "one_time_keys", "public_bundles")


def upgrade() -> None:
    for table in _TABLES:
        seq = f"{table}_id_seq"
        op.execute(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_class WHERE relname = '{seq}') THEN
                    CREATE SEQUENCE {seq} OWNED BY {table}.id;
                END IF;
            END$$;
            """
        )
        op.execute(f"ALTER TABLE {table} ALTER COLUMN id SET DEFAULT nextval('{seq}')")
        op.execute(f"SELECT setval('{seq}', COALESCE((SELECT MAX(id) FROM {table}), 0) + 1, false)")


def downgrade() -> None:
    for table in _TABLES:
        seq = f"{table}_id_seq"
        op.execute(f"ALTER TABLE {table} ALTER COLUMN id DROP DEFAULT")
        op.execute(f"DROP SEQUENCE IF EXISTS {seq}")
