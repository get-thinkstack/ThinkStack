"""durability tests for the file-backed vector store.

these prove that a save which fails part-way (simulating a crash / power loss
mid-write) never corrupts the existing ``vectors.json`` on disk.
"""

import pytest

from infrastructure.local_vector_store import VectorStore


def test_existing_store_survives_a_failed_save(tmp_path):
    store = VectorStore(persist_dir=str(tmp_path))
    store.upsert(
        ids=["a"],
        documents=["hello"],
        embeddings=[[0.1, 0.2, 0.3]],
        metadatas=[{"doc_id": "d1"}],
    )

    # sanity: the first entry is persisted and reloadable
    assert VectorStore(persist_dir=str(tmp_path)).get(ids=["a"])["ids"] == ["a"]

    # a set in metadata is not json-serializable, so the save raises mid-write
    with pytest.raises(TypeError):
        store.upsert(
            ids=["b"],
            documents=["world"],
            embeddings=[[0.4, 0.5, 0.6]],
            metadatas=[{"doc_id": "d2", "bad": {1, 2, 3}}],
        )

    # the on-disk store must still be the intact single-entry file, not a
    # truncated / corrupt one that reloads as empty
    reloaded = VectorStore(persist_dir=str(tmp_path))
    assert reloaded.get(ids=["a"])["ids"] == ["a"]
    assert reloaded.get(ids=["b"])["ids"] == []

    # and no temp file is left lying around
    assert not (tmp_path / "vectors.json.tmp").exists()
