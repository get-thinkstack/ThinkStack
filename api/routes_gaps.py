"""
gap analysis api routes.

provides the endpoint for running comprehensive gap analysis across
ingested documents, combining claim extraction with gap detection
and research direction suggestions.
"""

import json
import logging
from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from domain.knowledge_base.repository import get_chunks_by_doc_id
from domain.gap_finder.gap_analyzer import analyze_gaps
from domain.gap_finder.suggestion_engine import generate_suggestions
from domain.fine_tuning.data_collector import save_gap_analysis_pair
from infrastructure.ollama_client import ollama_client

logger = logging.getLogger(__name__)
router = APIRouter()


DOCUMENT_ANALYSIS_PROMPT = """analyze the following research paper text and return a json object with:
1. summary: a concise 3-5 sentence summary
2. claims: a list of 3-5 key claims or findings

for each claim object include only:
- claim_text (one sentence, in your own words -- do not quote the paper)
- claim_type (finding, methodology, limitation, future_work)

paper text:
{text}

respond only in valid json with keys summary and claims."""


class GapAnalysisRequest(BaseModel):
    """request body for gap analysis."""
    doc_ids: list[str] = Field(..., min_length=2)
    password: str | None = None


async def _analyze_document(doc_id: str, text: str) -> tuple[dict, list[dict]]:
    """summarize a paper and extract claims in a single model call.

    this keeps the gap-finder path shorter by avoiding separate summary
    and claim extraction calls for each paper.
    """
    prompt = DOCUMENT_ANALYSIS_PROMPT.format(text=text[:2500])
    system = (
        "you are an academic analysis tool. produce concise, grounded output "
        "and respond only with valid json."
    )

    try:
        response = await ollama_client.generate_json(
            prompt,
            system=system,
            max_tokens=600,
            max_tokens=800,
            task_type="gap_analysis",
        )
        data = json.loads(response)
        summary_text = data.get("summary", "")
        claims = data.get("claims", [])

        summaries = [{"doc_id": doc_id, "text": summary_text}]
        claim_rows = []
        for claim in claims:
            claim_rows.append({
                "doc_id": doc_id,
                "text": claim.get("claim_text", ""),
                "type": claim.get("claim_type", "finding"),
            })

        return summaries[0], claim_rows
    except Exception as e:
        logger.error("document analysis failed for %s: %s", doc_id, e)
        return {
            "doc_id": doc_id,
            "text": f"analysis failed: {str(e)}",
        }, []


@router.post("/analyze")
async def analyze(request: GapAnalysisRequest):
    """run comprehensive gap analysis across multiple documents.

    orchestrates the full gap analysis pipeline:
    1. generates summaries for each document
    2. extracts claims from each document
    3. analyzes gaps across all claims and summaries
    4. generates research direction suggestions

    requires at least 2 documents for meaningful gap analysis.

    args:
        request: list of document ids to analyze for gaps.

    returns:
        complete gap analysis with identified gaps and suggestions.
    """
    if len(request.doc_ids) < 2:
        raise HTTPException(
            status_code=400,
            detail="at least 2 documents are required for gap analysis",
        )

    summaries = []
    all_claims = []

    for doc_id in request.doc_ids:
        chunks = get_chunks_by_doc_id(doc_id)
        if not chunks["ids"]:
            logger.warning("no chunks found for document %s, skipping", doc_id)
            continue

        first_meta = chunks["metadatas"][0] if chunks["metadatas"] else {}
        is_enc = first_meta.get("is_encrypted")
        if is_enc == "true" or is_enc is True:
            if not request.password:
                raise HTTPException(status_code=403, detail=f"document is encrypted. password required.")
            from domain.encryption.vault import decrypt_paper, WrongPasswordError
            from domain.encryption.envelope import EnvelopeFormatError
            envelope = first_meta.get("encrypted_envelope")
            try:
                text = decrypt_paper(envelope, request.password)
            except WrongPasswordError:
                raise HTTPException(status_code=403, detail="incorrect password")
            except EnvelopeFormatError:
                raise HTTPException(status_code=422, detail="corrupted envelope")
        else:
            text = " ".join(chunks["documents"])

        summary_row, doc_claims = await _analyze_document(doc_id, text)
        summaries.append(summary_row)
        all_claims.extend(doc_claims)

    if len(summaries) < 2:
        raise HTTPException(
            status_code=422,
            detail="could not process enough documents for gap analysis",
        )

    gaps = await analyze_gaps(summaries, all_claims, request.doc_ids)
    suggestions = await generate_suggestions(gaps)

    # save training pair for future fine-tuning (best-effort, privacy-safe)
    try:
        combined_text = "\n".join(
            f"[{s['doc_id']}] {s['text'][:200]}" for s in summaries
        )
        result_json = json.dumps({
            "gaps": [asdict(g) for g in gaps],
            "suggestions": [asdict(s) for s in suggestions],
        }, ensure_ascii=False)
        save_gap_analysis_pair(
            paper_content=combined_text,
            system="gap analysis across research papers",
            analysis_result=result_json,
        )
    except Exception:  # noqa: BLE001 - data collection is non-critical
        pass

    return {
        "gaps": [asdict(g) for g in gaps],
        "suggestions": [asdict(s) for s in suggestions],
        "papers_analyzed": len(summaries),
        "total_claims": len(all_claims),
        "total_gaps": len(gaps),
        "total_suggestions": len(suggestions),
    }
