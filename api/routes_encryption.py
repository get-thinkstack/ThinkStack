"""Vault routes: encrypt a paper at rest, read it back, or remove encryption.

The work is domain/encryption/at_rest.py (what is locked, in what order) over
vault.py (Argon2id key, AES-256-GCM, TSENC1 envelope). These routes only map
its errors to HTTP.
"""

import logging
from contextlib import contextmanager

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from domain.encryption import at_rest
from domain.encryption.envelope import EnvelopeFormatError
from domain.encryption.vault import WrongPasswordError

logger = logging.getLogger(__name__)
router = APIRouter()


class EncryptRequest(BaseModel):
    doc_id: str
    password: str


class DecryptRequest(BaseModel):
    doc_id: str
    password: str


@contextmanager
def _as_http():
    try:
        yield
    except LookupError:
        raise HTTPException(status_code=404, detail="document not found")
    except at_rest.AlreadyEncryptedError:
        raise HTTPException(status_code=409, detail="document is already encrypted")
    except at_rest.NotEncryptedError:
        raise HTTPException(status_code=400, detail="document is not encrypted")
    except at_rest.NothingToEncryptError:
        raise HTTPException(status_code=422, detail="document has no text to encrypt")
    except WrongPasswordError:
        raise HTTPException(status_code=403, detail="incorrect password")
    except EnvelopeFormatError as e:
        raise HTTPException(status_code=422, detail=f"corrupted envelope: {e}")


@router.post("/encrypt")
async def encrypt_document(req: EncryptRequest):
    """Encrypt a paper's text and PDF at rest."""
    with _as_http():
        n = at_rest.lock_paper(req.doc_id, req.password)
    return {"doc_id": req.doc_id, "is_encrypted": True, "chunks_updated": n, "status": "encrypted"}


@router.post("/decrypt")
async def decrypt_document(req: DecryptRequest):
    """Return the decrypted text. Read-only: the paper stays encrypted."""
    with _as_http():
        text = at_rest.read_text(req.doc_id, req.password)
    return {"doc_id": req.doc_id, "full_text": text, "status": "decrypted"}


@router.post("/remove")
async def remove_encryption(req: DecryptRequest):
    """Remove encryption, restoring the text and the PDF exactly."""
    with _as_http():
        n = at_rest.unlock_paper(req.doc_id, req.password)
    return {"doc_id": req.doc_id, "is_encrypted": False, "chunks_updated": n,
            "status": "encryption_removed"}
