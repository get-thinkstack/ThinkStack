"""wiring tests: ingest-time analysis precompute + cache cleanup on delete."""

from pathlib import Path

import pytest

from api import routes_documents
from api.routes_documents import upload_document, delete_document
from domain.ingestion.models import DocumentMetadata
from infrastructure.analysis_cache import DocAnalysisCache


class FakeUpload:
    """minimal stand-in for starlette's UploadFile."""

    def __init__(self, filename, content=b"%PDF-1.4 fake"):
        self.filename = filename
        self._content = content

    async def read(self):
        return self._content


def _stub_ingestion(monkeypatch, doc_id="docX"):
    monkeypatch.setattr(routes_documents, "save_uploaded_pdf",
                        lambda name, content: (doc_id, Path("fake.pdf")))
    monkeypatch.setattr(routes_documents, "extract_text",
                        lambda path: ([{"page_number": 1, "text": "body"}], "full paper text"))
    monkeypatch.setattr(routes_documents, "get_page_count", lambda path: 1)

    async def fake_metadata(text):
        return DocumentMetadata()
    monkeypatch.setattr(routes_documents, "extract_metadata", fake_metadata)
    monkeypatch.setattr(routes_documents, "chunk_pages", lambda pages, did: ["chunk"])
    monkeypatch.setattr(routes_documents, "store_chunks", lambda chunks, meta: len(chunks))


async def test_upload_precomputes_and_caches_analysis(monkeypatch, tmp_path):
    _stub_ingestion(monkeypatch)
    cache = DocAnalysisCache(tmp_path / "doc_analysis.json")
    monkeypatch.setattr(routes_documents, "doc_analysis_cache", cache)

    async def fake_analyze_document(doc_id, text):
        return {"summary": f"summary of {doc_id}", "claims": [{"text": "c", "type": "finding"}]}
    monkeypatch.setattr(routes_documents, "analyze_document", fake_analyze_document)

    result = await upload_document(FakeUpload("paper.pdf"))

    assert result["status"] == "ingested"
    assert cache.get("docX") == {
        "summary": "summary of docX",
        "claims": [{"text": "c", "type": "finding"}],
    }


async def test_upload_still_succeeds_when_analysis_fails(monkeypatch, tmp_path):
    _stub_ingestion(monkeypatch)
    cache = DocAnalysisCache(tmp_path / "doc_analysis.json")
    monkeypatch.setattr(routes_documents, "doc_analysis_cache", cache)

    async def boom(doc_id, text):
        raise RuntimeError("model unavailable")
    monkeypatch.setattr(routes_documents, "analyze_document", boom)

    result = await upload_document(FakeUpload("paper.pdf"))

    # upload succeeds; nothing cached (falls back to lazy compute at scan time)
    assert result["status"] == "ingested"
    assert cache.get("docX") is None


async def test_delete_removes_cached_analysis(monkeypatch, tmp_path):
    monkeypatch.setattr(routes_documents, "delete_pdf", lambda doc_id: True)
    monkeypatch.setattr(routes_documents, "delete_chunks_by_doc_id", lambda doc_id: True)
    cache = DocAnalysisCache(tmp_path / "doc_analysis.json")
    cache.put("docX", summary="s", claims=[])
    monkeypatch.setattr(routes_documents, "doc_analysis_cache", cache)

    await delete_document("docX")

    assert cache.get("docX") is None
