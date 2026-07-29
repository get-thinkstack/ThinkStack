"""
analysis api routes.

provides endpoints for paper summarization, claim extraction,
and thematic clustering powered by the local slm.
"""

import logging
from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from domain.knowledge_base.repository import get_chunks_by_doc_id
from domain.analysis.summarizer import summarize_single, summarize_multiple
from domain.analysis.claim_extractor import extract_claims
from domain.analysis.theme_clusterer import cluster_by_themes
from infrastructure.analysis_history import analysis_history

logger = logging.getLogger(__name__)
router = APIRouter()


def _record(analysis_type: str, doc_ids: list[str], result: dict) -> dict:
    """save an analysis run to history and stamp the response with its id.

    the stored record keeps the analysis ``type`` so the ui can re-render the
    matching view when a past run is reopened.
    """
    saved = analysis_history.add({
        "type": analysis_type,
        "doc_ids": doc_ids,
        "result": result,
    })
    return {**result, "run_id": saved["run_id"], "created_at": saved["created_at"]}


class AnalysisRequest(BaseModel):
    """request body for analysis endpoints."""
    doc_ids: list[str] = Field(..., min_length=1)
    password: str | None = None


def _get_doc_text(doc_id: str, password: str | None = None) -> str:
    """retrieve the full concatenated text for a document.

    args:
        doc_id: the document identifier.
        password: password to decrypt the full text if encrypted.

    returns:
        concatenated text of all document chunks or decrypted full text.

    raises:
        HTTPException: if no chunks are found for the document or password wrong.
    """
    chunks = get_chunks_by_doc_id(doc_id)
    if not chunks["ids"]:
        raise HTTPException(
            status_code=404,
            detail=f"no chunks found for document {doc_id}",
        )

    first_meta = chunks["metadatas"][0] if chunks["metadatas"] else {}
    is_enc = first_meta.get("is_encrypted")
    if is_enc == "true" or is_enc is True:
        if not password:
            raise HTTPException(status_code=403, detail="document is encrypted. password required.")
        from domain.encryption.vault import decrypt_paper, WrongPasswordError
        from domain.encryption.envelope import EnvelopeFormatError
        envelope = first_meta.get("encrypted_envelope")
        try:
            return decrypt_paper(envelope, password)
        except WrongPasswordError:
            raise HTTPException(status_code=403, detail="incorrect password")
        except EnvelopeFormatError:
            raise HTTPException(status_code=422, detail="corrupted envelope")

    return " ".join(chunks["documents"])


@router.post("/summarize")
async def summarize(request: AnalysisRequest):
    """generate summaries for one or more documents.

    produces single-paper summaries for individual documents or a
    comparative summary when multiple documents are provided.

    args:
        request: list of document ids to summarize.

    returns:
        generated summaries with key points.
    """
    if len(request.doc_ids) == 1:
        text = _get_doc_text(request.doc_ids[0], request.password)
        summary = await summarize_single(request.doc_ids[0], text)
    else:
        texts = {}
        for doc_id in request.doc_ids:
            texts[doc_id] = _get_doc_text(doc_id, request.password)
        summary = await summarize_multiple(request.doc_ids, texts)

    return _record("summarize", request.doc_ids, asdict(summary))


@router.post("/claims")
async def claims(request: AnalysisRequest):
    """extract key claims and findings from documents.

    identifies structured claims including findings, methodology,
    limitations, and future work directions.

    args:
        request: list of document ids to analyze.

    returns:
        list of extracted claims with types and confidence levels.
    """
    all_claims = []
    for doc_id in request.doc_ids:
        text = _get_doc_text(doc_id, request.password)
        doc_claims = await extract_claims(doc_id, text)
        all_claims.extend([asdict(c) for c in doc_claims])

    return _record("claims", request.doc_ids, {
        "claims": all_claims,
        "total": len(all_claims),
        "doc_ids": request.doc_ids,
    })


@router.post("/themes")
async def themes(request: AnalysisRequest):
    """cluster documents into thematic groups.

    identifies common themes across the provided documents and
    assigns each paper to one or more clusters.

    args:
        request: list of document ids to cluster.

    returns:
        list of thematic clusters with labels and descriptions.
    """
    if len(request.doc_ids) < 2:
        raise HTTPException(
            status_code=400,
            detail="at least 2 documents are required for theme clustering",
        )

    texts = {}
    for doc_id in request.doc_ids:
        texts[doc_id] = _get_doc_text(doc_id, request.password)

    result_themes = await cluster_by_themes(texts)
    return _record("themes", request.doc_ids, {
        "themes": [asdict(t) for t in result_themes],
        "total": len(result_themes),
        "doc_ids": request.doc_ids,
    })


@router.get("/history")
async def list_analysis_history():
    """list past analysis runs (summaries/claims/themes), newest first."""
    return {"runs": analysis_history.list()}


@router.delete("/history/{run_id}")
async def delete_analysis_run(run_id: str):
    """delete a single past analysis run by id."""
    if not analysis_history.delete(run_id):
        raise HTTPException(status_code=404, detail="run not found")
    return {"deleted": True, "run_id": run_id}
