"""unit tests for infrastructure.local_vector_store.

the store is the numpy/json-backed vector index. every test uses an isolated
tmp persist dir so nothing touches real user data. covers upsert/query/get/
update/delete plus the metadata filter and the degenerate cases (empty store,
zero-norm query, missing ids).
"""

import pytest

from infrastructure.local_vector_store import VectorStore


@pytest.fixture
def store(tmp_path):
    return VectorStore(persist_dir=str(tmp_path / "vs"))


def _seed(store):
    """three orthogonal-ish 2d vectors with simple metadata."""
    store.upsert(
        ids=["a", "b", "c"],
        documents=["doc a", "doc b", "doc c"],
        embeddings=[[1.0, 0.0], [0.0, 1.0], [0.9, 0.1]],
        metadatas=[{"kind": "x"}, {"kind": "y"}, {"kind": "x"}],
    )


class TestUpsertAndCount:
    def test_upsert_returns_count_and_persists(self, store):
        n = store.upsert(["a"], ["hello"], [[1.0, 0.0]], [{"k": 1}])
        assert n == 1
        assert store.count() == 1

    def test_upsert_existing_id_updates_in_place(self, store):
        store.upsert(["a"], ["v1"], [[1.0, 0.0]], [{"k": 1}])
        store.upsert(["a"], ["v2"], [[0.0, 1.0]], [{"k": 2}])
        assert store.count() == 1  # not duplicated
        got = store.get(ids=["a"])
        assert got["documents"] == ["v2"]

    def test_empty_store_counts_zero(self, store):
        assert store.count() == 0


class TestQuery:
    def test_returns_nearest_first(self, store):
        _seed(store)
        res = store.query([1.0, 0.0], n_results=3)
        assert res["ids"][0] == "a"  # identical direction is closest
        assert "b" in res["ids"]

    def test_respects_n_results(self, store):
        _seed(store)
        res = store.query([1.0, 0.0], n_results=1)
        assert len(res["ids"]) == 1

    def test_distances_are_sorted_ascending(self, store):
        _seed(store)
        res = store.query([1.0, 0.0], n_results=3)
        assert res["distances"] == sorted(res["distances"])

    # ── edge cases ──
    def test_query_on_empty_store_is_empty(self, store):
        res = store.query([1.0, 0.0], n_results=5)
        assert res == {"ids": [], "documents": [], "metadatas": [], "distances": []}

    def test_zero_norm_query_returns_empty(self, store):
        _seed(store)
        assert store.query([0.0, 0.0], n_results=3)["ids"] == []

    def test_where_equality_filter(self, store):
        _seed(store)
        res = store.query([1.0, 0.0], n_results=5, where={"kind": "x"})
        assert set(res["ids"]) == {"a", "c"}

    def test_where_in_operator(self, store):
        _seed(store)
        res = store.query([1.0, 0.0], n_results=5, where={"kind": {"$in": ["y"]}})
        assert res["ids"] == ["b"]

    def test_where_matching_nothing_is_empty(self, store):
        _seed(store)
        assert store.query([1.0, 0.0], where={"kind": "zzz"})["ids"] == []


class TestGetUpdateDelete:
    def test_get_by_ids(self, store):
        _seed(store)
        got = store.get(ids=["a", "c"])
        assert set(got["ids"]) == {"a", "c"}

    def test_get_by_where(self, store):
        _seed(store)
        got = store.get(where={"kind": "y"})
        assert got["ids"] == ["b"]

    def test_update_metadata_only(self, store):
        _seed(store)
        updated = store.update(ids=["a"], metadatas=[{"kind": "z"}])
        assert updated == 1
        assert store.get(ids=["a"])["metadatas"][0]["kind"] == "z"

    def test_update_missing_id_is_noop(self, store):
        _seed(store)
        assert store.update(ids=["ghost"], metadatas=[{"kind": "z"}]) == 0

    def test_delete_existing(self, store):
        _seed(store)
        assert store.delete(["a"]) == 1
        assert store.count() == 2

    def test_delete_missing_id_returns_zero(self, store):
        _seed(store)
        assert store.delete(["ghost"]) == 0
        assert store.count() == 3

    def test_delete_rebuilds_query_matrix(self, store):
        _seed(store)
        store.delete(["a"])
        # querying the deleted direction must no longer return "a"
        assert "a" not in store.query([1.0, 0.0], n_results=3)["ids"]


class TestPersistence:
    def test_reload_from_disk(self, tmp_path):
        d = str(tmp_path / "vs")
        s1 = VectorStore(persist_dir=d)
        s1.upsert(["a"], ["hello"], [[1.0, 0.0]], [{"k": 1}])
        # a fresh instance on the same dir must see the persisted vector
        s2 = VectorStore(persist_dir=d)
        assert s2.count() == 1
        assert s2.get(ids=["a"])["documents"] == ["hello"]

    def test_corrupt_store_starts_fresh(self, tmp_path):
        d = tmp_path / "vs"
        d.mkdir()
        (d / "vectors.json").write_text("{ not json")
        s = VectorStore(persist_dir=str(d))  # must not raise
        assert s.count() == 0
