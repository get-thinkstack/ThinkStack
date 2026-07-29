"""tests for the gap-analysis run history store."""

from infrastructure.gap_history import GapHistoryStore


def _run(**over):
    base = {
        "doc_ids": ["d1", "d2"],
        "papers_analyzed": 2,
        "gaps": [{"gap_id": "g1", "description": "a gap"}],
        "suggestions": [{"suggestion_id": "s1", "title": "a sug"}],
        "total_claims": 4,
        "total_gaps": 1,
        "total_suggestions": 1,
    }
    base.update(over)
    return base


def test_add_assigns_id_and_timestamp_and_returns_saved(tmp_path):
    store = GapHistoryStore(tmp_path / "gap_history.json")
    saved = store.add(_run())

    assert saved["run_id"]
    assert saved["created_at"]
    assert saved["papers_analyzed"] == 2
    assert saved["gaps"] == [{"gap_id": "g1", "description": "a gap"}]


def test_list_is_newest_first(tmp_path):
    store = GapHistoryStore(tmp_path / "gap_history.json")
    first = store.add(_run(papers_analyzed=2))
    second = store.add(_run(papers_analyzed=3))

    runs = store.list()
    assert [r["run_id"] for r in runs] == [second["run_id"], first["run_id"]]


def test_get_by_id_and_missing(tmp_path):
    store = GapHistoryStore(tmp_path / "gap_history.json")
    saved = store.add(_run())

    assert store.get(saved["run_id"])["run_id"] == saved["run_id"]
    assert store.get("nope") is None


def test_delete_removes_and_reports(tmp_path):
    store = GapHistoryStore(tmp_path / "gap_history.json")
    saved = store.add(_run())

    assert store.delete(saved["run_id"]) is True
    assert store.get(saved["run_id"]) is None
    assert store.delete(saved["run_id"]) is False  # already gone


def test_retention_cap_keeps_newest(tmp_path):
    store = GapHistoryStore(tmp_path / "gap_history.json", max_runs=3)
    ids = [store.add(_run(papers_analyzed=i))["run_id"] for i in range(5)]

    kept = [r["run_id"] for r in store.list()]
    assert kept == [ids[4], ids[3], ids[2]]  # 3 newest, newest first


def test_persists_across_instances(tmp_path):
    path = tmp_path / "gap_history.json"
    saved = GapHistoryStore(path).add(_run())

    reloaded = GapHistoryStore(path)
    assert reloaded.get(saved["run_id"])["run_id"] == saved["run_id"]


def test_corrupt_file_is_tolerated(tmp_path):
    path = tmp_path / "gap_history.json"
    path.write_text("{ broken", encoding="utf-8")

    store = GapHistoryStore(path)
    assert store.list() == []
    saved = store.add(_run())  # still works over the corrupt file
    assert GapHistoryStore(path).get(saved["run_id"]) is not None
