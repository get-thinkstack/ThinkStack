"""
vault module.

the public surface of the encryption system. this is the only module
the rest of the app (api routes, tauri commands) should import from --
kdf.py, cipher.py, and envelope.py are internal building blocks.
"""

from domain.encryption import cipher, kdf
from domain.encryption.envelope import Envelope


class WrongPasswordError(Exception):
    """the password did not match the one used to encrypt this paper."""


def encrypt_paper(plaintext: str, password: str) -> str:
    """encrypt a paper's text into a TSENC1 envelope string.

    args:
        plaintext: the paper's text content.
        password: the password chosen to protect this paper. used
            once here to derive a key, then it goes out of scope --
            it is never itself stored anywhere.

    returns:
        a self-contained envelope string. store this; it's all you
        need (plus the password) to decrypt later.
    """
    params = kdf.KdfParams.current_defaults()
    salt = kdf.generate_salt()
    key = kdf.derive_key(password, salt, params)

    nonce = cipher.generate_nonce()
    ciphertext = cipher.encrypt(key, nonce, plaintext.encode("utf-8"))

    envelope = Envelope(
        kdf_params=params,
        salt=salt,
        nonce=nonce,
        ciphertext=ciphertext,
    )
    return envelope.to_string()


def decrypt_paper(envelope_string: str, password: str) -> str:
    """decrypt a TSENC1 envelope string back into the original text.

    args:
        envelope_string: the string produced by encrypt_paper.
        password: the password to try.

    returns:
        the original plaintext.

    raises:
        WrongPasswordError: the password doesn't match.
        EnvelopeFormatError: the envelope string itself is malformed
            (corrupted file, wrong format version, etc).
    """
    envelope = Envelope.from_string(envelope_string)  # may raise EnvelopeFormatError
    key = kdf.derive_key(password, envelope.salt, envelope.kdf_params)

    try:
        plaintext_bytes = cipher.decrypt(key, envelope.nonce, envelope.ciphertext)
    except cipher.DecryptionError as exc:
        raise WrongPasswordError("incorrect password") from exc

    return plaintext_bytes.decode("utf-8")
