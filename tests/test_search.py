"""unit tests for the search layer (keyword BM25 + hybrid RRF fusion).

semantic search is not unit-tested here (it needs the embedding model — a heavy
integration concern); the fusion logic that combines it is tested directly with
constructed result lists, and keyword search runs against an isolated in-memory
vector store.
"""

import pytest

from domain.search import keyword_search as kw_mod
from domain.search.hybrid_search import _reciprocal_rank_fusion
from domain.search.keyword_search import _tokenize, keyword_search
from domain.search.models import SearchQuery, SearchResult
from infrastructure.local_vector_store import VectorStore


class TestTokenize:
    def test_lowercases_and_splits(self):
        assert _tokenize("Hello World") == ["hello", "world"]

    def test_strips_punctuation(self):
        assert _tokenize("machine-learning, AI!") == ["machine", "learning", "ai"]

    def test_empty_string(self):
        assert _tokenize("") == []


@pytest.fixture
def seeded_store(tmp_path, monkeypatch):
    store = VectorStore(persist_dir=str(tmp_path / "vs"))
    store.upsert(
        ids=["c1", "c2", "c3"],
        documents=[
            "neural networks for image classification",
            "reinforcement learning for robotics control",
            "neural networks and deep learning theory",
        ],
        embeddings=[[1.0, 0.0], [0.0, 1.0], [0.8, 0.2]],
        metadatas=[{"doc_id": "d1"}, {"doc_id": "d2"}, {"doc_id": "d3"}],
    )
    monkeypatch.setattr(kw_mod, "get_vector_store", lambda: store)
    return store


class TestKeywordSearch:
    def test_finds_matching_terms(self, seeded_store):
        results = keyword_search(SearchQuery(query="neural networks", top_k=5))
        ids = [r.chunk_id for r in results]
        assert "c1" in ids and "c3" in ids  # both mention neural networks
        assert "c2" not in ids              # robotics doc has no matching terms

    def test_respects_top_k(self, seeded_store):
        results = keyword_search(SearchQuery(query="neural networks learning", top_k=1))
        assert len(results) <= 1

    def test_results_are_score_ranked(self, seeded_store):
        results = keyword_search(SearchQuery(query="neural networks", top_k=5))
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)
        assert all(r.source == "keyword" for r in results)

    def test_no_match_returns_empty(self, seeded_store):
        assert keyword_search(SearchQuery(query="quantum chromodynamics")) == []

    def test_empty_store_returns_empty(self, tmp_path, monkeypatch):
        empty = VectorStore(persist_dir=str(tmp_path / "empty"))
        monkeypatch.setattr(kw_mod, "get_vector_store", lambda: empty)
        assert keyword_search(SearchQuery(query="anything")) == []


class TestReciprocalRankFusion:
    def _r(self, cid):
        return SearchResult(chunk_id=cid, text=cid)

    def test_item_in_both_lists_ranks_highest(self):
        semantic = [self._r("a"), self._r("b")]
        keyword = [self._r("b"), self._r("c")]
        merged = _reciprocal_rank_fusion([semantic, keyword])
        # b appears in both lists -> highest fused score -> first
        assert merged[0].chunk_id == "b"
        assert {r.chunk_id for r in merged} == {"a", "b", "c"}

    def test_marks_source_hybrid(self):
        merged = _reciprocal_rank_fusion([[self._r("a")], [self._r("a")]])
        assert merged[0].source == "hybrid"

    def test_empty_inputs(self):
        assert _reciprocal_rank_fusion([[], []]) == []

    def test_dedupes_by_chunk_id(self):
        merged = _reciprocal_rank_fusion([[self._r("a")], [self._r("a")]])
        assert len(merged) == 1
