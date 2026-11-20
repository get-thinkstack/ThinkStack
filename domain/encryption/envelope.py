"""The text format of an encrypted paper:

    TSENC1.<time_cost>.<memory_cost_kib>.<parallelism>.<salt_b64>.<nonce_b64>.<ciphertext_b64>

every field needed to decrypt -- except the password itself -- travels
in this one string. the version tag (TSENC1) lets the format change
later without breaking papers encrypted under an older version.
"""

import base64
from dataclasses import dataclass

from domain.encryption.kdf import KdfParams

FORMAT_VERSION = "TSENC1"
SEPARATOR = "."


class EnvelopeFormatError(Exception):
    """raised when a string doesn't parse as a valid envelope --
    wrong version tag, missing fields, or invalid base64.
    """


@dataclass(frozen=True)
class Envelope:
    """the parsed contents of an encrypted-paper string."""
    kdf_params: KdfParams
    salt: bytes
    nonce: bytes
    ciphertext: bytes

    def to_string(self) -> str:
        """serialize this envelope into the textual TSENC1 format."""
        fields = [
            FORMAT_VERSION,
            str(self.kdf_params.time_cost),
            str(self.kdf_params.memory_cost_kib),
            str(self.kdf_params.parallelism),
            _b64(self.salt),
            _b64(self.nonce),
            _b64(self.ciphertext),
        ]
        return SEPARATOR.join(fields)

    @classmethod
    def from_string(cls, text: str) -> "Envelope":
        """parse a TSENC1 string back into its components.

        raises:
            EnvelopeFormatError: if the string is malformed.
        """
        parts = text.strip().split(SEPARATOR)
        if len(parts) != 7:
            raise EnvelopeFormatError(
                f"expected 7 fields, got {len(parts)}"
            )

        version, time_cost, memory_cost_kib, parallelism, salt_b64, nonce_b64, ct_b64 = parts

        if version != FORMAT_VERSION:
            raise EnvelopeFormatError(
                f"unsupported envelope version: {version!r}"
            )

        try:
            params = KdfParams(
                time_cost=int(time_cost),
                memory_cost_kib=int(memory_cost_kib),
                parallelism=int(parallelism),
            )
            return cls(
                kdf_params=params,
                salt=_unb64(salt_b64),
                nonce=_unb64(nonce_b64),
                ciphertext=_unb64(ct_b64),
            )
        except (ValueError, Exception) as exc:
            raise EnvelopeFormatError(f"malformed envelope field: {exc}") from exc


def _b64(data: bytes) -> str:
    """encode bytes as base64 text using the url-safe alphabet, which
    has no '+' or '/' characters -- nothing that could clash with the
    '.' separator or cause trouble if this ever ends up in a url/filename.
    """
    return base64.urlsafe_b64encode(data).decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text.encode("ascii"))
