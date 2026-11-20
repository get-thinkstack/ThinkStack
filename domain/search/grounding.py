"""Grounding: the passages a generation should be shown, within a budget.

Scribe's write-at-the-cursor calls this so the model writes from what the
selected papers say instead of inventing it. It runs semantic search and
joins the best chunks into one block, best-first, cut at the budget: the local
context window is small, and an unbounded block would crowd out the
instructions and the answer.
"""

import logging
from dataclasses import dataclass

from config import settings
from domain.search.models import SearchQuery
from domain.search.semantic_search import semantic_search
from infrastructure.local_vector_store import get_vector_store

logger = logging.getLogger(__name__)


@dataclass
class GroundingSource:
    """a knowledge-base chunk offered as grounding, and how well it matched."""
    doc_id: str = ""
    title: str = ""
    score: float = 0.0


def build_grounding_context(
    query: str,
    doc_ids: list[str] | None = None,
) -> tuple[str, list[GroundingSource]]:
    """`(context_text, sources)` for `query`, limited to `doc_ids` if given.

    Both are empty for an empty library: callers generate ungrounded, because
    an empty library is a normal state, not an error.
    """
    store = get_vector_store()
    if store.count() == 0:
        return "", []

    results = semantic_search(
        SearchQuery(
            query=query,
            top_k=settings.grounding_context_chunks,
            doc_ids=doc_ids or [],
        )
    )

    blocks: list[str] = []
    sources: list[GroundingSource] = []
    seen_docs: set[str] = set()
    budget = settings.grounding_char_budget
    used = 0

    for result in results:
        snippet = result.text.strip()
        if not snippet:
            continue
        remaining = budget - used
        if remaining <= 0:
            break
        if len(snippet) > remaining:
            snippet = snippet[:remaining]

        title = result.metadata.get("title") or result.doc_id
        blocks.append(f"[source: {title}]\n{snippet}")
        used += len(snippet)

        # one entry per document, not per chunk: the list is shown to a human as
        # "what this drew on", and the same paper listed five times is noise.
        if result.doc_id not in seen_docs:
            seen_docs.add(result.doc_id)
            sources.append(
                GroundingSource(doc_id=result.doc_id, title=title, score=result.score)
            )

    return "\n\n".join(blocks), sources
