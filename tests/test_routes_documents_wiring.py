"""wiring tests: ingest-time analysis precompute + cache cleanup on delete."""

from pathlib import Path


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


async def test_upload_queues_analysis_instead_of_awaiting_it(monkeypatch):
    """the upload response must not wait on the model.

    this used to await analyze_document inside the handler, which put a ~50 s
    call in the request: the browser sat on a pending POST for the whole of it
    and three papers meant three minutes of apparent hang. the analysis still
    happens at ingest time, just after the response.
    """
    _stub_ingestion(monkeypatch)
    scheduled = []
    monkeypatch.setattr(
        routes_documents, "schedule_for_new_document",
        lambda doc_id, text, title="": scheduled.append((doc_id, text, title)),
    )

    result = await upload_document(FakeUpload("paper.pdf"))

    assert result["status"] == "ingested"
    assert scheduled == [("docX", "full paper text", "")]


async def test_upload_still_succeeds_when_scheduling_blows_up(monkeypatch):
    """a broken queue must not cost the user their document.

    the pdf is already saved and its chunks stored by this point; failing the
    request here would report an ingest failure for a paper that is, in fact,
    ingested.
    """
    _stub_ingestion(monkeypatch)

    def boom(doc_id, text, title=""):
        raise RuntimeError("queue unavailable")
    monkeypatch.setattr(routes_documents, "schedule_for_new_document", boom)

    result = await upload_document(FakeUpload("paper.pdf"))

    assert result["status"] == "ingested"


async def test_pdf_route_404s_for_an_unknown_document(monkeypatch):
    import pytest
    from fastapi import HTTPException
    from api.routes_documents import get_document_pdf

    monkeypatch.setattr(routes_documents, "get_pdf_path", lambda doc_id: None)

    with pytest.raises(HTTPException) as e:
        await get_document_pdf("nope")
    assert e.value.status_code == 404


async def test_pdf_route_refuses_an_encrypted_document(monkeypatch, tmp_path):
    """the stored pdf is NOT encrypted at rest.

    encryption covers the chunk text in the vector store; the original file
    sits in papers_dir as plaintext. serving it for an encrypted document
    would hand back everything the encryption exists to withhold.
    """
    import pytest
    from fastapi import HTTPException
    from api.routes_documents import get_document_pdf

    pdf = tmp_path / "docX_paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(routes_documents, "get_pdf_path", lambda doc_id: pdf)
    monkeypatch.setattr(routes_documents, "get_chunks_by_doc_id",
                        lambda doc_id: {"ids": ["c1"], "documents": ["x"],
                                        "metadatas": [{"is_encrypted": "true"}]})

    with pytest.raises(HTTPException) as e:
        await get_document_pdf("docX")
    assert e.value.status_code == 403


async def test_pdf_route_serves_a_plain_document_inline(monkeypatch, tmp_path):
    """inline, not attachment -- an attachment disposition leaves the reader's
    iframe blank and downloads the file instead (same trap routes_papers hit)."""
    from api.routes_documents import get_document_pdf

    pdf = tmp_path / "docX_paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(routes_documents, "get_pdf_path", lambda doc_id: pdf)
    monkeypatch.setattr(routes_documents, "get_chunks_by_doc_id",
                        lambda doc_id: {"ids": ["c1"], "documents": ["x"],
                                        "metadatas": [{"is_encrypted": "false"}]})

    resp = await get_document_pdf("docX")

    assert resp.media_type == "application/pdf"
    assert "inline" in resp.headers["content-disposition"]


async def test_delete_removes_cached_analysis(monkeypatch, tmp_path):
    monkeypatch.setattr(routes_documents, "delete_pdf", lambda doc_id: True)
    monkeypatch.setattr(routes_documents, "delete_chunks_by_doc_id", lambda doc_id: True)
    cache = DocAnalysisCache(tmp_path / "doc_analysis.json")
    cache.put("docX", summary="s", claims=[])
    monkeypatch.setattr(routes_documents, "doc_analysis_cache", cache)

    await delete_document("docX")

    assert cache.get("docX") is None
