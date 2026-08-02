"""integration tests: each analysis run (summarize/claims/themes) is logged to
history, and the history endpoints list/delete runs."""

import pytest
from fastapi import HTTPException

from api import routes_analysis
from api.routes_analysis import (
    AnalysisRequest,
    summarize,
    claims,
    themes,
    list_analysis_history,
    delete_analysis_run,
)
from domain.analysis.models import Summary, Claim, Theme
from infrastructure.analysis_cache import DocAnalysisCache
from infrastructure.run_history import RunHistoryStore


@pytest.fixture
def wired(monkeypatch, tmp_path):
    history = RunHistoryStore(tmp_path / "analysis_history.json")
    monkeypatch.setattr(routes_analysis, "analysis_history", history)
    # summarize and claims also write through to the per-document cache the
    # canvas reads. The module-level singleton is bound to the real data dir,
    # so without this the suite leaves entries in the developer's library.
    monkeypatch.setattr(
        routes_analysis, "doc_analysis_cache",
        DocAnalysisCache(tmp_path / "doc_analysis.json"),
    )
    monkeypatch.setattr(routes_analysis, "_get_doc_text", lambda did, pw=None: f"text {did}")

    async def fake_single(doc_id, text):
        return Summary(doc_ids=[doc_id], summary_text="a summary", key_points=["p1"], summary_type="single")
    monkeypatch.setattr(routes_analysis, "summarize_single", fake_single)

    async def fake_claims(doc_id, text):
        return [Claim(doc_id=doc_id, claim_text="c1", claim_type="finding", confidence="high")]
    monkeypatch.setattr(routes_analysis, "extract_claims", fake_claims)

    async def fake_themes(texts):
        return [Theme(theme_id="t1", label="Theme A", description="d", doc_ids=list(texts), keywords=["k"])]
    monkeypatch.setattr(routes_analysis, "cluster_by_themes", fake_themes)
    return history


async def test_summarize_is_logged(wired):
    result = await summarize(AnalysisRequest(doc_ids=["d1"]))

    assert result["run_id"]
    runs = wired.list()
    assert len(runs) == 1
    assert runs[0]["type"] == "summarize"
    assert runs[0]["doc_ids"] == ["d1"]
    assert runs[0]["result"]["summary_text"] == "a summary"


async def test_claims_is_logged(wired):
    result = await claims(AnalysisRequest(doc_ids=["d1"]))

    assert result["run_id"]
    runs = wired.list()
    assert runs[0]["type"] == "claims"
    assert runs[0]["result"]["total"] == 1


async def test_themes_is_logged(wired):
    result = await themes(AnalysisRequest(doc_ids=["d1", "d2"]))

    assert result["run_id"]
    runs = wired.list()
    assert runs[0]["type"] == "themes"
    assert runs[0]["result"]["themes"][0]["label"] == "Theme A"


async def test_runs_accumulate_newest_first(wired):
    await summarize(AnalysisRequest(doc_ids=["d1"]))
    await claims(AnalysisRequest(doc_ids=["d1"]))

    runs = wired.list()
    assert [r["type"] for r in runs] == ["claims", "summarize"]


async def test_list_and_delete_endpoints(wired):
    r = await claims(AnalysisRequest(doc_ids=["d1"]))
    listed = await list_analysis_history()
    assert listed["runs"][0]["run_id"] == r["run_id"]

    out = await delete_analysis_run(r["run_id"])
    assert out["deleted"] is True
    assert (await list_analysis_history())["runs"] == []


async def test_delete_missing_is_404(wired):
    with pytest.raises(HTTPException) as exc:
        await delete_analysis_run("nope")
    assert exc.value.status_code == 404
