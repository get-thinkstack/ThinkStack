"""AES-256-GCM, authenticated encryption.

Encrypting also produces an authentication tag. Decrypting with the wrong key,
or with tampered bytes, fails that tag check loudly instead of returning
corrupted plaintext.
"""

import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_LENGTH_BYTES = 12


class DecryptionError(Exception):
    """raised when decryption fails: wrong password, corrupted data,
    or tampered ciphertext. deliberately doesn't distinguish which --
    telling an attacker *why* it failed leaks information.
    """


def generate_nonce() -> bytes:
    """generate a fresh random nonce. must never be reused with the
    same key -- generating it fresh every call is what guarantees that.
    """
    return os.urandom(NONCE_LENGTH_BYTES)


def encrypt(key: bytes, nonce: bytes, plaintext: bytes) -> bytes:
    """Ciphertext with the 16-byte auth tag appended (AESGCM's layout).

    `key` is 32 bytes (kdf.derive_key); `nonce` is 12 bytes and must never be
    reused with the same key.
    """
    aesgcm = AESGCM(key)
    return aesgcm.encrypt(nonce, plaintext, associated_data=None)


def decrypt(key: bytes, nonce: bytes, ciphertext: bytes) -> bytes:
    """The plaintext, or DecryptionError if the key is wrong or the bytes
    were tampered with. The right key means the same password AND salt."""
    aesgcm = AESGCM(key)
    try:
        return aesgcm.decrypt(nonce, ciphertext, associated_data=None)
    except InvalidTag as exc:
        raise DecryptionError(
            "decryption failed: wrong password or corrupted data"
        ) from exc
