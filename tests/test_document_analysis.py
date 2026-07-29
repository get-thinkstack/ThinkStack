"""tests for the single-call per-document summary+claims analysis."""

import json

from infrastructure.ollama_client import ollama_client
from domain.analysis import document_analysis


def _patch_llm(monkeypatch, response):
    """replace the llm call with one returning ``response`` (str or exception)."""
    async def fake(prompt, system=None, max_tokens=1024, **kwargs):
        if isinstance(response, Exception):
            raise response
        return response
    monkeypatch.setattr(ollama_client, "generate_json", fake)


async def test_returns_summary_and_normalized_claims(monkeypatch):
    _patch_llm(monkeypatch, json.dumps({
        "summary": "this paper does X.",
        "claims": [
            {"claim_text": "finding one", "claim_type": "finding"},
            {"claim_text": "limitation two", "claim_type": "limitation"},
        ],
    }))

    result = await document_analysis.analyze_document("doc1", "some paper text")

    assert result["summary"] == "this paper does X."
    assert result["claims"] == [
        {"text": "finding one", "type": "finding"},
        {"text": "limitation two", "type": "limitation"},
    ]


async def test_missing_claims_defaults_to_empty(monkeypatch):
    _patch_llm(monkeypatch, json.dumps({"summary": "s"}))

    result = await document_analysis.analyze_document("doc1", "text")

    assert result == {"summary": "s", "claims": []}


async def test_claim_type_defaults_when_absent(monkeypatch):
    _patch_llm(monkeypatch, json.dumps({
        "summary": "s",
        "claims": [{"claim_text": "no type given"}],
    }))

    result = await document_analysis.analyze_document("doc1", "text")

    assert result["claims"] == [{"text": "no type given", "type": "finding"}]


async def test_returns_none_when_model_errors(monkeypatch):
    _patch_llm(monkeypatch, RuntimeError("model down"))
    assert await document_analysis.analyze_document("doc1", "text") is None


async def test_returns_none_on_unparseable_output(monkeypatch):
    _patch_llm(monkeypatch, "not json at all")
    assert await document_analysis.analyze_document("doc1", "text") is None
