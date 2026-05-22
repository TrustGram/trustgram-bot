"""
SQLAlchemy ORM models for TrustGram.

  - Users          — Telegram users who have registered.
  - PublicBundles  — X3DH identity + signed pre-key per user.
  - OneTimeKeys    — Expendable one-time pre-keys (consumed on first use).
  - Messages       — Store-and-forward encrypted blobs (the "inbox").
"""

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    registration_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    bundle: Mapped["PublicBundle | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    one_time_keys: Mapped[list["OneTimeKey"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class PublicBundle(Base):
    __tablename__ = "public_bundles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), unique=True, index=True
    )
    identity_key: Mapped[str] = mapped_column(Text, nullable=False)
    signing_key: Mapped[str] = mapped_column(Text, nullable=False)
    signed_pre_key: Mapped[str] = mapped_column(Text, nullable=False)
    signature: Mapped[str] = mapped_column(Text, nullable=False)

    user: Mapped["User"] = relationship(back_populates="bundle")


class OneTimeKey(Base):
    __tablename__ = "one_time_keys"
    # (user_id, key_id) uniquely identifies an OTK. Without this, a buggy or
    # malicious client could insert duplicates and confuse session setup.
    __table_args__ = (UniqueConstraint("user_id", "key_id", name="uq_otk_user_keyid"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), index=True)
    key_id: Mapped[str] = mapped_column(String(255), nullable=False)
    public_key: Mapped[str] = mapped_column(Text, nullable=False)

    user: Mapped["User"] = relationship(back_populates="one_time_keys")


class Message(Base):
    __tablename__ = "messages"
    # Composite index for inbox queries (filter recipient_id, sort timestamp).
    # See migration 007_messages_inbox_index — supersedes the single-column index.
    __table_args__ = (Index("messages_inbox_idx", "recipient_id", "timestamp"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    recipient_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.telegram_id", ondelete="CASCADE"),
    )
    sender_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    encrypted_payload: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    # Set to now() the first time GET /chat/inbox returns this row. Once set,
    # the cleanup sweeper expires the row aggressively (POST_FETCH_TTL_MINUTES)
    # — the client has had a chance to decrypt, so we no longer need to hold
    # it for the full 30-day "never opened the app" window. Reduces the
    # forensic exposure if the recipient's device is lost between fetch and
    # explicit DELETE.
    first_fetched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
