"""
chat service module.

implements a retrieval-augmented (rag) chat assistant for asking
questions about the paper collection. relevant chunks are retrieved
from the vector store and used as grounding context, so the prompt
stays small and inference is fast regardless of library size.

generation goes through the shared ``ollama_client``, which abstracts
both the llama.cpp and ollama runtimes -- so the assistant works with
either backend selected via ``settings.llm_provider``.
"""

import logging

from config import settings
from domain.chat.models import ChatAnswer, ChatSource, ChatTurn
from domain.search.models import SearchQuery
from domain.search.semantic_search import semantic_search
from infrastructure.local_vector_store import get_vector_store
from infrastructure.ollama_client import ollama_client

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "you are thinkstack, a concise research assistant. answer the user's "
    "question using the provided context from their research papers and any "
    "current analysis results. ground your answer in the context; if the "
    "context does not contain the answer, say so briefly and answer from "
    "general knowledge, making clear it is not from their papers. keep "
    "answers focused and avoid inventing citations."
)

# only the most recent turns are replayed to keep the prompt small.
_MAX_HISTORY_TURNS = 4


def _build_context(question: str, doc_ids: list[str]) -> tuple[str, list[ChatSource]]:
    """retrieve relevant chunks and assemble a bounded context block.

    args:
        question: the user's question, used as the retrieval query.
        doc_ids: optional document ids to restrict retrieval to.

    returns:
        a tuple of (context_text, sources). both are empty when the
        knowledge base has no content.
    """
    store = get_vector_store()
    if store.count() == 0:
        return "", []

    results = semantic_search(
        SearchQuery(
            query=question,
            top_k=settings.chat_context_chunks,
            doc_ids=doc_ids or [],
        )
    )

    blocks: list[str] = []
    sources: list[ChatSource] = []
    seen_docs: set[str] = set()
    budget = settings.chat_context_char_budget
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

        if result.doc_id not in seen_docs:
            seen_docs.add(result.doc_id)
            sources.append(
                ChatSource(doc_id=result.doc_id, title=title, score=result.score)
            )

    return "\n\n".join(blocks), sources


def _format_history(history: list[ChatTurn]) -> str:
    """render the most recent turns into a compact transcript."""
    if not history:
        return ""
    recent = history[-_MAX_HISTORY_TURNS:]
    lines = [f"{turn.role}: {turn.content}".strip() for turn in recent if turn.content]
    return "\n".join(lines)


async def answer_question(
    question: str,
    doc_ids: list[str] | None = None,
    history: list[ChatTurn] | None = None,
    analysis_context: str = "",
) -> ChatAnswer:
    """answer a question using retrieved paper context and the local llm.

    args:
        question: the user's question.
        doc_ids: optional ids to scope retrieval to selected papers.
        history: prior conversation turns for continuity.
        analysis_context: optional summary/claims/themes text from the
            current analysis view, supplied verbatim as extra grounding.

    returns:
        a ChatAnswer with the reply and the sources used.
    """
    question = (question or "").strip()
    if not question:
        return ChatAnswer(answer="please enter a question.", sources=[])

    context_text, sources = _build_context(question, doc_ids or [])

    prompt_parts: list[str] = []
    if analysis_context.strip():
        prompt_parts.append(f"current analysis results:\n{analysis_context.strip()}")
    if context_text:
        prompt_parts.append(f"context from the user's papers:\n{context_text}")
    else:
        prompt_parts.append(
            "context from the user's papers: (no relevant passages found)"
        )

    transcript = _format_history(history or [])
    if transcript:
        prompt_parts.append(f"conversation so far:\n{transcript}")

    prompt_parts.append(f"question: {question}")
    prompt = "\n\n".join(prompt_parts)

    try:
        reply = await ollama_client.generate(
            prompt,
            system=SYSTEM_PROMPT,
            temperature=0.3,
            max_tokens=settings.chat_max_tokens,
        )
    except Exception as e:  # noqa: BLE001 - surface a friendly message to the ui
        logger.error("chat generation failed: %s", e)
        return ChatAnswer(
            answer=f"sorry, generation failed: {e}",
            sources=sources,
            used_context=bool(context_text),
        )

    return ChatAnswer(
        answer=reply.strip(),
        sources=sources,
        used_context=bool(context_text),
    )
