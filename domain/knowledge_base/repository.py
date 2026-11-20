"""Every write to the vector store goes through here: store, update, delete.

Ingest calls `store_chunks` (which embeds); LitGraph reads `get_doc_centroids`
and `get_document_metadata`; corrections call `update_document_metadata`.
Search (semantic_search, grounding) and graph_builder read the store
directly; nothing else should touch it.
"""

import logging
from typing import TYPE_CHECKING

from infrastructure.local_vector_store import get_vector_store
from domain.knowledge_base.author_codec import encode_authors
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
    """Embed the chunks in one batch and store them. Returns how many landed."""
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
            "authors": encode_authors(metadata.authors),
            "year": metadata.year or "",
            "arxiv_id": metadata.arxiv_id or "",
            "doi": metadata.doi or "",
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
    """Every chunk of one document, as `{ids, documents, metadatas}`."""
    store = get_vector_store()
    return store.get(where={"doc_id": doc_id})


def delete_chunks_by_doc_id(doc_id: str) -> bool:
    """Delete a document's chunks. False when it had none."""
    store = get_vector_store()
    existing = store.get(where={"doc_id": doc_id})

    if existing["ids"]:
        store.delete(ids=existing["ids"])
        logger.info("deleted %d chunks for document %s", len(existing["ids"]), doc_id)
        return True
    return False


def get_all_doc_ids() -> list[str]:
    """Every document id in the store, sorted."""
    store = get_vector_store()
    results = store.get()

    doc_ids = set()
    for meta in results.get("metadatas", []):
        if meta and "doc_id" in meta:
            doc_ids.add(meta["doc_id"])

    return sorted(doc_ids)


def get_document_metadata() -> dict[str, dict]:
    """`{doc_id: metadata}`, taking each document's lowest-numbered chunk.

    Every chunk of a document carries the same document-level fields, so any
    of them would do, but "any" is not stable across calls, so the lowest
    chunk index decides. One store read for the whole library, not a query per
    paper.
    """
    store = get_vector_store()
    results = store.get()

    best: dict[str, tuple[int, dict]] = {}
    for meta in results.get("metadatas", []) or []:
        if not meta or "doc_id" not in meta:
            continue
        index = meta.get("chunk_index")
        index = index if isinstance(index, int) else 1 << 30
        current = best.get(meta["doc_id"])
        if current is None or index < current[0]:
            best[meta["doc_id"]] = (index, dict(meta))

    return {doc_id: meta for doc_id, (_, meta) in best.items()}


def get_doc_centroids(doc_ids: list[str] | None = None) -> tuple[list[str], "np.ndarray"]:
    """Mean embedding per document, as `(ids, matrix (n, d))` aligned by index.

    Documents with no stored vectors are DROPPED, not given a zero row: a zero
    row sits at the origin and claims similarity to everything else parked
    there.
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
    """Total chunks and unique documents."""
    store = get_vector_store()
    count = store.count()
    doc_ids = get_all_doc_ids()
    return {
        "total_chunks": count,
        "total_documents": len(doc_ids),
        "document_ids": doc_ids,
    }


def update_document_metadata(doc_id: str, fields: dict) -> int:
    """Set metadata fields on EVERY chunk of a document. Returns the count.

    Bibliographic metadata is copied onto each chunk so a search hit can name
    its paper without a second lookup. The cost is that correcting a title is
    not one write: miss a chunk and the same paper answers to two titles
    depending on which passage matched.

    All the fields go in one pass. Correcting a reference usually means fixing
    the authors and the year together, and a field at a time would read and
    rewrite every chunk of the paper once per field.
    """
    if not fields:
        return 0

    store = get_vector_store()
    existing = store.get(where={"doc_id": doc_id})
    ids = existing.get("ids") or []
    if not ids:
        return 0

    metadatas = existing.get("metadatas") or [{} for _ in ids]
    for meta in metadatas:
        meta.update(fields)

    store.update(ids=ids, metadatas=metadatas)
    logger.info("updated %s on %d chunks of %s", ", ".join(fields), len(ids), doc_id)
    return len(ids)


def update_chunk_metadata_field(chunk_id: str, field: str, value) -> None:
    """Set one metadata field on one chunk, leaving text and embedding alone.

    `value` must be str, int, float or bool.
    """
    store = get_vector_store()
    existing = store.get(ids=[chunk_id])

    if not existing["ids"]:
        logger.warning("chunk %s not found, skipping metadata update", chunk_id)
        return

    meta = existing["metadatas"][0] if existing["metadatas"] else {}
    meta[field] = value

    store.update(ids=[chunk_id], metadatas=[meta])


def set_chunk_texts(texts_by_id: dict[str, str]) -> int:
    """Replace chunk text, leaving metadata and embeddings alone. Encryption
    blanks text at rest with this and restores it on removal."""
    return get_vector_store().set_documents(texts_by_id)


def is_encrypted(meta: dict | None) -> bool:
    """The flag as stored: the string "true", or a legacy boolean."""
    return (meta or {}).get("is_encrypted") in ("true", True)
