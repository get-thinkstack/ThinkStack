"""Encrypting a paper hides it at rest: chunk text and the stored PDF.

Before this, encrypting only ADDED an encrypted copy. The chunk text stayed
plaintext in the store, the PDF stayed plaintext on disk, and
`GET /api/documents/{id}` returned the whole paper with no password. These
tests run the real routes over a real store in tmp_path, with a cheap KDF.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import infrastructure.local_vector_store as LVS
from config import settings
from domain.encryption import kdf
from infrastructure.analysis_cache import doc_analysis_cache

SECRET_PDF = b"%PDF-1.4 SECRET-PDF-BYTES"
TEXTS = ["the secret alpha passage", "the secret beta passage"]
PASSWORD = "correct horse"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(kdf, "TIME_COST", 1)
    monkeypatch.setattr(kdf, "MEMORY_COST_KIB", 8)
    monkeypatch.setattr(kdf, "PARALLELISM", 1)

    papers = tmp_path / "papers"
    papers.mkdir()
    monkeypatch.setattr(settings, "papers_dir", papers)
    (papers / "d1_paper.pdf").write_bytes(SECRET_PDF)

    store = LVS.VectorStore(str(tmp_path / "vs"))
    store.upsert(
        ids=["d1_0", "d1_1"],
        documents=list(TEXTS),
        embeddings=[[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]],
        metadatas=[
            {"doc_id": "d1", "title": "T", "chunk_index": 0},
            {"doc_id": "d1", "title": "T", "chunk_index": 1},
        ],
    )
    monkeypatch.setattr(LVS, "_store_instance", store)
    monkeypatch.setattr(doc_analysis_cache, "_path", tmp_path / "cache.json")
    monkeypatch.setattr(doc_analysis_cache, "_entries", {})

    from api.routes_documents import router as docs
    from api.routes_encryption import router as enc
    app = FastAPI()
    app.include_router(docs, prefix="/api/documents")
    app.include_router(enc, prefix="/api/encryption")
    c = TestClient(app)
    c.tmp = tmp_path
    c.papers = papers
    return c


def _encrypt(client):
    r = client.post("/api/encryption/encrypt", json={"doc_id": "d1", "password": PASSWORD})
    assert r.status_code == 200, r.text


def _stored_texts(client):
    fresh = LVS.VectorStore(str(client.tmp / "vs"))      # what is on DISK
    return fresh.get(where={"doc_id": "d1"})["documents"]


def test_no_chunk_text_is_left_on_disk(client):
    _encrypt(client)
    assert all("secret" not in t for t in _stored_texts(client))


def test_the_stored_pdf_is_no_longer_plaintext(client):
    _encrypt(client)
    for f in client.papers.iterdir():
        assert b"SECRET-PDF-BYTES" not in f.read_bytes(), f.name


def test_the_document_route_returns_no_text_without_a_password(client):
    _encrypt(client)
    body = client.get("/api/documents/d1").json()
    assert "secret" not in body["full_text"]
    assert all("secret" not in c["text"] for c in body["chunks"])


def test_a_paper_encrypted_the_old_way_is_not_served_either(client):
    """Papers encrypted before the fix still hold plaintext chunks."""
    store = LVS._store_instance
    for cid in ("d1_0", "d1_1"):
        meta = store.get(ids=[cid])["metadatas"][0]
        store.update([cid], [{**meta, "is_encrypted": "true"}])
    body = client.get("/api/documents/d1").json()
    assert "secret" not in body["full_text"]


def test_the_password_still_reads_the_text(client):
    _encrypt(client)
    r = client.post("/api/encryption/decrypt", json={"doc_id": "d1", "password": PASSWORD})
    assert r.json()["full_text"] == " ".join(TEXTS)


def test_removing_encryption_restores_chunks_and_pdf_exactly(client):
    _encrypt(client)
    r = client.post("/api/encryption/remove", json={"doc_id": "d1", "password": PASSWORD})
    assert r.status_code == 200, r.text
    assert _stored_texts(client) == TEXTS
    assert (client.papers / "d1_paper.pdf").read_bytes() == SECRET_PDF


def test_a_wrong_password_changes_nothing(client):
    _encrypt(client)
    r = client.post("/api/encryption/remove", json={"doc_id": "d1", "password": "nope"})
    assert r.status_code == 403
    assert all("secret" not in t for t in _stored_texts(client))


def test_the_cached_summary_goes_with_the_text(client):
    doc_analysis_cache.put("d1", "a summary of the secret", [])
    _encrypt(client)
    assert doc_analysis_cache.get("d1") is None


def test_an_encrypted_paper_stays_in_the_library(client):
    _encrypt(client)
    listed = client.get("/api/documents").json()["documents"]
    assert [d["doc_id"] for d in listed] == ["d1"]
    assert listed[0]["filename"] == "paper.pdf"
    assert client.get("/api/documents/d1").status_code == 200


def test_deleting_an_encrypted_paper_leaves_no_ciphertext_behind(client):
    _encrypt(client)
    client.delete("/api/documents/d1")
    assert list(client.papers.iterdir()) == []


def test_analysis_with_the_password_reads_the_paper_not_the_envelope(client):
    from api.routes_analysis import _get_doc_text
    from api.routes_gaps import _decrypt_or_join
    from domain.knowledge_base.repository import get_chunks_by_doc_id

    _encrypt(client)
    assert _get_doc_text("d1", PASSWORD) == " ".join(TEXTS)
    assert _decrypt_or_join("d1", get_chunks_by_doc_id("d1"), PASSWORD) == " ".join(TEXTS)


def test_search_never_returns_an_encrypted_papers_text(client, monkeypatch):
    """Covers papers locked before text was blanked at rest."""
    import domain.search.semantic_search as S
    from domain.search.models import SearchQuery

    store = LVS._store_instance
    for cid in ("d1_0", "d1_1"):
        meta = store.get(ids=[cid])["metadatas"][0]
        store.update([cid], [{**meta, "is_encrypted": "true"}])
    monkeypatch.setattr(S, "generate_embedding", lambda q: [1.0, 0.0, 0.0, 0.0])

    hits = S.semantic_search(SearchQuery(query="secret alpha"))
    assert hits, "an encrypted paper is still findable"
    assert all("secret" not in h.text for h in hits)


@pytest.fixture
def histories(tmp_path, monkeypatch):
    from infrastructure.analysis_history import analysis_history
    from infrastructure.gap_history import gap_history
    for store, name in ((analysis_history, "a.json"), (gap_history, "g.json")):
        monkeypatch.setattr(store, "_path", tmp_path / name)
        monkeypatch.setattr(store, "_runs", [])
    return analysis_history, gap_history


def test_runs_that_quote_the_paper_go_with_it(client, histories):
    analysis, gaps = histories
    analysis.add({"type": "summarize", "doc_ids": ["d1"], "summary_text": "the secret"})
    analysis.add({"type": "summarize", "doc_ids": ["other"], "summary_text": "fine"})
    analysis.add({"type": "themes", "doc_ids": ["d1", "other"], "themes": [{"label": "X"}]})
    gaps.add({"doc_ids": ["d1", "other"], "gaps": [{"description": "the secret gap"}]})
    gaps.add({"doc_ids": ["other", "x"], "gaps": []})
    _encrypt(client)
    left = [(r.get("type"), r["doc_ids"]) for r in analysis.list()]
    assert (("summarize", ["d1"]) not in left) and ("summarize", ["other"]) in left
    assert ("themes", ["d1", "other"]) in left      # names and membership, not words
    assert [r["doc_ids"] for r in gaps.list()] == [["other", "x"]]


def _lock_the_old_way(client):
    """What encrypting did before 2026-11-19: a v1 envelope, nothing removed."""
    from domain.encryption.vault import encrypt_paper
    envelope = encrypt_paper(" ".join(TEXTS), PASSWORD)
    store = LVS._store_instance
    for cid in ("d1_0", "d1_1"):
        meta = store.get(ids=[cid])["metadatas"][0]
        store.update([cid], [{**meta, "is_encrypted": "true", "encrypted_envelope": envelope}])


def test_using_the_password_on_an_old_paper_locks_it_at_rest(client):
    _lock_the_old_way(client)
    r = client.post("/api/encryption/decrypt", json={"doc_id": "d1", "password": PASSWORD})
    assert r.json()["full_text"] == " ".join(TEXTS)
    assert all("secret" not in t for t in _stored_texts(client))
    for f in client.papers.iterdir():
        assert b"SECRET-PDF-BYTES" not in f.read_bytes(), f.name


def test_an_upgraded_old_paper_unlocks_exactly(client):
    _lock_the_old_way(client)
    client.post("/api/encryption/decrypt", json={"doc_id": "d1", "password": PASSWORD})
    client.post("/api/encryption/remove", json={"doc_id": "d1", "password": PASSWORD})
    assert _stored_texts(client) == TEXTS
    assert (client.papers / "d1_paper.pdf").read_bytes() == SECRET_PDF
