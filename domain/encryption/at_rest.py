"""Encrypting a paper at rest: its chunk text and its stored PDF.

    lock_paper    chunk texts -> one envelope on every chunk's metadata, then
                  the text is blanked; the PDF -> `<file>.pdf.tsenc`, then the
                  plaintext PDF is deleted; the cached summary and the past
                  runs that quote the paper are dropped
    read_text     the joined text, with the password; nothing changes, except
                  that a v1 paper is upgraded to v2 (below)
    unlock_paper  PDF and chunk texts restored exactly, flags cleared

Embeddings are kept, so the map still places the paper and search can still
find it; they reveal its topic, not its text.

Order matters. Every ciphertext is written before any plaintext is removed,
and the password is proven before anything is restored, so a failure part way
leaves a paper that is still readable with its password. The routes refuse
text whenever `is_encrypted` is set, so a half-locked paper is not served.

Papers encrypted before 2026-11-19 carry a v1 envelope (joined text only) and
their chunk text and PDF were never removed. The first `read_text` with the
password locks them at rest; unlocking one that was never read just clears
the flags.
"""

from __future__ import annotations

import os

from domain.encryption.vault import decrypt_bytes, encrypt_bytes, open_text, seal_chunks
from domain.knowledge_base.repository import (
    get_chunks_by_doc_id,
    is_encrypted,
    set_chunk_texts,
    update_chunk_metadata_field,
)
from infrastructure.analysis_cache import doc_analysis_cache
from infrastructure.analysis_history import analysis_history
from infrastructure.gap_history import gap_history
from infrastructure.file_manager import (
    ENCRYPTED_SUFFIX,
    get_encrypted_pdf_path,
    get_pdf_path,
)


class NotEncryptedError(ValueError):
    """the paper is not encrypted."""


class AlreadyEncryptedError(ValueError):
    """the paper is already encrypted."""


class NothingToEncryptError(ValueError):
    """the paper has no text."""


def _chunks(doc_id: str) -> dict:
    chunks = get_chunks_by_doc_id(doc_id)
    if not chunks["ids"]:
        raise LookupError(doc_id)
    return chunks


def _envelope(chunks: dict) -> str:
    first = chunks["metadatas"][0] if chunks["metadatas"] else {}
    if not is_encrypted(first):
        raise NotEncryptedError()
    return first.get("encrypted_envelope") or ""


def _write_atomically(path, text: str) -> None:
    tmp = path.with_name(path.name + ".part")
    tmp.write_text(text, encoding="ascii")
    os.replace(tmp, path)


def lock_paper(doc_id: str, password: str) -> int:
    """Encrypt the paper at rest. Returns how many chunks were locked."""
    chunks = _chunks(doc_id)
    if is_encrypted(chunks["metadatas"][0] if chunks["metadatas"] else {}):
        raise AlreadyEncryptedError()
    texts = dict(zip(chunks["ids"], chunks["documents"] or []))
    if not any(t.strip() for t in texts.values()):
        raise NothingToEncryptError()
    _seal(doc_id, chunks["ids"], texts, password)
    return len(chunks["ids"])


def _seal(doc_id: str, ids: list[str], texts: dict[str, str], password: str) -> None:
    """Write every ciphertext, then remove every plaintext."""
    envelope = seal_chunks(texts, password)
    pdf = get_pdf_path(doc_id)
    if pdf:
        _write_atomically(pdf.with_name(pdf.name + ENCRYPTED_SUFFIX),
                          encrypt_bytes(pdf.read_bytes(), password))

    for chunk_id in ids:
        update_chunk_metadata_field(chunk_id, "encrypted_envelope", envelope)
        update_chunk_metadata_field(chunk_id, "is_encrypted", "true")

    # Ciphertext is all in place; only now remove the plaintext.
    set_chunk_texts({cid: "" for cid in ids})
    if pdf:
        pdf.unlink()
    doc_analysis_cache.delete(doc_id)
    _forget_runs(doc_id)


def _forget_runs(doc_id: str) -> None:
    """Drop past runs that quote the paper: summaries, claims, gap scans.
    Theme runs stay; they hold group names and membership, not its words."""
    for run in analysis_history.list():
        if run.get("type") != "themes" and doc_id in (run.get("doc_ids") or []):
            analysis_history.delete(run["run_id"])
    for run in gap_history.list():
        if doc_id in (run.get("doc_ids") or []):
            gap_history.delete(run["run_id"])


def read_text(doc_id: str, password: str) -> str:
    """The paper's text. WrongPasswordError / EnvelopeFormatError propagate.

    A paper locked the old way (v1: joined text only, plaintext left behind) is
    upgraded to full at-rest encryption here: the password is the only thing
    that can do it, and this is the first time it is offered.
    """
    chunks = _chunks(doc_id)
    joined, texts = open_text(_envelope(chunks), password)
    plain = dict(zip(chunks["ids"], chunks["documents"] or []))
    if texts is None and any(t.strip() for t in plain.values()):
        _seal(doc_id, chunks["ids"], plain, password)
    return joined


def unlock_paper(doc_id: str, password: str) -> int:
    """Remove encryption, restoring text and PDF exactly. Returns chunk count."""
    chunks = _chunks(doc_id)
    _, texts = open_text(_envelope(chunks), password)   # proves the password

    sealed_pdf = get_encrypted_pdf_path(doc_id)
    if sealed_pdf:
        data = decrypt_bytes(sealed_pdf.read_text(encoding="ascii"), password)
        plain = sealed_pdf.with_name(sealed_pdf.name[: -len(ENCRYPTED_SUFFIX)])
        tmp = plain.with_name(plain.name + ".part")
        tmp.write_bytes(data)
        os.replace(tmp, plain)
        sealed_pdf.unlink()

    if texts is not None:                                # v1 never blanked them
        set_chunk_texts(texts)
    for chunk_id in chunks["ids"]:
        update_chunk_metadata_field(chunk_id, "encrypted_envelope", "")
        update_chunk_metadata_field(chunk_id, "is_encrypted", "false")
    return len(chunks["ids"])
