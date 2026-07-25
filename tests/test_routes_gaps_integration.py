"""integration tests for the gap-analysis route orchestration.

these verify the caching behaviour without touching the real llm: the route
must reuse cached per-document analysis (zero re-computation) and, on a cache
miss, compute once and store the result.
"""

import pytest

from api import routes_gaps
from api.routes_gaps import GapAnalysisRequest, analyze
from domain.gap_finder.models import ResearchGap, Suggestion
from infrastructure.analysis_cache import DocAnalysisCache
from infrastructure.gap_history import GapHistoryStore


@pytest.fixture
def wired(monkeypatch, tmp_path):
    """wire the route to a temp cache, fake chunks, and a recording aggregator."""
    cache = DocAnalysisCache(tmp_path / "doc_analysis.json")
    monkeypatch.setattr(routes_gaps, "doc_analysis_cache", cache)
    # isolate history so these tests don't touch the real gap_history.json
    monkeypatch.setattr(routes_gaps, "gap_history", GapHistoryStore(tmp_path / "gap_history.json"))

    def fake_chunks(doc_id):
        return {
            "ids": [f"{doc_id}_c0"],
            "documents": [f"text for {doc_id}"],
            "metadatas": [{"doc_id": doc_id}],
        }
    monkeypatch.setattr(routes_gaps, "get_chunks_by_doc_id", fake_chunks)

    calls = {"analyze_document": 0, "aggregate_args": None}

    async def fake_analyze_document(doc_id, text):
        calls["analyze_document"] += 1
        return {"summary": f"summary {doc_id}", "claims": [{"text": "c", "type": "finding"}]}
    monkeypatch.setattr(routes_gaps, "analyze_document", fake_analyze_document)

    async def fake_aggregate(summaries, claims, doc_ids):
        calls["aggregate_args"] = {"summaries": summaries, "claims": claims, "doc_ids": doc_ids}
        return [ResearchGap(gap_id="g1", description="a gap")], [Suggestion(suggestion_id="s1", title="a sug")]
    monkeypatch.setattr(routes_gaps, "analyze_gaps_and_suggestions", fake_aggregate)

    return cache, calls


async def test_cached_docs_are_not_recomputed(wired):
    cache, calls = wired
    cache.put("d1", summary="cached one", claims=[{"text": "x", "type": "finding"}])
    cache.put("d2", summary="cached two", claims=[])

    result = await analyze(GapAnalysisRequest(doc_ids=["d1", "d2"]))

    # nothing recomputed
    assert calls["analyze_document"] == 0
    assert result["papers_analyzed"] == 2
    assert result["total_gaps"] == 1
    assert result["total_suggestions"] == 1
    # the cached summaries were the ones handed to the aggregator
    summaries_texts = {s["doc_id"]: s["text"] for s in calls["aggregate_args"]["summaries"]}
    assert summaries_texts == {"d1": "cached one", "d2": "cached two"}


async def test_cache_miss_computes_once_and_stores(wired):
    cache, calls = wired

    result = await analyze(GapAnalysisRequest(doc_ids=["d1", "d2"]))

    # computed exactly once per document
    assert calls["analyze_document"] == 2
    # and the results are now cached for next time
    assert cache.get("d1") == {"summary": "summary d1", "claims": [{"text": "c", "type": "finding"}]}
    assert cache.get("d2") is not None
    # claims were assembled with their doc_id for the aggregator
    claims = calls["aggregate_args"]["claims"]
    assert {"doc_id": "d1", "text": "c", "type": "finding"} in claims
    assert result["total_claims"] == 2


async def test_second_scan_reuses_first_scans_cache(wired):
    cache, calls = wired

    await analyze(GapAnalysisRequest(doc_ids=["d1", "d2"]))
    assert calls["analyze_document"] == 2

    # a second identical scan must recompute nothing
    await analyze(GapAnalysisRequest(doc_ids=["d1", "d2"]))
    assert calls["analyze_document"] == 2  # unchanged
