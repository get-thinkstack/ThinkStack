"""integration tests: a completed scan is logged to history, and the history
endpoints list/delete runs."""

import pytest
from fastapi import HTTPException

from api import routes_gaps
from api.routes_gaps import (
    GapAnalysisRequest,
    analyze,
    list_history,
    delete_history_run,
)
from domain.gap_finder.models import ResearchGap, Suggestion
from infrastructure.analysis_cache import DocAnalysisCache
from infrastructure.gap_history import GapHistoryStore


@pytest.fixture
def wired(monkeypatch, tmp_path):
    monkeypatch.setattr(routes_gaps, "doc_analysis_cache", DocAnalysisCache(tmp_path / "c.json"))
    history = GapHistoryStore(tmp_path / "h.json")
    monkeypatch.setattr(routes_gaps, "gap_history", history)
    monkeypatch.setattr(routes_gaps, "get_chunks_by_doc_id", lambda did: {
        "ids": [f"{did}_c"], "documents": [f"t {did}"], "metadatas": [{"doc_id": did}],
    })

    async def fake_ad(doc_id, text):
        return {"summary": f"s {doc_id}", "claims": [{"text": "c", "type": "finding"}]}
    monkeypatch.setattr(routes_gaps, "analyze_document", fake_ad)

    async def fake_agg(summaries, claims, doc_ids):
        return (
            [ResearchGap(gap_id="g1", description="a gap")],
            [Suggestion(suggestion_id="s1", title="a sug", related_gaps=["g1"])],
        )
    monkeypatch.setattr(routes_gaps, "analyze_gaps_and_suggestions", fake_agg)
    return history


async def test_scan_is_logged_to_history(wired):
    result = await analyze(GapAnalysisRequest(doc_ids=["d1", "d2"]))

    assert result["run_id"]
    runs = wired.list()
    assert len(runs) == 1
    assert runs[0]["run_id"] == result["run_id"]
    assert runs[0]["doc_ids"] == ["d1", "d2"]
    assert runs[0]["papers_analyzed"] == 2
    assert runs[0]["gaps"][0]["description"] == "a gap"
    assert runs[0]["suggestions"][0]["related_gaps"] == ["g1"]


async def test_new_scan_does_not_erase_previous(wired):
    await analyze(GapAnalysisRequest(doc_ids=["d1", "d2"]))
    await analyze(GapAnalysisRequest(doc_ids=["d1", "d2"]))

    assert len(wired.list()) == 2  # both retained, newest first


async def test_list_history_endpoint(wired):
    result = await analyze(GapAnalysisRequest(doc_ids=["d1", "d2"]))
    out = await list_history()
    assert out["runs"][0]["run_id"] == result["run_id"]


async def test_delete_history_endpoint(wired):
    result = await analyze(GapAnalysisRequest(doc_ids=["d1", "d2"]))
    out = await delete_history_run(result["run_id"])
    assert out["deleted"] is True
    assert (await list_history())["runs"] == []


async def test_delete_missing_run_is_404(wired):
    with pytest.raises(HTTPException) as exc:
        await delete_history_run("nope")
    assert exc.value.status_code == 404
