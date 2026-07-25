"""unit tests for domain.ingestion.chunker.

covers token estimation, the recursive separator split, chunk assembly with
overlap, and page-number attribution — plus the empty/whitespace/single-token
edge cases that must not crash or produce junk chunks.
"""

from domain.ingestion.chunker import (
    _estimate_tokens,
    _split_by_separators,
    chunk_pages,
    chunk_text,
)


class TestEstimateTokens:
    def test_word_based_estimate(self):
        assert _estimate_tokens("one two three") == int(3 * 1.3)

    def test_empty_string_is_zero(self):
        assert _estimate_tokens("") == 0

    def test_whitespace_only_is_zero(self):
        assert _estimate_tokens("   \n\t ") == 0


class TestSplitBySeparators:
    def test_splits_on_first_effective_separator(self):
        assert _split_by_separators("a\n\nb\n\nc", ["\n\n", "\n"]) == ["a", "b", "c"]

    def test_falls_through_to_next_separator(self):
        # no double-newline, so it should split on single newline
        assert _split_by_separators("a\nb", ["\n\n", "\n"]) == ["a", "b"]

    def test_unsplittable_text_returns_whole(self):
        assert _split_by_separators("abc", ["\n\n", "\n"]) == ["abc"]

    def test_strips_and_drops_empty_segments(self):
        assert _split_by_separators("a\n\n\n\n  \n\nb", ["\n\n"]) == ["a", "b"]


class TestChunkText:
    def test_short_text_is_single_chunk(self):
        chunks = chunk_text("a short sentence.", doc_id="d1")
        assert len(chunks) == 1
        assert chunks[0].doc_id == "d1"
        assert chunks[0].chunk_index == 0

    def test_chunk_ids_are_ordered_and_formatted(self):
        text = ". ".join(f"sentence number {i} with several words" for i in range(200))
        chunks = chunk_text(text, doc_id="d1", chunk_size=50, chunk_overlap=10)
        assert len(chunks) > 1
        assert chunks[0].chunk_id == "d1_chunk_0000"
        assert chunks[1].chunk_id == "d1_chunk_0001"
        assert [c.chunk_index for c in chunks] == list(range(len(chunks)))

    def test_each_chunk_respects_size_roughly(self):
        text = ". ".join(f"word{i} filler filler filler" for i in range(300))
        chunks = chunk_text(text, doc_id="d1", chunk_size=40, chunk_overlap=5)
        # allow one segment of spill, but no chunk should be wildly over budget
        assert all(c.token_count <= 40 * 2 for c in chunks)

    def test_token_count_is_populated(self):
        chunks = chunk_text("alpha beta gamma delta.", doc_id="d1")
        assert chunks[0].token_count > 0

    # ── edge cases ──
    def test_empty_text_produces_no_chunks(self):
        assert chunk_text("", doc_id="d1") == []

    def test_whitespace_only_produces_no_chunks(self):
        assert chunk_text("   \n\n  ", doc_id="d1") == []

    def test_single_word(self):
        chunks = chunk_text("word", doc_id="d1")
        assert len(chunks) == 1
        assert chunks[0].text == "word"


class TestChunkPages:
    def test_assigns_page_numbers(self):
        pages = [
            {"page_number": 1, "text": "alpha beta gamma " * 20},
            {"page_number": 2, "text": "delta epsilon zeta " * 20},
        ]
        chunks = chunk_pages(pages, doc_id="d1", chunk_size=30, chunk_overlap=5)
        assert chunks, "expected at least one chunk"
        # every chunk gets attributed to one of the real pages
        assert all(c.page_number in (1, 2) for c in chunks)

    def test_single_page(self):
        pages = [{"page_number": 7, "text": "only page content here " * 10}]
        chunks = chunk_pages(pages, doc_id="d1", chunk_size=30, chunk_overlap=5)
        assert all(c.page_number == 7 for c in chunks)
