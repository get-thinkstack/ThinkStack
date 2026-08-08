"""
knowledge base repository module.

provides crud operations for storing and retrieving document chunks
in the vector store. handles batch upsert of chunks with their
embeddings and metadata for efficient vector search.
"""

import logging
from typing import TYPE_CHECKING

from infrastructure.local_vector_store import get_vector_store
from domain.knowledge_base.embedding_service import generate_embeddings
from domain.ingestion.models import TextChunk, DocumentMetadata

if TYPE_CHECKING:
    # numpy stays a deferred import at the one call site that needs it; this is
    # only so the "np.ndarray" annotation below resolves for linters.
    import numpy as np

logger = logging.getLogger(__name__)


def store_chunks(
    chunks: list[TextChunk],
    metadata: DocumentMetadata,
) -> int:
    """store document chunks with embeddings in the vector store.

    generates embeddings for all chunks in batch, then upserts them
    along with metadata for filtering.

    args:
        chunks: list of text chunks to store.
        metadata: document-level metadata to attach to each chunk.

    returns:
        number of chunks successfully stored.
    """
    if not chunks:
        return 0

    store = get_vector_store()

    texts = [c.text for c in chunks]
    embeddings = generate_embeddings(texts)

    ids = [c.chunk_id for c in chunks]
    metadatas = [
        {
            "doc_id": c.doc_id,
            "chunk_index": c.chunk_index,
            "page_number": c.page_number,
            "token_count": c.token_count,
            "title": metadata.title or "",
            "authors": ", ".join(metadata.authors) if metadata.authors else "",
            "year": metadata.year or "",
        }
        for c in chunks
    ]

    store.upsert(
        ids=ids,
        documents=texts,
        embeddings=embeddings,
        metadatas=metadatas,
    )

    logger.info("stored %d chunks for document %s", len(chunks), chunks[0].doc_id)
    return len(chunks)


def get_chunks_by_doc_id(doc_id: str) -> dict:
    """retrieve all chunks belonging to a specific document.

    args:
        doc_id: the document identifier to filter by.

    returns:
        dictionary with ids, documents, metadatas lists.
    """
    store = get_vector_store()
    return store.get(where={"doc_id": doc_id})


def delete_chunks_by_doc_id(doc_id: str) -> bool:
    """delete all chunks for a specific document from the store.

    args:
        doc_id: the document identifier whose chunks should be removed.

    returns:
        true if chunks were found and deleted, false if none existed.
    """
    store = get_vector_store()
    existing = store.get(where={"doc_id": doc_id})

    if existing["ids"]:
        store.delete(ids=existing["ids"])
        logger.info("deleted %d chunks for document %s", len(existing["ids"]), doc_id)
        return True
    return False


def get_all_doc_ids() -> list[str]:
    """retrieve all unique document ids in the store.

    returns:
        sorted list of unique document id strings.
    """
    store = get_vector_store()
    results = store.get()

    doc_ids = set()
    for meta in results.get("metadatas", []):
        if meta and "doc_id" in meta:
            doc_ids.add(meta["doc_id"])

    return sorted(doc_ids)


def get_doc_centroids(doc_ids: list[str] | None = None) -> tuple[list[str], "np.ndarray"]:
    """mean embedding per document, as (ids, matrix of shape (n, d)).

    a document's centroid is the cheapest honest summary of what it is about:
    it already exists (written at ingest), it costs no model call, and cosine
    between two of them is a far better similarity signal than asking a small
    model to eyeball two text excerpts.

    args:
        doc_ids: restrict to these documents. None means every document.

    returns:
        (ids, centroids) aligned by index. documents with no stored vectors are
        dropped rather than given a zero row -- a zero row would sit at the
        origin and claim similarity to everything else parked there.
    """
    import numpy as np

    got = get_vector_store().get_embeddings()
    if got["embeddings"] is None or len(got["ids"]) == 0:
        return [], np.empty((0, 0), dtype=np.float32)

    wanted = set(doc_ids) if doc_ids else None
    embeddings = np.asarray(got["embeddings"], dtype=np.float32)

    order: list[str] = []
    rows: dict[str, list] = {}
    for i, meta in enumerate(got["metadatas"]):
        doc_id = (meta or {}).get("doc_id")
        if not doc_id or (wanted is not None and doc_id not in wanted):
            continue
        if doc_id not in rows:
            rows[doc_id] = []
            order.append(doc_id)
        rows[doc_id].append(embeddings[i])

    if not order:
        return [], np.empty((0, 0), dtype=np.float32)

    return order, np.vstack([np.mean(rows[d], axis=0) for d in order])


def get_collection_stats() -> dict:
    """return statistics about the vector store.

    returns:
        dictionary with total chunk count and unique document count.
    """
    store = get_vector_store()
    count = store.count()
    doc_ids = get_all_doc_ids()
    return {
        "total_chunks": count,
        "total_documents": len(doc_ids),
        "document_ids": doc_ids,
    }


def update_chunk_metadata_field(chunk_id: str, field: str, value) -> None:
    """update a single metadata field on a specific chunk.

    uses chromadb's upsert to merge the new field value into the
    existing metadata without touching the document text or embedding.

    args:
        chunk_id: the id of the chunk to update.
        field: the metadata key to set.
        value: the value to assign (must be a chroma-compatible type:
            str, int, float, or bool).
    """
    store = get_vector_store()
    existing = store.get(ids=[chunk_id])

    if not existing["ids"]:
        logger.warning("chunk %s not found, skipping metadata update", chunk_id)
        return

    meta = existing["metadatas"][0] if existing["metadatas"] else {}
    meta[field] = value

    store.update(ids=[chunk_id], metadatas=[meta])
