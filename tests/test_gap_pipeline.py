"""Gaps + suggestions in one call: suggestions linked by index, empty on failure,
and duplicate findings merged (D-17) without merging genuinely different gaps."""

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


# ─────────────────────────── D-17: repeated gaps ───────────────────────────
#
# A tester on macOS reported the same gap listed more than once. Nothing
# de-duplicated them: every entry the model returned was given a fresh uuid, so
# two identical descriptions became two distinct gaps, each with its own id,
# each drawn on the map and each counted in "4 gaps".
#
# Small models repeat themselves, and this one is asked for a list. Treating
# the reply as a set of findings rather than as a list of rows is the fix.

def _gap(description, **kw):
    return {"description": description, "gap_type": kw.get("gap_type", "under_explored"),
            "evidence": kw.get("evidence", []), "severity": kw.get("severity", "medium"),
            "related_doc_ids": kw.get("related_doc_ids", [])}


def test_the_same_gap_twice_is_one_gap():
    gaps = gap_pipeline._parse_gaps(
        [_gap("No paper evaluates these detectors on non-stationary streams."),
         _gap("No paper evaluates these detectors on non-stationary streams.")],
        ["d1"],
    )
    assert len(gaps) == 1


def test_it_ignores_case_spacing_and_trailing_punctuation():
    """A model repeating itself rarely repeats itself byte for byte."""
    gaps = gap_pipeline._parse_gaps(
        [_gap("No paper evaluates these detectors on non-stationary streams."),
         _gap("no paper   evaluates these detectors on non-stationary streams"),
         _gap("No paper evaluates these detectors on non-stationary streams!!")],
        ["d1"],
    )
    assert len(gaps) == 1


def test_genuinely_different_gaps_are_kept():
    """The conservative half: near is not the same, and merging costs a finding."""
    gaps = gap_pipeline._parse_gaps(
        [_gap("No paper evaluates these detectors on non-stationary streams."),
         _gap("No paper evaluates these detectors on stationary streams."),
         _gap("Nothing compares the runtime cost of the two approaches.")],
        ["d1"],
    )
    assert len(gaps) == 3


def test_a_duplicate_contributes_what_it_knows():
    """Dropping the second copy must not drop evidence only it carried."""
    gaps = gap_pipeline._parse_gaps(
        [_gap("Streams are not evaluated.", evidence=["p1 says nothing"],
              related_doc_ids=["d1"], severity="low"),
         _gap("streams are not evaluated", evidence=["p2 says nothing"],
              related_doc_ids=["d2"], severity="high")],
        ["d1", "d2"],
    )
    assert len(gaps) == 1
    assert set(gaps[0].evidence) == {"p1 says nothing", "p2 says nothing"}
    assert set(gaps[0].related_doc_ids) == {"d1", "d2"}
    # the worse reading of the same finding is the one worth reporting
    assert gaps[0].severity == "high"


def test_the_ids_the_suggestions_point_at_stay_valid():
    """Suggestions reference gaps by 1-based index into the parsed list.

    De-duplicating shortens that list, so the remapping has to happen against
    what survived or a suggestion silently attaches to the wrong finding.
    """
    gaps = gap_pipeline._parse_gaps(
        [_gap("Streams are not evaluated."),
         _gap("streams are not evaluated"),
         _gap("Runtime cost is not compared.")],
        ["d1"],
    )
    suggestions = gap_pipeline._parse_suggestions(
        [{"title": "Evaluate on streams", "related_gap_indexes": [1]},
         {"title": "Benchmark runtime", "related_gap_indexes": [2]}],
        gaps,
    )
    assert len(gaps) == 2
    assert suggestions[0].related_gaps == [gaps[0].gap_id]
    assert suggestions[1].related_gaps == [gaps[1].gap_id]
