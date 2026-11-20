"""Gap finding route, and its run history.

A scan needs each paper's summary and claims. Those come from the analysis
cache (filled at ingest, or on first scan), so a scan over analysed papers
costs one model call: the combined gaps + suggestions pass in
domain/gap_finder/gap_pipeline.py.
"""

import logging
from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from domain.knowledge_base.repository import get_chunks_by_doc_id
from domain.analysis.document_analysis import analyze_document
from domain.gap_finder.gap_pipeline import analyze_gaps_and_suggestions
from infrastructure.analysis_cache import doc_analysis_cache
from infrastructure.gap_history import gap_history

logger = logging.getLogger(__name__)
router = APIRouter()


class GapAnalysisRequest(BaseModel):
    """request body for gap analysis."""
    doc_ids: list[str] = Field(..., min_length=2)
    password: str | None = None


def _decrypt_or_join(doc_id: str, chunks: dict, password: str | None) -> str:
    """reconstruct a document's text, decrypting it if stored encrypted."""
    first_meta = chunks["metadatas"][0] if chunks["metadatas"] else {}
    is_enc = first_meta.get("is_encrypted")
    if is_enc == "true" or is_enc is True:
        if not password:
            raise HTTPException(
                status_code=403,
                detail="document is encrypted. password required.",
            )
        from domain.encryption.vault import open_text, WrongPasswordError
        from domain.encryption.envelope import EnvelopeFormatError
        envelope = first_meta.get("encrypted_envelope")
        try:
            return open_text(envelope, password)[0]
        except WrongPasswordError:
            raise HTTPException(status_code=403, detail="incorrect password")
        except EnvelopeFormatError:
            raise HTTPException(status_code=422, detail="corrupted envelope")
    return " ".join(chunks["documents"])


async def _get_analysis(doc_id: str, password: str | None) -> dict | None:
    """A paper's summary and claims, from the cache or computed once and cached.

    None when the paper has no chunks or analysis fails; the caller skips it.
    """
    cached = doc_analysis_cache.get(doc_id)
    if cached is not None:
        return cached

    chunks = get_chunks_by_doc_id(doc_id)
    if not chunks["ids"]:
        logger.warning("no chunks found for document %s, skipping", doc_id)
        return None

    text = _decrypt_or_join(doc_id, chunks, password)
    analysis = await analyze_document(doc_id, text)
    if analysis is None:
        return None

    doc_analysis_cache.put(doc_id, analysis["summary"], analysis["claims"])
    return analysis


@router.post("/analyze")
async def analyze(request: GapAnalysisRequest):
    """Find gaps and suggest directions across the given papers (at least 2)."""
    if len(request.doc_ids) < 2:
        raise HTTPException(
            status_code=400,
            detail="at least 2 documents are required for gap analysis",
        )

    summaries = []
    all_claims = []

    for doc_id in request.doc_ids:
        analysis = await _get_analysis(doc_id, request.password)
        if analysis is None:
            continue
        summaries.append({"doc_id": doc_id, "text": analysis["summary"]})
        for claim in analysis.get("claims", []):
            all_claims.append({
                "doc_id": doc_id,
                "text": claim.get("text", ""),
                "type": claim.get("type", "finding"),
            })

    if len(summaries) < 2:
        raise HTTPException(
            status_code=422,
            detail="could not process enough documents for gap analysis",
        )

    gaps, suggestions = await analyze_gaps_and_suggestions(
        summaries, all_claims, request.doc_ids
    )

    result = {
        "gaps": [asdict(g) for g in gaps],
        "suggestions": [asdict(s) for s in suggestions],
        "papers_analyzed": len(summaries),
        "total_claims": len(all_claims),
        "total_gaps": len(gaps),
        "total_suggestions": len(suggestions),
    }

    # The saved record adds run_id and created_at; returned so the UI can
    # select this run.
    saved = gap_history.add({"doc_ids": request.doc_ids, **result})
    result["run_id"] = saved["run_id"]
    result["created_at"] = saved["created_at"]
    return result


@router.get("/history")
async def list_history():
    """list past gap-analysis runs, newest first."""
    return {"runs": gap_history.list()}


@router.delete("/history/{run_id}")
async def delete_history_run(run_id: str):
    """delete a single past gap-analysis run by id."""
    if not gap_history.delete(run_id):
        raise HTTPException(status_code=404, detail="run not found")
    return {"deleted": True, "run_id": run_id}
