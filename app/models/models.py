"""
SQLAlchemy ORM models for TrustGram.

Schema mirrors the README spec:
  - Users           — Telegram users who have registered.
  - PublicBundles    — X3DH identity + signed pre-key per user.
  - OneTimeKeys     — Expendable one-time pre-keys (consumed on first use).
  - Messages        — Store-and-forward encrypted blobs (the "inbox").
  - SessionRequests — Pending chat initiation requests.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class User(Base):
    """
    A registered TrustGram user, identified by their Telegram ID.
    """

    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, index=True,
    )
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    registration_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    # ── Relationships ─────────────────────────────────────────
    bundle: Mapped["PublicBundle | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan",
    )
    one_time_keys: Mapped[list["OneTimeKey"]] = relationship(
        back_populates="user", cascade="all, delete-orphan",
    )


class PublicBundle(Base):
    """
    X3DH public bundle for a user — identity key, signed pre-key, and
    the signature proving the signed pre-key belongs to the identity.

    One row per user.  Replaced when the user rotates their signed pre-key.
    """

    __tablename__ = "public_bundles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"),
        unique=True, index=True,
    )
    identity_key: Mapped[str] = mapped_column(Text, nullable=False)
    signed_pre_key: Mapped[str] = mapped_column(Text, nullable=False)
    signature: Mapped[str] = mapped_column(Text, nullable=False)

    # ── Relationships ─────────────────────────────────────────
    user: Mapped["User"] = relationship(back_populates="bundle")


class OneTimeKey(Base):
    """
    Expendable one-time pre-key.  Each key is consumed exactly once when
    someone initiates an X3DH session.

    The client uploads a batch; the server hands them out and deletes them.
    """

    __tablename__ = "one_time_keys"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"),
        index=True,
    )
    key_id: Mapped[str] = mapped_column(String(255), nullable=False)
    public_key: Mapped[str] = mapped_column(Text, nullable=False)

    # ── Relationships ─────────────────────────────────────────
    user: Mapped["User"] = relationship(back_populates="one_time_keys")


class Message(Base):
    """
    An encrypted message blob sitting in a recipient's inbox.

    The server never inspects `encrypted_payload` — it's opaque ciphertext
    produced by `trustgram-crypto` on the sender's device.
    """

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    recipient_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"),
        index=True,
    )
    sender_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    encrypted_payload: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class SessionRequest(Base):
    """
    Pending chat initiation request.

    Alice calls POST /session/init to create one; Bob sees it via
    GET /session/pending and can accept or decline.
    """

    __tablename__ = "session_requests"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    from_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    to_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), index=True,
    )
    from_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
