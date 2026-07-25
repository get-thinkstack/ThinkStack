"""
semantic search module.

performs vector similarity search over the vector store using
cosine distance on locally generated embeddings.
"""

import logging

from infrastructure.local_vector_store import get_vector_store
from domain.knowledge_base.embedding_service import generate_embedding
from domain.search.models import SearchQuery, SearchResult

logger = logging.getLogger(__name__)


def semantic_search(query: SearchQuery) -> list[SearchResult]:
    """search the knowledge base using vector similarity.

    embeds the query text and searches the vector store for the most
    similar document chunks using cosine distance.

    args:
        query: search query with text, top_k, and optional filters.

    returns:
        list of search results sorted by descending similarity score.
    """
    store = get_vector_store()

    if store.count() == 0:
        return []

    query_embedding = generate_embedding(query.query)

    where_filter = None
    if query.doc_ids:
        where_filter = {"doc_id": {"$in": query.doc_ids}}

    results = store.query(
        query_embedding=query_embedding,
        n_results=min(query.top_k, store.count()),
        where=where_filter,
    )

    search_results = []
    if results and results["ids"]:
        for i, chunk_id in enumerate(results["ids"]):
            distance = results["distances"][i] if results["distances"] else 1.0
            score = 1.0 - distance

            if score < query.min_score:
                continue

            search_results.append(SearchResult(
                chunk_id=chunk_id,
                doc_id=results["metadatas"][i].get("doc_id", ""),
                text=results["documents"][i],
                score=round(score, 4),
                metadata=results["metadatas"][i],
                source="semantic",
            ))

    logger.info(
        "semantic search for '%s' returned %d results",
        query.query[:50],
        len(search_results),
    )
    return search_results
