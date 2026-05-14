"""
Pydantic schemas for request / response validation.

All public-key material is represented as base64-encoded strings (JWK or raw).
The server treats them as opaque — no parsing, no validation beyond presence.
"""

from datetime import datetime

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════
# Key Management
# ═══════════════════════════════════════════════════════════════

class OneTimeKeySchema(BaseModel):
    """A single one-time pre-key for X3DH."""
    key_id: str
    public_key: str


class RegisterBundleRequest(BaseModel):
    """POST /keys/register — initial public bundle upload."""
    identity_key: str
    signed_pre_key: str
    signature: str
    one_time_keys: list[OneTimeKeySchema] = Field(default_factory=list)


class PublicBundleResponse(BaseModel):
    """GET /keys/{telegram_id} — Bob's public bundle for session setup."""
    telegram_id: int
    identity_key: str
    signed_pre_key: str
    signature: str
    one_time_key: OneTimeKeySchema | None = None


class RefillOTKRequest(BaseModel):
    """POST /keys/otk — replenish one-time pre-keys."""
    one_time_keys: list[OneTimeKeySchema] = Field(min_length=1)


# ═══════════════════════════════════════════════════════════════
# Messaging
# ═══════════════════════════════════════════════════════════════

class SendMessageRequest(BaseModel):
    """POST /chat/send — deliver an encrypted blob."""
    recipient_id: int
    encrypted_payload: str


class MessageResponse(BaseModel):
    """A single encrypted message returned from the inbox."""
    id: int
    sender_id: int
    sender_username: str | None = None
    encrypted_payload: str
    timestamp: datetime


class InboxResponse(BaseModel):
    """GET /chat/inbox — all pending messages."""
    messages: list[MessageResponse]


# ═══════════════════════════════════════════════════════════════
# Session Requests
# ═══════════════════════════════════════════════════════════════

class SessionInitRequest(BaseModel):
    """POST /session/init — send a chat request to another user."""
    to_id: int


class SessionRespondRequest(BaseModel):
    """POST /session/accept or /session/decline — respond to a request."""
    from_id: int


class SessionPendingItem(BaseModel):
    """A single pending incoming session request."""
    from_id: int
    from_username: str | None = None
    created_at: datetime


class PendingSessionsResponse(BaseModel):
    """GET /session/pending — all pending requests for current user."""
    requests: list[SessionPendingItem]


# ═══════════════════════════════════════════════════════════════
# Generic
# ═══════════════════════════════════════════════════════════════

class StatusResponse(BaseModel):
    """Standard status response for mutations."""
    ok: bool = True
    detail: str = ""
