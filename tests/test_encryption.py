"""security tests for the encryption module (kdf / cipher / envelope / vault).

this protects papers the user chose to encrypt, so the tests assert the security
properties directly: keys are deterministic in the password+salt but diverge when
either changes, GCM authentication rejects wrong keys and tampering, the on-disk
envelope round-trips and rejects malformed input, and the public vault surface
raises a clean WrongPasswordError rather than leaking why.

KDF cost is patched down to argon2's minimum so the suite stays fast; production
cost lives in kdf.py and is unaffected.
"""

import pytest

from domain.encryption import cipher, kdf
from domain.encryption.cipher import DecryptionError
from domain.encryption.envelope import Envelope, EnvelopeFormatError, FORMAT_VERSION
from domain.encryption.kdf import KdfParams, derive_key, generate_salt
from domain.encryption.vault import (
    WrongPasswordError,
    decrypt_paper,
    encrypt_paper,
)

FAST = KdfParams(time_cost=1, memory_cost_kib=8, parallelism=1)


@pytest.fixture
def fast_kdf(monkeypatch):
    """patch the module-level cost constants so current_defaults() is cheap."""
    monkeypatch.setattr(kdf, "TIME_COST", 1)
    monkeypatch.setattr(kdf, "MEMORY_COST_KIB", 8)
    monkeypatch.setattr(kdf, "PARALLELISM", 1)


# ─────────────────────────────── kdf ─────────────────────────────────────
class TestKdf:
    def test_salt_is_16_random_bytes(self):
        s1, s2 = generate_salt(), generate_salt()
        assert len(s1) == 16 and len(s2) == 16
        assert s1 != s2  # cryptographically random -> practically never equal

    def test_key_is_32_bytes(self):
        assert len(derive_key("pw", generate_salt(), FAST)) == 32

    def test_same_inputs_are_deterministic(self):
        salt = generate_salt()
        assert derive_key("pw", salt, FAST) == derive_key("pw", salt, FAST)

    def test_different_salt_changes_key(self):
        assert derive_key("pw", generate_salt(), FAST) != derive_key("pw", generate_salt(), FAST)

    def test_different_password_changes_key(self):
        salt = generate_salt()
        assert derive_key("pw-a", salt, FAST) != derive_key("pw-b", salt, FAST)

    def test_current_defaults_are_strong(self):
        d = KdfParams.current_defaults()
        # the shipped params must stay expensive enough to matter
        assert d.memory_cost_kib >= 19456  # OWASP argon2id floor
        assert d.time_cost >= 2


# ────────────────────────────── cipher ───────────────────────────────────
class TestCipher:
    def _key(self):
        return derive_key("pw", generate_salt(), FAST)

    def test_round_trip(self):
        key, nonce = self._key(), cipher.generate_nonce()
        ct = cipher.encrypt(key, nonce, b"secret bytes")
        assert cipher.decrypt(key, nonce, ct) == b"secret bytes"

    def test_nonce_is_12_bytes(self):
        assert len(cipher.generate_nonce()) == 12

    def test_ciphertext_carries_16_byte_tag(self):
        key, nonce = self._key(), cipher.generate_nonce()
        ct = cipher.encrypt(key, nonce, b"1234")
        assert len(ct) == len(b"1234") + 16  # GCM appends a 16-byte auth tag

    def test_empty_plaintext_round_trips(self):
        key, nonce = self._key(), cipher.generate_nonce()
        assert cipher.decrypt(key, nonce, cipher.encrypt(key, nonce, b"")) == b""

    def test_wrong_key_raises(self):
        nonce = cipher.generate_nonce()
        ct = cipher.encrypt(self._key(), nonce, b"data")
        with pytest.raises(DecryptionError):
            cipher.decrypt(self._key(), nonce, ct)  # a different key

    def test_tampered_ciphertext_raises(self):
        key, nonce = self._key(), cipher.generate_nonce()
        ct = bytearray(cipher.encrypt(key, nonce, b"data"))
        ct[0] ^= 0x01  # flip one bit
        with pytest.raises(DecryptionError):
            cipher.decrypt(key, nonce, bytes(ct))

    def test_wrong_nonce_raises(self):
        key = self._key()
        ct = cipher.encrypt(key, cipher.generate_nonce(), b"data")
        with pytest.raises(DecryptionError):
            cipher.decrypt(key, cipher.generate_nonce(), ct)


# ───────────────────────────── envelope ──────────────────────────────────
class TestEnvelope:
    def _envelope(self):
        return Envelope(kdf_params=FAST, salt=b"s" * 16, nonce=b"n" * 12, ciphertext=b"ct-bytes")

    def test_round_trip(self):
        env = self._envelope()
        parsed = Envelope.from_string(env.to_string())
        assert parsed.salt == env.salt
        assert parsed.nonce == env.nonce
        assert parsed.ciphertext == env.ciphertext
        assert parsed.kdf_params == env.kdf_params

    def test_string_format(self):
        s = self._envelope().to_string()
        assert s.startswith(FORMAT_VERSION + ".")
        assert len(s.split(".")) == 7

    def test_uses_urlsafe_base64(self):
        # url-safe alphabet has no '+' or '/' that could clash with the separator
        env = Envelope(kdf_params=FAST, salt=bytes(range(16)), nonce=bytes(range(12)),
                       ciphertext=bytes(range(255)))
        s = env.to_string()
        assert "+" not in s and "/" not in s

    def test_wrong_field_count_raises(self):
        with pytest.raises(EnvelopeFormatError):
            Envelope.from_string("TSENC1.1.8.1.only.four")

    def test_wrong_version_raises(self):
        good = self._envelope().to_string().split(".", 1)[1]
        with pytest.raises(EnvelopeFormatError):
            Envelope.from_string("TSENC9." + good)

    def test_bad_base64_raises(self):
        with pytest.raises(EnvelopeFormatError):
            Envelope.from_string("TSENC1.1.8.1.!!!bad!!!.nonce.ct")

    def test_non_integer_params_raise(self):
        with pytest.raises(EnvelopeFormatError):
            Envelope.from_string("TSENC1.x.8.1.c2FsdA==.bm9uY2U=.Y3Q=")


# ─────────────────────────────── vault ───────────────────────────────────
class TestVault:
    def test_round_trip(self, fast_kdf):
        env = encrypt_paper("my secret paper", "hunter2")
        assert decrypt_paper(env, "hunter2") == "my secret paper"

    def test_unicode_round_trips(self, fast_kdf):
        text = "café ∑ 研究 🔬 formulæ"
        assert decrypt_paper(encrypt_paper(text, "pw"), "pw") == text

    def test_empty_paper_round_trips(self, fast_kdf):
        assert decrypt_paper(encrypt_paper("", "pw"), "pw") == ""

    def test_wrong_password_raises(self, fast_kdf):
        env = encrypt_paper("secret", "correct-horse")
        with pytest.raises(WrongPasswordError):
            decrypt_paper(env, "wrong-password")

    def test_same_text_encrypts_differently_each_time(self, fast_kdf):
        # fresh salt + nonce per call -> identical plaintext yields distinct output
        assert encrypt_paper("same", "pw") != encrypt_paper("same", "pw")

    def test_malformed_envelope_raises_format_error(self, fast_kdf):
        with pytest.raises(EnvelopeFormatError):
            decrypt_paper("not-a-valid-envelope", "pw")

    def test_tampered_envelope_is_rejected(self, fast_kdf):
        env = encrypt_paper("secret", "pw")
        # corrupt the ciphertext field (last dot-separated field)
        head, ct = env.rsplit(".", 1)
        tampered_ct = ("A" if ct[0] != "A" else "B") + ct[1:]
        with pytest.raises((WrongPasswordError, EnvelopeFormatError)):
            decrypt_paper(head + "." + tampered_ct, "pw")
