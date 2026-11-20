"""The encryption package's public surface.

    encrypt_bytes / decrypt_bytes   any bytes <-> one TSENC1 string
    encrypt_paper / decrypt_paper   the same, for text
    seal_chunks / open_text         a paper's chunks, keyed by chunk id

Callers use these; kdf.py and cipher.py are internal. (The routes do import
`EnvelopeFormatError` from envelope.py to catch it.)

    encrypt: password + fresh salt -> key (kdf) -> AES-GCM with a fresh nonce
             (cipher) -> one TSENC1 string (envelope)
    decrypt: parse the string -> same params and salt -> key -> verify + decrypt
"""

import json

from domain.encryption import cipher, kdf
from domain.encryption.envelope import Envelope


class WrongPasswordError(Exception):
    """the password did not match the one used to encrypt this paper."""


def encrypt_bytes(data: bytes, password: str) -> str:
    """A self-contained TSENC1 string: with the password, all that is needed
    to decrypt. The password itself is never stored."""
    params = kdf.KdfParams.current_defaults()
    salt = kdf.generate_salt()
    key = kdf.derive_key(password, salt, params)

    nonce = cipher.generate_nonce()
    ciphertext = cipher.encrypt(key, nonce, data)

    envelope = Envelope(
        kdf_params=params,
        salt=salt,
        nonce=nonce,
        ciphertext=ciphertext,
    )
    return envelope.to_string()


def decrypt_bytes(envelope_string: str, password: str) -> bytes:
    """The original bytes. WrongPasswordError for a wrong password;
    EnvelopeFormatError for a malformed or unknown-version string."""
    envelope = Envelope.from_string(envelope_string)  # may raise EnvelopeFormatError
    key = kdf.derive_key(password, envelope.salt, envelope.kdf_params)

    try:
        return cipher.decrypt(key, envelope.nonce, envelope.ciphertext)
    except cipher.DecryptionError as exc:
        raise WrongPasswordError("incorrect password") from exc


def encrypt_paper(plaintext: str, password: str) -> str:
    return encrypt_bytes(plaintext.encode("utf-8"), password)


def decrypt_paper(envelope_string: str, password: str) -> str:
    return decrypt_bytes(envelope_string, password).decode("utf-8")


# Payload version 2 keeps every chunk's text under its id, so removing
# encryption restores the store exactly. Version 1 (before 2026-11-19) held
# only the joined text, and its chunks were never blanked.
_CHUNKS_V2 = "thinkstack-chunks-v2"


def seal_chunks(texts_by_id: dict[str, str], password: str) -> str:
    """Encrypt a paper's chunk texts, keyed by chunk id, as one envelope."""
    payload = {"format": _CHUNKS_V2, "chunks": texts_by_id}
    return encrypt_paper(json.dumps(payload, ensure_ascii=False), password)


def open_text(envelope_string: str, password: str) -> tuple[str, dict[str, str] | None]:
    """`(joined_text, texts_by_id)`; texts_by_id is None for a v1 envelope.

    Joined in chunk-id order, which is ingestion order (`<doc>_chunk_0007`).
    """
    plaintext = decrypt_paper(envelope_string, password)
    try:
        payload = json.loads(plaintext)
    except ValueError:
        return plaintext, None
    if not isinstance(payload, dict) or payload.get("format") != _CHUNKS_V2:
        return plaintext, None
    chunks = payload["chunks"]
    ordered = sorted(chunks, key=_chunk_order)
    return " ".join(chunks[i] for i in ordered), chunks


def _chunk_order(chunk_id: str):
    tail = chunk_id.rsplit("_", 1)[-1]
    return (0, int(tail)) if tail.isdigit() else (1, chunk_id)
