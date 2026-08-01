"""unit tests for the semantic search layer.

the embedding model itself is a heavy integration concern, so it is stubbed
here: every test supplies its own query vector and a small hand-built vector
store. what is under test is the ranking contract -- full-corpus sweep, the
exact-token bonus, and the per-paper rollup -- not MiniLM's judgement.
"""

import pytest

from domain.search import semantic_search as sem_mod
from domain.search.semantic_search import (
    EXACT_TOKEN_BONUS,
    _exact_bonus,
    _tokenize,
    search_papers,
    semantic_search,
)
from domain.search.models import SearchQuery
from infrastructure.local_vector_store import VectorStore


class TestTokenize:
    def test_lowercases_and_splits(self):
        assert _tokenize("Hello World") == ["hello", "world"]

    def test_strips_punctuation(self):
        assert _tokenize("machine-learning, AI!") == ["machine", "learning", "ai"]

    def test_empty_string(self):
        assert _tokenize("") == []


class TestExactBonus:
    def test_no_query_tokens_scores_zero(self):
        assert _exact_bonus([], "anything at all") == 0.0

    def test_all_tokens_present_scores_full(self):
        assert _exact_bonus(["neural", "nets"], "neural nets rule") == EXACT_TOKEN_BONUS

    def test_partial_match_scores_proportionally(self):
        assert _exact_bonus(["neural", "nets"], "neural only") == EXACT_TOKEN_BONUS / 2

    def test_absent_tokens_score_zero(self):
        assert _exact_bonus(["quantum"], "neural nets rule") == 0.0


@pytest.fixture
def store(tmp_path, monkeypatch):
    """three chunks across two papers, with hand-chosen vectors.

    c1 and c3 sit at the same angle, so cosine alone ties them and the
    exact-token bonus is the only thing that can separate them.
    """
    vs = VectorStore(persist_dir=str(tmp_path / "vs"))
    vs.upsert(
        ids=["c1", "c2", "c3"],
        documents=[
            "federated averaging across hospital sites",
            "reinforcement learning for robotics control",
            "training jointly without centralising records, via FedAvg",
        ],
        embeddings=[[1.0, 0.0], [0.0, 1.0], [1.0, 0.0]],
        metadatas=[
            {"doc_id": "d1", "chunk_index": 0, "page_number": 1, "title": "Fed A"},
            {"doc_id": "d2", "chunk_index": 0, "page_number": 1, "title": "RL"},
            {"doc_id": "d1", "chunk_index": 1, "page_number": 4, "title": "Fed A"},
        ],
    )
    monkeypatch.setattr(sem_mod, "get_vector_store", lambda: vs)
    return vs


def _stub_embedding(monkeypatch, vector):
    monkeypatch.setattr(sem_mod, "generate_embedding", lambda _q: vector)


class TestSemanticSearch:
    def test_empty_store_returns_empty(self, tmp_path, monkeypatch):
        empty = VectorStore(persist_dir=str(tmp_path / "empty"))
        monkeypatch.setattr(sem_mod, "get_vector_store", lambda: empty)
        assert semantic_search(SearchQuery(query="anything")) == []

    def test_ranks_by_cosine(self, store, monkeypatch):
        _stub_embedding(monkeypatch, [0.0, 1.0])
        results = semantic_search(SearchQuery(query="robots", top_k=1))
        assert results[0].chunk_id == "c2"

    def test_exact_token_breaks_a_cosine_tie(self, store, monkeypatch):
        # c1 and c3 are cosine-identical; only c3 contains "fedavg" verbatim.
        _stub_embedding(monkeypatch, [1.0, 0.0])
        results = semantic_search(SearchQuery(query="FedAvg", top_k=3))
        assert results[0].chunk_id == "c3"
        assert results[0].score > results[1].score

    def test_bonus_cannot_outrank_a_better_semantic_match(self, store, monkeypatch):
        # query points exactly at c2, which shares no literal token with it.
        # c1/c3 match "hospital"/"records" lexically but are orthogonal.
        _stub_embedding(monkeypatch, [0.0, 1.0])
        results = semantic_search(SearchQuery(query="hospital records", top_k=3))
        assert results[0].chunk_id == "c2"

    def test_sweeps_whole_corpus_not_just_top_k(self, store, monkeypatch):
        """top_k caps the output, but every chunk must be scored first.

        the old build passed top_k down to the store, so a chunk outside the
        first k by raw cosine could never receive its exact-token bonus.
        """
        _stub_embedding(monkeypatch, [1.0, 0.0])
        results = semantic_search(SearchQuery(query="FedAvg", top_k=1))
        assert len(results) == 1
        assert results[0].chunk_id == "c3"   # only reachable via a full sweep

    def test_min_score_filters(self, store, monkeypatch):
        _stub_embedding(monkeypatch, [0.0, 1.0])
        results = semantic_search(SearchQuery(query="robots", top_k=5, min_score=0.9))
        assert [r.chunk_id for r in results] == ["c2"]

    def test_doc_ids_filter(self, store, monkeypatch):
        _stub_embedding(monkeypatch, [1.0, 0.0])
        results = semantic_search(SearchQuery(query="anything", top_k=5, doc_ids=["d2"]))
        assert {r.doc_id for r in results} == {"d2"}

    def test_marks_source_semantic(self, store, monkeypatch):
        _stub_embedding(monkeypatch, [1.0, 0.0])
        assert all(r.source == "semantic" for r in semantic_search(SearchQuery(query="x")))


class TestSearchPapers:
    def test_groups_chunks_under_their_paper(self, store, monkeypatch):
        _stub_embedding(monkeypatch, [1.0, 0.0])
        papers = search_papers(SearchQuery(query="federated", top_k=5))
        d1 = next(p for p in papers if p["doc_id"] == "d1")
        assert len(d1["hits"]) == 2          # both c1 and c3, not just the best
        assert {h["chunk_id"] for h in d1["hits"]} == {"c1", "c3"}

    def test_paper_score_is_its_best_chunk(self, store, monkeypatch):
        _stub_embedding(monkeypatch, [1.0, 0.0])
        papers = search_papers(SearchQuery(query="FedAvg", top_k=5))
        d1 = next(p for p in papers if p["doc_id"] == "d1")
        assert d1["score"] == max(h["score"] for h in d1["hits"])

    def test_hits_are_in_reading_order(self, store, monkeypatch):
        _stub_embedding(monkeypatch, [1.0, 0.0])
        papers = search_papers(SearchQuery(query="FedAvg", top_k=5))
        d1 = next(p for p in papers if p["doc_id"] == "d1")
        indices = [h["chunk_index"] for h in d1["hits"]]
        assert indices == sorted(indices)

    def test_papers_ranked_by_best_chunk(self, store, monkeypatch):
        _stub_embedding(monkeypatch, [1.0, 0.0])
        papers = search_papers(SearchQuery(query="federated", top_k=5))
        assert papers[0]["doc_id"] == "d1"
        assert [p["score"] for p in papers] == sorted(
            (p["score"] for p in papers), reverse=True
        )

    def test_top_k_bounds_papers_not_chunks(self, store, monkeypatch):
        _stub_embedding(monkeypatch, [1.0, 0.0])
        papers = search_papers(SearchQuery(query="federated", top_k=1))
        assert len(papers) == 1
        assert len(papers[0]["hits"]) == 2   # the paper keeps all its matches

    def test_carries_paper_metadata(self, store, monkeypatch):
        _stub_embedding(monkeypatch, [1.0, 0.0])
        papers = search_papers(SearchQuery(query="federated", top_k=5))
        assert next(p for p in papers if p["doc_id"] == "d1")["title"] == "Fed A"

    def test_empty_store_returns_empty(self, tmp_path, monkeypatch):
        empty = VectorStore(persist_dir=str(tmp_path / "empty"))
        monkeypatch.setattr(sem_mod, "get_vector_store", lambda: empty)
        assert search_papers(SearchQuery(query="anything")) == []
