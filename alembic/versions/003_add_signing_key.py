"""Add signing_key column to public_bundles.

The original schema lacked a dedicated signature-verification key, so SPK
signatures were never actually verifiable end-to-end. This migration adds an
ECDSA P-256 signing public key (base64 SPKI) alongside the ECDH identity key.

Existing rows are wiped: bundles without a signing key cannot produce a
verifiable SPK signature, so clients must re-register. OTKs and stored
messages are cascade-deleted via FK constraints.

Revision ID: 003_add_signing_key
Revises: 002_fix_id_autoincrement
Create Date: 2026-05-20
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "003_add_signing_key"
down_revision: str | None = "002_fix_id_autoincrement"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Wipe stale bundles — none of them carry a verifiable SPK signature,
    # and the new NOT NULL signing_key cannot be back-filled.
    op.execute("DELETE FROM one_time_keys")
    op.execute("DELETE FROM public_bundles")
    op.add_column(
        "public_bundles",
        sa.Column("signing_key", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("public_bundles", "signing_key")
