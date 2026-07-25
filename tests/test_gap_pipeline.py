"""tests for the merged gaps + suggestions analysis (single llm call)."""

import json

from infrastructure.ollama_client import ollama_client
from domain.gap_finder import gap_pipeline


def _patch_llm(monkeypatch, response):
    async def fake(prompt, system=None, max_tokens=1024, **kwargs):
        if isinstance(response, Exception):
            raise response
        return response
    monkeypatch.setattr(ollama_client, "generate_json", fake)


async def test_builds_gaps_and_links_suggestions_by_index(monkeypatch):
    _patch_llm(monkeypatch, json.dumps({
        "gaps": [
            {
                "gap_type": "contradictions",
                "description": "g one",
                "evidence": ["e1"],
                "severity": "high",
                "related_doc_ids": ["d1", "d2"],
            },
            {
                "gap_type": "under_explored",
                "description": "g two",
                "evidence": [],
                "severity": "low",
            },
        ],
        "suggestions": [
            {
                "title": "s one",
                "description": "do this",
                "rationale": "because",
                "feasibility": "high",
                "potential_impact": "medium",
                "related_gap_indexes": [1],
            },
            {
                "title": "s two",
                "description": "do that",
                "rationale": "why",
                "feasibility": "low",
                "potential_impact": "high",
                "related_gap_indexes": [2, 99],
            },
        ],
    }))

    gaps, suggestions = await gap_pipeline.analyze_gaps_and_suggestions(
        summaries=[{"doc_id": "d1", "text": "s"}],
        claims=[],
        doc_ids=["d1", "d2", "d3"],
    )

    assert [g.description for g in gaps] == ["g one", "g two"]
    assert gaps[0].gap_type == "contradictions"
    assert gaps[0].evidence == ["e1"]
    assert gaps[0].severity == "high"
    assert gaps[0].related_doc_ids == ["d1", "d2"]
    # gap ids are assigned by us and must be unique, non-empty
    assert gaps[0].gap_id and gaps[1].gap_id
    assert gaps[0].gap_id != gaps[1].gap_id
    # a gap with no related_doc_ids defaults to all analyzed docs
    assert gaps[1].related_doc_ids == ["d1", "d2", "d3"]

    # suggestions are linked to the assigned gap ids via the 1-based indexes,
    # and out-of-range indexes are dropped
    assert suggestions[0].title == "s one"
    assert suggestions[0].related_gaps == [gaps[0].gap_id]
    assert suggestions[1].related_gaps == [gaps[1].gap_id]
    assert suggestions[0].feasibility == "high"
    assert suggestions[1].potential_impact == "high"


async def test_returns_empty_on_model_error(monkeypatch):
    _patch_llm(monkeypatch, RuntimeError("model down"))
    gaps, suggestions = await gap_pipeline.analyze_gaps_and_suggestions(
        summaries=[{"doc_id": "d1", "text": "s"}], claims=[], doc_ids=["d1"],
    )
    assert gaps == []
    assert suggestions == []


async def test_returns_empty_on_unparseable_output(monkeypatch):
    _patch_llm(monkeypatch, "not json")
    gaps, suggestions = await gap_pipeline.analyze_gaps_and_suggestions(
        summaries=[{"doc_id": "d1", "text": "s"}], claims=[], doc_ids=["d1"],
    )
    assert gaps == []
    assert suggestions == []


async def test_suggestions_optional(monkeypatch):
    _patch_llm(monkeypatch, json.dumps({
        "gaps": [{"gap_type": "temporal", "description": "g", "severity": "medium"}],
    }))
    gaps, suggestions = await gap_pipeline.analyze_gaps_and_suggestions(
        summaries=[{"doc_id": "d1", "text": "s"}], claims=[], doc_ids=["d1"],
    )
    assert len(gaps) == 1
    assert suggestions == []
