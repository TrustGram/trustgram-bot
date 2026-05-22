"""
Pydantic schemas for request / response validation.

All public-key material is represented as base64-encoded strings (JWK or raw).
The server treats them as opaque — no parsing, no validation beyond presence.
"""

from datetime import datetime

from pydantic import BaseModel, Field, field_serializer

# ═══════════════════════════════════════════════════════════════
# Size limits
# ═══════════════════════════════════════════════════════════════
# Public keys are base64(P-256 raw) ≈ 88 bytes; allow some slack for JWK/future curves.
KEY_MAX_LEN = 512
KEY_ID_MAX_LEN = 64
# ECDSA P-256 raw signature is 64 bytes → 88 base64; SPKI public key ≈ 124 base64. Allow slack.
SIGNATURE_MAX_LEN = 256
SIGNATURE_MIN_LEN = 64
# Files capped at 512 KB in the UI. After deflate + base64 + JSON wrap ≈ 720 KB of
# plaintext, which after bucket padding (H4) rounds up to a 1 MiB plaintext bucket;
# the resulting AES-GCM ciphertext base64'd lands at ≈ 1.4 MiB. 2 MiB cap leaves
# headroom for the JSON envelope and future bucket growth without rejecting valid
# clients.
PAYLOAD_MAX_LEN = 2_097_152
OTK_BATCH_MAX = 100


# ═══════════════════════════════════════════════════════════════
# Key Management
# ═══════════════════════════════════════════════════════════════


class OneTimeKeySchema(BaseModel):
    """A single one-time pre-key for X3DH."""

    key_id: str = Field(min_length=1, max_length=KEY_ID_MAX_LEN)
    public_key: str = Field(min_length=1, max_length=KEY_MAX_LEN)


class RegisterBundleRequest(BaseModel):
    """POST /keys/register — initial public bundle upload."""

    identity_key: str = Field(min_length=1, max_length=KEY_MAX_LEN)
    signing_key: str = Field(min_length=1, max_length=KEY_MAX_LEN)
    signed_pre_key: str = Field(min_length=1, max_length=KEY_MAX_LEN)
    signature: str = Field(min_length=SIGNATURE_MIN_LEN, max_length=SIGNATURE_MAX_LEN)
    one_time_keys: list[OneTimeKeySchema] = Field(default_factory=list, max_length=OTK_BATCH_MAX)


class PublicBundleResponse(BaseModel):
    """GET /keys/{telegram_id} — Bob's public bundle for session setup."""

    telegram_id: int
    telegram_username: str | None = None
    identity_key: str
    signing_key: str
    signed_pre_key: str
    signature: str
    one_time_key: OneTimeKeySchema | None = None


class RefillOTKRequest(BaseModel):
    """POST /keys/otk — replenish one-time pre-keys."""

    one_time_keys: list[OneTimeKeySchema] = Field(min_length=1, max_length=OTK_BATCH_MAX)


class OTKCountResponse(BaseModel):
    """GET /keys/otk/count — how many OTKs are left on the server."""

    count: int


class UpdateSPKRequest(BaseModel):
    """PUT /keys/spk — rotate signed pre-key without touching OTKs."""

    signed_pre_key: str = Field(min_length=1, max_length=KEY_MAX_LEN)
    signature: str = Field(min_length=SIGNATURE_MIN_LEN, max_length=SIGNATURE_MAX_LEN)


# ═══════════════════════════════════════════════════════════════
# Messaging
# ═══════════════════════════════════════════════════════════════


class SendMessageRequest(BaseModel):
    """POST /chat/send — deliver an encrypted blob."""

    recipient_id: int
    encrypted_payload: str = Field(min_length=1, max_length=PAYLOAD_MAX_LEN)


class MessageResponse(BaseModel):
    """A single encrypted message returned from the inbox."""

    id: int
    sender_id: int
    sender_username: str | None = None
    encrypted_payload: str
    timestamp: datetime

    @field_serializer("timestamp")
    def serialize_timestamp(self, v: datetime) -> str:
        ms = v.microsecond // 1000
        return v.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


class InboxResponse(BaseModel):
    """GET /chat/inbox — all pending messages."""

    messages: list[MessageResponse]


# ═══════════════════════════════════════════════════════════════
# Generic
# ═══════════════════════════════════════════════════════════════


class StatusResponse(BaseModel):
    """Standard status response for mutations."""

    ok: bool = True
    detail: str = ""
