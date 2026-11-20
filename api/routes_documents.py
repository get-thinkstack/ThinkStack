"""Library routes: upload, list, read, correct and delete papers.

`POST /upload` is the ingestion pipeline:

    save PDF -> text (pdf_parser) -> page-1 layout -> metadata
      -> chunks (chunker) -> embed + store (repository)
      -> queue analysis (analysis.precompute), after the response

Ingest must survive its optional steps. A failed layout read or analysis
queue is logged; it never discards a paper whose chunks are already stored.
"""

import logging
import re
from dataclasses import asdict

from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel
from fastapi.responses import FileResponse

from infrastructure.file_manager import (
    save_uploaded_pdf,
    list_stored_pdfs,
    delete_pdf,
    get_pdf_path,
    get_stored_path,
)
from domain.ingestion.pdf_parser import extract_layout, extract_text, get_page_count
from domain.ingestion.chunker import chunk_pages
from domain.ingestion.metadata_extractor import extract_metadata
from domain.analysis.precompute import schedule_for_new_document
from domain.knowledge_base.author_codec import (
    authors_display, decode_authors, encode_authors,
)
from domain.knowledge_base.repository import (
    store_chunks,
    get_chunks_by_doc_id,
    delete_chunks_by_doc_id,
    get_collection_stats,
    is_encrypted,
    update_document_metadata,
)
from infrastructure.analysis_cache import doc_analysis_cache
from infrastructure.gap_history import gap_history

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    """Ingest one PDF and return its metadata and chunk count.

    Analysis is queued, so the response does not wait for a model.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="only pdf files are accepted")

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="uploaded file is empty")

    doc_id, file_path = save_uploaded_pdf(file.filename, content)

    try:
        pages, full_text = extract_text(str(file_path))
        if not full_text.strip():
            raise HTTPException(
                status_code=422,
                detail="could not extract text from the pdf",
            )

        # Title and authors are only identifiable from page-1 layout (font
        # sizes, positions); full_text has flattened it. Optional: with no
        # layout, extract_metadata falls back to the flat text.
        try:
            layout = extract_layout(str(file_path))
        except Exception as e:  # noqa: BLE001 - layout is optional, ingest is not
            logger.warning("layout extraction failed for %s: %s", file.filename, e)
            layout = []

        metadata = await extract_metadata(full_text, page=layout[0] if layout else None)
        metadata.pages = get_page_count(str(file_path))
        metadata.source = file.filename

        chunks = chunk_pages(pages, doc_id)
        stored_count = store_chunks(chunks, metadata)

        # Queued, never awaited: a model call here holds the upload open for
        # tens of seconds per paper. Guarded because the paper is already
        # stored; a queue failure reaching the handler below would delete it.
        try:
            schedule_for_new_document(doc_id, full_text, metadata.title)
        except Exception as e:  # noqa: BLE001 - analysis is optional, ingest is not
            logger.warning("could not queue analysis for %s: %s", doc_id, e)

        return {
            "doc_id": doc_id,
            "filename": file.filename,
            "metadata": asdict(metadata),
            "chunks_created": stored_count,
            "text_length": len(full_text),
            "status": "ingested",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("ingestion failed for %s: %s", file.filename, e)
        delete_pdf(doc_id)
        raise HTTPException(
            status_code=500,
            detail=f"ingestion failed: {str(e)}",
        )


@router.get("")
async def list_documents():
    """Every paper with its metadata and chunk count, plus the Library's
    summary figures (chunks, analysed papers, gaps in the newest scan)."""
    stored_files = list_stored_pdfs()
    stats = get_collection_stats()

    documents = []
    for pdf in stored_files:
        doc_id = pdf["doc_id"]
        chunks = get_chunks_by_doc_id(doc_id)
        chunk_count = len(chunks["ids"]) if chunks["ids"] else 0

        doc_metadata = {}
        if chunks["metadatas"] and chunks["metadatas"]:
            first_meta = chunks["metadatas"][0]
            doc_metadata = {
                "title": first_meta.get("title", ""),
                "authors": authors_display(first_meta.get("authors", "")),
                "year": first_meta.get("year", ""),
                "is_encrypted": first_meta.get("is_encrypted", "false"),
            }

        documents.append({
            "doc_id": doc_id,
            "filename": pdf["filename"],
            "size_bytes": pdf["size_bytes"],
            "chunks": chunk_count,
            "metadata": doc_metadata,
        })

    # The newest gap run, not a sum: each scan covers the whole library and
    # supersedes the last, so summing would count a gap once per rescan.
    latest_gap_run = (gap_history.list() or [{}])[0]

    return {
        "documents": documents,
        "total": len(documents),
        "total_chunks": stats["total_chunks"],
        "analyses": doc_analysis_cache.count(),
        "gaps": latest_gap_run.get("total_gaps", 0),
    }


@router.get("/{doc_id}")
async def get_document(doc_id: str):
    """One paper: metadata, every chunk in full, and the joined text.

    An encrypted paper is listed with its metadata and NO text; reading it
    needs the password (POST /api/encryption/decrypt).
    """
    path = get_stored_path(doc_id)
    if not path:
        raise HTTPException(status_code=404, detail="document not found")

    chunks = get_chunks_by_doc_id(doc_id)
    if not chunks["ids"]:
        raise HTTPException(status_code=404, detail="document chunks not found")

    metadata = chunks["metadatas"][0] if chunks["metadatas"] else {}
    texts = chunks["documents"] if chunks["documents"] else []
    if is_encrypted(metadata):
        # Also covers papers locked before text was blanked at rest.
        texts = ["" for _ in texts]

    return {
        "doc_id": doc_id,
        "filename": path.name,
        # Whole chunks, never previews: the LitGraph reader marks passages per
        # chunk, and a truncated chunk drops the marked sentence.
        "chunks": [
            {"chunk_id": cid, "text": txt, "metadata": meta}
            for cid, txt, meta in zip(
                chunks["ids"], texts, chunks["metadatas"]
            )
        ],
        "metadata": metadata,
        "total_chunks": len(chunks["ids"]),
        "full_text": " ".join(texts),
    }


# HEAD as well as GET: the reader probes for the pdf's existence before
# mounting an <iframe>, and fastapi does not add HEAD to a GET route on its
# own -- the probe got 405 and every paper fell back to the text view.
@router.api_route("/{doc_id}/pdf", methods=["GET", "HEAD"])
async def get_document_pdf(doc_id: str):
    """serve the originally uploaded pdf, for the litgraph reader.

    served ``inline`` so the panel's <iframe> renders it -- an ``attachment``
    disposition downloads the file and leaves the iframe blank, the same trap
    the paper-writer preview hit.
    """
    # Encrypted first: its plaintext PDF is gone, and the reader treats 403
    # as "locked" where 404 would mean "lost".
    chunks = get_chunks_by_doc_id(doc_id)
    if is_encrypted((chunks.get("metadatas") or [{}])[0]):
        raise HTTPException(status_code=403, detail="document is encrypted")

    path = get_pdf_path(doc_id)
    if not path:
        raise HTTPException(status_code=404, detail="document not found")

    return FileResponse(
        path=str(path),
        media_type="application/pdf",
        filename=path.name,
        content_disposition_type="inline",
    )


class ReferenceUpdate(BaseModel):
    """The bibliographic fields. Omit one to leave it as it is."""
    title: str | None = None
    authors: list[str] | None = None
    year: str | None = None


MAX_AUTHORS = 60          # the largest real author lists run to about 50
MAX_AUTHOR_CHARS = 120


@router.patch("/{doc_id}/metadata")
async def correct_reference(doc_id: str, body: ReferenceUpdate):
    """Correct a paper's extracted title, authors or year.

    This metadata labels map nodes, names search hits and builds BibTeX
    entries, and extraction is wrong for a minority of papers, so this is the
    one place to repair it. Later citations use the fix; a references.bib
    already written keeps what it has, because that file is the author's.

    An empty year is allowed (the paper states none). An empty title is not
    (the paper could not be found again).
    """
    fields: dict = {}

    if body.title is not None:
        title = body.title.strip()
        if not title:
            raise HTTPException(status_code=400, detail="A paper needs a title.")
        if len(title) > 300:
            raise HTTPException(status_code=400, detail="That title is too long.")
        fields["title"] = title

    if body.authors is not None:
        names = [a.strip() for a in body.authors if a and a.strip()]
        if len(names) > MAX_AUTHORS:
            raise HTTPException(status_code=400, detail=f"At most {MAX_AUTHORS} authors.")
        if any(len(n) > MAX_AUTHOR_CHARS for n in names):
            raise HTTPException(status_code=400, detail="One of those names is too long.")
        fields["authors"] = encode_authors(names)

    if body.year is not None:
        year = body.year.strip()
        if year and not re.fullmatch(r"(1[89]|20)\d{2}", year):
            raise HTTPException(status_code=400, detail="Use a four-digit year, or leave it blank.")
        fields["year"] = year

    if not fields:
        raise HTTPException(status_code=400, detail="Nothing to change.")

    updated = update_document_metadata(doc_id, fields)
    if not updated:
        raise HTTPException(status_code=404, detail="document not found")

    return {
        "doc_id": doc_id,
        "metadata": {
            **fields,
            **({"authors": decode_authors(fields["authors"])} if "authors" in fields else {}),
        },
        "chunks_updated": updated,
    }


@router.delete("/{doc_id}")
async def delete_document(doc_id: str):
    """Delete a paper: its PDF, its chunks and its cached analysis."""
    pdf_deleted = delete_pdf(doc_id)
    chunks_deleted = delete_chunks_by_doc_id(doc_id)
    # Its cached analysis goes too, or the orphan is still counted as analysed.
    doc_analysis_cache.delete(doc_id)

    if not pdf_deleted and not chunks_deleted:
        raise HTTPException(status_code=404, detail="document not found")

    return {
        "doc_id": doc_id,
        "pdf_deleted": pdf_deleted,
        "chunks_deleted": chunks_deleted,
        "status": "deleted",
    }
