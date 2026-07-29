"""
text chunker module.

splits extracted document text into overlapping chunks suitable for
embedding and retrieval. uses a recursive character splitting strategy
that respects paragraph and sentence boundaries.
"""

import logging

from config import settings
from domain.ingestion.models import TextChunk

logger = logging.getLogger(__name__)


def _estimate_tokens(text: str) -> int:
    """estimate token count using a word-based approximation.

    args:
        text: input text string.

    returns:
        estimated token count (roughly 1.3 tokens per word).
    """
    words = len(text.split())
    return int(words * 1.3)


def _split_by_separators(text: str, separators: list[str]) -> list[str]:
    """recursively split text using a hierarchy of separators.

    tries each separator in order, splitting on the first one that
    produces multiple segments. this preserves document structure by
    preferring paragraph breaks over sentence breaks over word breaks.

    args:
        text: the text to split.
        separators: ordered list of separator strings to try.

    returns:
        list of text segments.
    """
    if not separators:
        return [text]

    separator = separators[0]
    remaining = separators[1:]

    parts = text.split(separator)
    parts = [p.strip() for p in parts if p.strip()]

    if len(parts) <= 1:
        return _split_by_separators(text, remaining) if remaining else [text]

    return parts


def chunk_text(
    text: str,
    doc_id: str,
    chunk_size: int = settings.chunk_size,
    chunk_overlap: int = settings.chunk_overlap,
) -> list[TextChunk]:
    """split document text into overlapping chunks for embedding.

    uses a recursive character splitting strategy that respects natural
    text boundaries (paragraphs, sentences, words). chunks are created
    with configurable size and overlap to ensure context continuity.

    args:
        text: the full document text to chunk.
        doc_id: the parent document identifier.
        chunk_size: target token count per chunk.
        chunk_overlap: number of overlapping tokens between chunks.

    returns:
        list of TextChunk objects with unique ids and positional info.
    """
    # empty / whitespace-only input yields no chunks. without this guard the
    # splitter bottoms out at [""] and emits a single empty chunk, which would
    # then be embedded and stored as a junk zero-vector.
    if not text or not text.strip():
        return []

    separators = ["\n\n", "\n", ". ", " "]
    segments = _split_by_separators(text, separators)

    chunks = []
    current_chunk = []
    current_tokens = 0

    for segment in segments:
        segment_tokens = _estimate_tokens(segment)

        if current_tokens + segment_tokens > chunk_size and current_chunk:
            chunk_text_content = " ".join(current_chunk)
            chunks.append(chunk_text_content)

            overlap_tokens = 0
            overlap_parts = []
            for part in reversed(current_chunk):
                part_tokens = _estimate_tokens(part)
                if overlap_tokens + part_tokens > chunk_overlap:
                    break
                overlap_parts.insert(0, part)
                overlap_tokens += part_tokens

            current_chunk = overlap_parts
            current_tokens = overlap_tokens

        current_chunk.append(segment)
        current_tokens += segment_tokens

    if current_chunk:
        chunks.append(" ".join(current_chunk))

    result = []
    for i, chunk_content in enumerate(chunks):
        result.append(TextChunk(
            chunk_id=f"{doc_id}_chunk_{i:04d}",
            doc_id=doc_id,
            text=chunk_content,
            chunk_index=i,
            token_count=_estimate_tokens(chunk_content),
        ))

    logger.info("created %d chunks from document %s", len(result), doc_id)
    return result


def chunk_pages(
    pages: list[dict],
    doc_id: str,
    chunk_size: int = settings.chunk_size,
    chunk_overlap: int = settings.chunk_overlap,
) -> list[TextChunk]:
    """chunk text while preserving page number information.

    processes each page individually and then merges small page chunks
    to reach the target chunk size, tracking which page each chunk
    originates from.

    args:
        pages: list of dicts with page_number and text keys.
        doc_id: the parent document identifier.
        chunk_size: target token count per chunk.
        chunk_overlap: number of overlapping tokens between chunks.

    returns:
        list of TextChunk objects with page numbers set.
    """
    full_text = "\n\n".join(p["text"] for p in pages)
    chunks = chunk_text(full_text, doc_id, chunk_size, chunk_overlap)

    for chunk in chunks:
        best_page = 0
        best_overlap = 0
        for page in pages:
            # count character overlap between chunk text and page text
            overlap = sum(
                1 for word in chunk.text.split()[:20]
                if word in page["text"]
            )
            if overlap > best_overlap:
                best_overlap = overlap
                best_page = page["page_number"]
        chunk.page_number = best_page

    return chunks
