"""
Unit tests for app/core/spk_verify.py.

Integration tests in tests/integration/test_api_keys.py already exercise the
happy path and the most common rejection (a single-byte-flipped signature).
This file pins down the boundary cases that the integration tests don't reach:
malformed base64, wrong signature length, signing key on the wrong curve, etc.
"""

import base64

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

from app.core.spk_verify import verify_spk_signature


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def _signed_bundle() -> tuple[str, str, str]:
    """Return (signing_key_b64, spk_b64, signature_b64) — all valid."""
    signing = ec.generate_private_key(ec.SECP256R1())
    spk_priv = ec.generate_private_key(ec.SECP256R1())
    spk_raw = spk_priv.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    der = signing.sign(spk_raw, ec.ECDSA(hashes.SHA256()))
    r, s = utils.decode_dss_signature(der)
    sig_raw = r.to_bytes(32, "big") + s.to_bytes(32, "big")

    spki = signing.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return _b64(spki), _b64(spk_raw), _b64(sig_raw)


class TestHappyPath:
    def test_valid_signature_verifies(self):
        sk, spk, sig = _signed_bundle()
        assert verify_spk_signature(sk, spk, sig) is True


class TestMalformedInputs:
    def test_signing_key_not_base64(self):
        _, spk, sig = _signed_bundle()
        assert verify_spk_signature("not!base64!", spk, sig) is False

    def test_spk_not_base64(self):
        sk, _, sig = _signed_bundle()
        assert verify_spk_signature(sk, "not!base64!", sig) is False

    def test_signature_not_base64(self):
        sk, spk, _ = _signed_bundle()
        assert verify_spk_signature(sk, spk, "not!base64!") is False

    def test_signing_key_garbage_bytes(self):
        """Base64-valid string, but not a parseable SPKI DER."""
        sk, spk, sig = _signed_bundle()
        assert verify_spk_signature(_b64(b"definitely not SPKI"), spk, sig) is False


class TestWrongSignatureLength:
    def test_too_short(self):
        sk, spk, _ = _signed_bundle()
        # 63 bytes — one short of the required raw r||s width.
        assert verify_spk_signature(sk, spk, _b64(b"\x00" * 63)) is False

    def test_too_long(self):
        sk, spk, _ = _signed_bundle()
        assert verify_spk_signature(sk, spk, _b64(b"\x00" * 65)) is False


class TestWrongKeyType:
    def test_rsa_signing_key_rejected(self):
        """An RSA public key in the signing_key slot must not be accepted."""
        from cryptography.hazmat.primitives.asymmetric import rsa

        rsa_priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        rsa_spki = rsa_priv.public_key().public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        _, spk, sig = _signed_bundle()
        assert verify_spk_signature(_b64(rsa_spki), spk, sig) is False

    def test_p384_signing_key_rejected(self):
        """A valid EC key but on the wrong curve (P-384) — must reject."""
        wrong_curve = ec.generate_private_key(ec.SECP384R1())
        spki = wrong_curve.public_key().public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        _, spk, sig = _signed_bundle()
        assert verify_spk_signature(_b64(spki), spk, sig) is False


class TestSignatureForgery:
    def test_signature_for_different_spk_rejected(self):
        """Replay a signature from a different SPK — must reject."""
        sk, spk1, sig1 = _signed_bundle()
        _, spk2, _ = _signed_bundle()
        # sig1 was over spk1's raw bytes; ask the verifier to check it against spk2.
        assert verify_spk_signature(sk, spk2, sig1) is False

    def test_signature_by_different_signer_rejected(self):
        """Same SPK but signed by a stranger — must reject."""
        sk1, spk, _ = _signed_bundle()
        # Sign the SAME spk with a different key.
        attacker = ec.generate_private_key(ec.SECP256R1())
        spk_raw = base64.b64decode(spk)
        der = attacker.sign(spk_raw, ec.ECDSA(hashes.SHA256()))
        r, s = utils.decode_dss_signature(der)
        forged = _b64(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
        assert verify_spk_signature(sk1, spk, forged) is False


@pytest.mark.parametrize("byte_index", [0, 31, 32, 63])
def test_single_byte_flip_breaks_signature(byte_index: int):
    sk, spk, sig = _signed_bundle()
    sig_raw = bytearray(base64.b64decode(sig))
    sig_raw[byte_index] ^= 0x01
    assert verify_spk_signature(sk, spk, _b64(bytes(sig_raw))) is False
