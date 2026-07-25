"""tests for the per-document analysis cache."""

from infrastructure.analysis_cache import DocAnalysisCache


def test_put_then_get_round_trips(tmp_path):
    cache = DocAnalysisCache(tmp_path / "doc_analysis.json")
    claims = [{"text": "c1", "type": "finding"}]

    cache.put("doc1", summary="a summary", claims=claims)
    got = cache.get("doc1")

    assert got == {"summary": "a summary", "claims": claims}


def test_get_missing_returns_none(tmp_path):
    cache = DocAnalysisCache(tmp_path / "doc_analysis.json")
    assert cache.get("nope") is None


def test_entries_persist_across_instances(tmp_path):
    path = tmp_path / "doc_analysis.json"
    DocAnalysisCache(path).put("doc1", summary="s", claims=[])

    # a fresh instance reads what the previous one wrote
    assert DocAnalysisCache(path).get("doc1") == {"summary": "s", "claims": []}


def test_delete_removes_and_persists(tmp_path):
    path = tmp_path / "doc_analysis.json"
    cache = DocAnalysisCache(path)
    cache.put("doc1", summary="s", claims=[])

    cache.delete("doc1")

    assert cache.get("doc1") is None
    assert DocAnalysisCache(path).get("doc1") is None


def test_delete_missing_is_a_noop(tmp_path):
    cache = DocAnalysisCache(tmp_path / "doc_analysis.json")
    cache.delete("nope")  # must not raise


def test_corrupt_file_is_handled_gracefully(tmp_path):
    path = tmp_path / "doc_analysis.json"
    path.write_text("{ not valid json", encoding="utf-8")

    cache = DocAnalysisCache(path)
    assert cache.get("doc1") is None

    # and it recovers: writes still work over the corrupt file
    cache.put("doc1", summary="s", claims=[])
    assert DocAnalysisCache(path).get("doc1") == {"summary": "s", "claims": []}
