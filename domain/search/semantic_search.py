"""Cosine similarity over locally generated embeddings.

The only search path in the app. BM25 and rank fusion were removed -- see
docs/ADR.md -- leaving one thing to preserve: rare literal tokens like
`FedAvg` or a surname, which the exact-token bonus can only nudge upward,
never enough to outrank a better meaning match.
"""

import logging
import re

from infrastructure.local_vector_store import get_vector_store
from domain.knowledge_base.author_codec import authors_display
from domain.knowledge_base.embedding_service import generate_embedding
from domain.knowledge_base.repository import is_encrypted
from domain.search.models import SearchQuery, SearchResult

logger = logging.getLogger(__name__)

# deliberately small. this must be able to lift a literal match over a
# near-tie, and must not be able to lift it over a genuinely better
# semantic match -- that would re-introduce the keyword bias we removed.
EXACT_TOKEN_BONUS = 0.05


def _tokenize(text: str) -> list[str]:
    """lowercase word tokens, used only for the exact-match bonus."""
    return re.findall(r"\b\w+\b", text.lower())


def _exact_bonus(query_tokens: list[str], text: str) -> float:
    """Fraction of query tokens appearing verbatim, in [0, EXACT_TOKEN_BONUS]."""
    if not query_tokens:
        return 0.0
    haystack = set(_tokenize(text))
    hits = sum(1 for t in query_tokens if t in haystack)
    return EXACT_TOKEN_BONUS * (hits / len(query_tokens))


def semantic_search(query: SearchQuery) -> list[SearchResult]:
    """Score the query against EVERY stored chunk, not a candidate pool.

    That is what makes a passage on page 40 as findable as one in the abstract.
    """
    store = get_vector_store()

    if store.count() == 0:
        return []

    query_embedding = generate_embedding(query.query)
    query_tokens = _tokenize(query.query)

    where_filter = None
    if query.doc_ids:
        where_filter = {"doc_id": {"$in": query.doc_ids}}

    # sweep everything. the store ranks by cosine internally, but we re-rank
    # after the bonus, so the candidate pool has to be the full corpus.
    results = store.query(
        query_embedding=query_embedding,
        n_results=store.count(),
        where=where_filter,
    )

    search_results = []
    if results and results["ids"]:
        for i, chunk_id in enumerate(results["ids"]):
            distance = results["distances"][i] if results["distances"] else 1.0
            text = results["documents"][i]
            if is_encrypted(results["metadatas"][i]):
                # Found by meaning, never shown (and no literal-match bonus).
                text = ""
            score = (1.0 - distance) + _exact_bonus(query_tokens, text)

            if score < query.min_score:
                continue

            search_results.append(SearchResult(
                chunk_id=chunk_id,
                doc_id=results["metadatas"][i].get("doc_id", ""),
                text=text,
                score=round(score, 4),
                metadata=results["metadatas"][i],
                source="semantic",
            ))

    search_results.sort(key=lambda r: r.score, reverse=True)

    logger.info(
        "semantic search for '%s' scored %d chunks, returning %d",
        query.query[:50],
        store.count(),
        min(len(search_results), query.top_k),
    )
    return search_results[:query.top_k]


def search_papers(query: SearchQuery) -> list[dict]:
    """Papers rather than loose chunks, each carrying every chunk that matched.

    The reader pane steps between matches within a paper, so keeping only the
    best chunk would break it. `top_k` bounds papers, not chunks -- one paper
    matching twelve times is one result to the user.
    """
    # score every chunk in the corpus; top_k applies to papers below, so the
    # per-chunk cap must not truncate the rollup first.
    unbounded = SearchQuery(
        query=query.query,
        top_k=get_vector_store().count() or 1,
        doc_ids=query.doc_ids,
        min_score=query.min_score,
    )
    chunks = semantic_search(unbounded)

    papers: dict[str, dict] = {}
    for r in chunks:
        entry = papers.get(r.doc_id)
        if entry is None:
            entry = {
                "doc_id": r.doc_id,
                "score": r.score,
                "title": r.metadata.get("title", ""),
                "authors": authors_display(r.metadata.get("authors", "")),
                "year": r.metadata.get("year", ""),
                "hits": [],
            }
            papers[r.doc_id] = entry
        entry["score"] = max(entry["score"], r.score)
        entry["hits"].append({
            "chunk_id": r.chunk_id,
            "chunk_index": r.metadata.get("chunk_index", 0),
            "page": r.metadata.get("page_number", 0),
            "score": r.score,
            "text": r.text,
        })

    ranked = sorted(papers.values(), key=lambda p: p["score"], reverse=True)
    for p in ranked:
        # within a paper, reading order beats score order -- the reader pane
        # steps through matches as they appear in the document.
        p["hits"].sort(key=lambda h: h["chunk_index"])

    logger.info(
        "paper search for '%s': %d chunks across %d papers",
        query.query[:50],
        len(chunks),
        len(ranked),
    )
    return ranked[:query.top_k]
