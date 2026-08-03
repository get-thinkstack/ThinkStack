"""
document api routes.

handles pdf upload, listing, retrieval, and deletion endpoints.
orchestrates the full ingestion pipeline from upload through
chunking and embedding storage.
"""

import logging
from dataclasses import asdict

from fastapi import APIRouter, UploadFile, File, HTTPException

from infrastructure.file_manager import (
    save_uploaded_pdf,
    list_stored_pdfs,
    delete_pdf,
    get_pdf_path,
)
from domain.ingestion.pdf_parser import extract_text, get_page_count
from domain.ingestion.chunker import chunk_pages
from domain.ingestion.metadata_extractor import extract_metadata
from domain.analysis.precompute import schedule_for_new_document
from domain.knowledge_base.repository import (
    store_chunks,
    get_chunks_by_doc_id,
    delete_chunks_by_doc_id,
    get_collection_stats,
)
from infrastructure.analysis_cache import doc_analysis_cache

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    """upload and process a pdf research paper.

    accepts a pdf file, extracts text, identifies metadata, creates
    chunks, generates embeddings, and stores everything in the
    knowledge base.

    args:
        file: the uploaded pdf file.

    returns:
        document metadata and processing statistics.
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

        metadata = await extract_metadata(full_text)
        metadata.pages = get_page_count(str(file_path))
        metadata.source = file.filename

        chunks = chunk_pages(pages, doc_id)
        stored_count = store_chunks(chunks, metadata)

        # Queue the analysis instead of awaiting it.
        #
        # This used to `await analyze_document(...)` here, which put a ~50 s
        # model call inside the upload request -- the browser sat on a pending
        # POST for the whole of it, and uploading three papers meant three
        # minutes of apparent hang. The work still happens at ingest time (so
        # the canvas is ready before the user opens it); it just happens after
        # the response, and a re-cluster and gap scan are queued behind it.
        # Guarded: by this point the pdf is saved and its chunks are stored, so
        # the document IS ingested. Letting a queue failure fall through to the
        # handler below would delete it and report a 500 for a paper that is
        # actually in the library. The analysis is recoverable; the ingest is
        # not worth throwing away with it.
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
    """list all ingested documents with their metadata.

    returns:
        list of document summaries including file and chunk information.
    """
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
                "authors": first_meta.get("authors", ""),
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

    return {
        "documents": documents,
        "total": len(documents),
        "total_chunks": stats["total_chunks"],
    }


@router.get("/{doc_id}")
async def get_document(doc_id: str):
    """get detailed information about a specific document.

    args:
        doc_id: the document identifier.

    returns:
        document details including all chunk texts and metadata.
    """
    path = get_pdf_path(doc_id)
    if not path:
        raise HTTPException(status_code=404, detail="document not found")

    chunks = get_chunks_by_doc_id(doc_id)
    if not chunks["ids"]:
        raise HTTPException(status_code=404, detail="document chunks not found")

    metadata = chunks["metadatas"][0] if chunks["metadatas"] else {}
    texts = chunks["documents"] if chunks["documents"] else []

    return {
        "doc_id": doc_id,
        "filename": path.name,
        # whole chunks, not a 500-char preview of each: litgraph's reader shows
        # the paper itself, and it marks passages per chunk -- a truncated chunk
        # would drop the marked sentence as often as it kept it. this costs
        # nothing on the wire that full_text below was not already sending.
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


@router.delete("/{doc_id}")
async def delete_document(doc_id: str):
    """delete a document and all its associated data.

    removes the pdf file and all chunks from the knowledge base.

    args:
        doc_id: the document identifier to delete.

    returns:
        confirmation of deletion.
    """
    pdf_deleted = delete_pdf(doc_id)
    chunks_deleted = delete_chunks_by_doc_id(doc_id)
    # drop any cached gap-analysis for this document so a re-upload under a new
    # id is never served a previous document's summary.
    doc_analysis_cache.delete(doc_id)

    if not pdf_deleted and not chunks_deleted:
        raise HTTPException(status_code=404, detail="document not found")

    return {
        "doc_id": doc_id,
        "pdf_deleted": pdf_deleted,
        "chunks_deleted": chunks_deleted,
        "status": "deleted",
    }
