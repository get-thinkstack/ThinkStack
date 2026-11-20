"""Startup filesystem work, and where uploaded PDFs live.

At startup (main.py lifespan): create the data directories, copy any bundled
models into the writable models dir, and reconcile the model registry with
this build's manifest. Then: save, find, list and delete uploaded PDFs in
`papers_dir` as `<doc_id>_<filename>`, where doc_id is a random 12-hex id.
"""

import logging
import shutil
import uuid
from pathlib import Path

from config import settings

logger = logging.getLogger(__name__)


def ensure_directories() -> None:
    """create all required data directories if they do not exist."""
    for directory in [settings.data_dir, settings.papers_dir, settings.chroma_dir, settings.models_dir]:
        directory.mkdir(parents=True, exist_ok=True)
        logger.info("ensured directory: %s", directory)
    seed_bundled_models()
    _reconcile_model_registry()


def _reconcile_model_registry() -> None:
    """Record what this build ships, and retire what it supersedes.

    Must run AFTER seeding, so the weights it records are already in place.
    Best-effort: a damaged registry degrades to "no user models" rather than
    blocking startup.
    """
    try:
        from domain.model_manager.reconcile import reconcile_and_save

        reconcile_and_save(settings.models_dir, settings.bundled_models_dir)
    except Exception as e:  # noqa: BLE001 - never let bookkeeping kill startup
        logger.warning("could not reconcile the model registry: %s", e)


def seed_bundled_models() -> None:
    """Copy bundled GGUF models into the writable models dir.

    A frozen build ships models read-only but loads them from a writable dir, so
    without this a fresh install starts with no model. Only copies what is
    missing, so a user's own files are never overwritten. No-op in a source
    checkout, where both paths are the same.
    """
    src = settings.bundled_models_dir
    dst = settings.models_dir
    try:
        if not src.is_dir() or src.resolve() == dst.resolve():
            return
        for gguf in sorted(src.glob("*.gguf")):
            target = dst / gguf.name
            if target.exists():
                continue
            logger.info("seeding bundled model into models dir: %s", gguf.name)
            shutil.copy2(gguf, target)
    except OSError as e:  # seeding is best-effort; the app can still run
        logger.warning("could not seed bundled models: %s", e)


def save_uploaded_pdf(filename: str, content: bytes) -> tuple[str, Path]:
    """Store an uploaded PDF. Returns `(doc_id, path)`.

    The id prefixes the stored filename, so two uploads of the same name do not
    collide.
    """
    doc_id = uuid.uuid4().hex[:12]
    safe_name = f"{doc_id}_{filename}"
    file_path = settings.papers_dir / safe_name
    file_path.write_bytes(content)
    logger.info("saved pdf: %s -> %s", filename, file_path)
    return doc_id, file_path


# An encrypted paper's PDF is stored as `<id>_<name>.pdf.tsenc` (a TSENC1
# envelope) and the plaintext file is removed (domain/encryption/at_rest.py).
ENCRYPTED_SUFFIX = ".tsenc"


def _stored(doc_id: str, encrypted: bool) -> Path | None:
    if not settings.papers_dir.exists():
        return None
    for path in settings.papers_dir.iterdir():
        if path.name.startswith(f"{doc_id}_") and (path.suffix == ENCRYPTED_SUFFIX) == encrypted:
            return path
    return None


def get_pdf_path(doc_id: str) -> Path | None:
    """The plaintext PDF for `doc_id`, or None (also None while encrypted)."""
    return _stored(doc_id, encrypted=False)


def get_encrypted_pdf_path(doc_id: str) -> Path | None:
    """The encrypted PDF for `doc_id`, or None."""
    return _stored(doc_id, encrypted=True)


def get_stored_path(doc_id: str) -> Path | None:
    """Whichever file holds the paper: plaintext or encrypted."""
    return get_pdf_path(doc_id) or get_encrypted_pdf_path(doc_id)


def delete_pdf(doc_id: str) -> bool:
    """Delete the stored PDF, plaintext and encrypted. False when there was
    nothing to delete."""
    deleted = False
    for path in (get_pdf_path(doc_id), get_encrypted_pdf_path(doc_id)):
        if path and path.exists():
            path.unlink()
            logger.info("deleted pdf: %s", path)
            deleted = True
    return deleted


def list_stored_pdfs() -> list[dict]:
    """Every stored PDF as `{doc_id, filename, size_bytes}`."""
    results = []
    if not settings.papers_dir.exists():
        return results

    for path in sorted(settings.papers_dir.iterdir()):
        encrypted = path.suffix == ENCRYPTED_SUFFIX
        name = path.name[: -len(ENCRYPTED_SUFFIX)] if encrypted else path.name
        if name.lower().endswith(".pdf"):
            stem = name[:-4]
            parts = stem.split("_", 1)
            doc_id = parts[0] if len(parts) > 1 else stem
            original_name = parts[1] + ".pdf" if len(parts) > 1 else name
            results.append({
                "doc_id": doc_id,
                "filename": original_name,
                "size_bytes": path.stat().st_size,
                "path": str(path),
                "encrypted": encrypted,
            })
    return results
