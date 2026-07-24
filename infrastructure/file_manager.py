"""
file manager module.

handles filesystem operations for pdf storage and data directory
management. ensures required directories exist on application startup.
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


def seed_bundled_models() -> None:
    """copy gguf models shipped in the frozen bundle into the writable models dir.

    a frozen build ships its models under a read-only bundle dir
    (``settings.bundled_models_dir``), but the app loads models from the
    writable ``settings.models_dir`` (STATE_DIR/models). without this, a freshly
    installed app would start with no model. only seeds files that are missing,
    so user-added or already-copied models are never overwritten. a no-op in a
    source checkout, where the two dirs are the same path.
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
    """save an uploaded pdf file to the papers directory.

    generates a unique document id and stores the file with that id
    as a prefix to avoid naming collisions.

    args:
        filename: the original filename of the uploaded pdf.
        content: the raw bytes of the pdf file.

    returns:
        a tuple of (document_id, file_path) where document_id is a
        unique identifier and file_path is the absolute storage path.
    """
    doc_id = uuid.uuid4().hex[:12]
    safe_name = f"{doc_id}_{filename}"
    file_path = settings.papers_dir / safe_name
    file_path.write_bytes(content)
    logger.info("saved pdf: %s -> %s", filename, file_path)
    return doc_id, file_path


def get_pdf_path(doc_id: str) -> Path | None:
    """find the stored pdf file for a given document id.

    args:
        doc_id: the unique document identifier.

    returns:
        the file path if found, none otherwise.
    """
    for path in settings.papers_dir.iterdir():
        if path.name.startswith(doc_id):
            return path
    return None


def delete_pdf(doc_id: str) -> bool:
    """delete the stored pdf for a given document id.

    args:
        doc_id: the unique document identifier.

    returns:
        true if the file was found and deleted, false otherwise.
    """
    path = get_pdf_path(doc_id)
    if path and path.exists():
        path.unlink()
        logger.info("deleted pdf: %s", path)
        return True
    return False


def list_stored_pdfs() -> list[dict]:
    """list all pdf files currently stored in the papers directory.

    returns:
        list of dictionaries with doc_id, filename, and size_bytes.
    """
    results = []
    if not settings.papers_dir.exists():
        return results

    for path in sorted(settings.papers_dir.iterdir()):
        if path.suffix.lower() == ".pdf":
            parts = path.stem.split("_", 1)
            doc_id = parts[0] if len(parts) > 1 else path.stem
            original_name = parts[1] + ".pdf" if len(parts) > 1 else path.name
            results.append({
                "doc_id": doc_id,
                "filename": original_name,
                "size_bytes": path.stat().st_size,
                "path": str(path),
            })
    return results
