"""
Server-side verification of the ECDSA signature that binds a user's signed
pre-key (SPK) to their long-term signing key.

Why defence-in-depth: receivers re-verify on every fetch via WebCrypto, so a
forged bundle wouldn't fool an honest client. But without this check the
server happily stores garbage — wasting OTK pool entries, polluting storage,
and burning the sender's CPU on derive→encrypt→fail-decrypt cycles. ~10ms
of ECDSA work at registration time eliminates the whole DoS surface.

Wire format (matches WebCrypto / x3dh.ts):
  signing_key   — base64 SPKI DER of an ECDSA P-256 public key
  signed_pre_key — base64 of the raw (uncompressed, 65-byte) ECDH P-256 pubkey
  signature     — base64 of raw r||s (64 bytes, JOSE / WebCrypto format)
"""

import base64
import binascii

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

# WebCrypto ECDSA P-256 produces a fixed-width raw signature of 32-byte r || 32-byte s.
_RAW_SIG_LEN = 64


def verify_spk_signature(signing_key_b64: str, signed_pre_key_b64: str, signature_b64: str) -> bool:
    """
    Return True iff `signature_b64` is a valid ECDSA-SHA256 signature over the
    raw bytes of `signed_pre_key_b64`, produced by the private half of
    `signing_key_b64`. All inputs are base64 strings; any decoding or format
    error means "invalid signature" — we return False rather than raising so
    callers can convert into a single 400.
    """
    try:
        spki = base64.b64decode(signing_key_b64, validate=True)
        spk_bytes = base64.b64decode(signed_pre_key_b64, validate=True)
        sig_raw = base64.b64decode(signature_b64, validate=True)
    except (binascii.Error, ValueError):
        return False

    if len(sig_raw) != _RAW_SIG_LEN:
        return False

    try:
        public_key = serialization.load_der_public_key(spki)
    except (ValueError, TypeError):
        return False

    if not isinstance(public_key, ec.EllipticCurvePublicKey):
        return False
    if not isinstance(public_key.curve, ec.SECP256R1):
        return False

    # WebCrypto emits raw r||s; cryptography wants DER-encoded ECDSA-Sig-Value.
    r = int.from_bytes(sig_raw[:32], "big")
    s = int.from_bytes(sig_raw[32:], "big")
    der_sig = utils.encode_dss_signature(r, s)

    try:
        public_key.verify(der_sig, spk_bytes, ec.ECDSA(hashes.SHA256()))
        return True
    except InvalidSignature:
        return False
