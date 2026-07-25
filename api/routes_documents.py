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
from domain.analysis.document_analysis import analyze_document
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

        # precompute the per-document summary+claims now, at ingest time, so a
        # later gap scan reuses it and only pays for the single aggregation
        # call. best-effort: if the model is unavailable this must not fail the
        # upload -- the gap route falls back to computing it lazily on demand.
        try:
            analysis = await analyze_document(doc_id, full_text)
            if analysis is not None:
                doc_analysis_cache.put(
                    doc_id, analysis["summary"], analysis["claims"]
                )
        except Exception as e:  # noqa: BLE001 - ingest-time analysis is optional
            logger.warning("ingest-time analysis skipped for %s: %s", doc_id, e)

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
        "metadata": metadata,
        "chunks": [
            {"chunk_id": cid, "text": txt[:500], "metadata": meta}
            for cid, txt, meta in zip(
                chunks["ids"], texts, chunks["metadatas"]
            )
        ],
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
