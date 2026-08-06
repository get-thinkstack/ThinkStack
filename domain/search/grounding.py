"""retrieve the passages that should ground a generation, within a budget.

This is the "show the model what the user's papers actually say" step. It runs
a semantic search for a query and assembles the winning chunks into one bounded
block of text, so a feature can say "write about X" and have the model see real
excerpts instead of inventing them.

It used to live in the chat service, which is why Scribe imported from
`domain.chat`. Chat is gone; the retrieval was never chat-specific -- it takes a
query and returns text -- so it sits here in `search/`, next to the semantic
search it is built on, and any feature that needs grounding can call it.

The budget is the point. The local context window is small, so an unbounded
context block would push out the instructions and the room the model needs to
answer. Chunks are taken best-first and truncated at the limit.
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
    """retrieve relevant chunks and assemble a bounded context block.

    args:
        query: what to retrieve for -- usually the user's question or writing
            instruction.
        doc_ids: restrict retrieval to these documents; empty/None searches the
            whole library.

    returns:
        ``(context_text, sources)``. Both are empty when the knowledge base has
        no content, which callers treat as "generate without grounding" rather
        than as an error -- a library with nothing in it is a normal state, not
        a failure.
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
