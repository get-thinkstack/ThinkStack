"""
knowledge base repository module.

provides crud operations for storing and retrieving document chunks
in the vector store. handles batch upsert of chunks with their
embeddings and metadata for efficient vector search.
"""

import logging

from infrastructure.local_vector_store import get_vector_store
from domain.knowledge_base.embedding_service import generate_embeddings
from domain.ingestion.models import TextChunk, DocumentMetadata

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
