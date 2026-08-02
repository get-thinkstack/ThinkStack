"""
claim extractor module.

extracts structured claims, findings, and methodological details from
research papers using the local slm. produces typed claim objects
for downstream gap analysis.
"""

import json
import logging

from domain.analysis.models import Claim
from domain.analysis.document_analysis import CLAIM_TYPES
from domain.analysis.parsing import as_dict, as_items, one_of
from infrastructure.ollama_client import ollama_client

logger = logging.getLogger(__name__)

CONFIDENCE_LEVELS = ("high", "medium", "low")

EXTRACTION_PROMPT = """analyze this research paper text and extract key claims and findings.
for each claim, identify:
1. claim_text: the claim or finding in one concise sentence (your own words)
2. claim_type: one of finding, methodology, limitation, future_work
3. confidence: high, medium, or low
4. supporting_text: a brief supporting phrase (max ~12 words)

paper text:
{text}

respond in json format with key "claims" containing a list of objects,
each with keys: claim_text, claim_type, confidence, supporting_text.
extract the 3 to 5 most important claims."""


async def extract_claims(doc_id: str, text: str) -> list[Claim]:
    """extract structured claims from a research paper using the slm.

    sends the paper text to the language model with a structured prompt
    that requests typed claims with confidence levels and supporting
    evidence.

    args:
        doc_id: the document identifier.
        text: the paper text to analyze.

    returns:
        list of Claim objects extracted from the paper.
    """
    truncated = text[:6000]
    prompt = EXTRACTION_PROMPT.format(text=truncated)

    system = (
        "you are an academic claim extraction tool. identify key claims, "
        "findings, and methodological details from research papers. "
        "respond only with valid json."
    )

    try:
        response = await ollama_client.generate_json(
            prompt, system=system, max_tokens=768, task_type="analysis"
        )
        data = json.loads(response)

        claims = []
        for entry in as_items(data, "claims"):
            item = as_dict(entry, "claim_text")
            text = item.get("claim_text") or item.get("text") or ""
            if not text:
                continue
            claims.append(Claim(
                doc_id=doc_id,
                claim_text=str(text),
                claim_type=one_of(item.get("claim_type"), CLAIM_TYPES, "finding"),
                confidence=one_of(item.get("confidence"), CONFIDENCE_LEVELS, "medium"),
                supporting_text=str(item.get("supporting_text") or ""),
            ))

        logger.info("extracted %d claims from document %s", len(claims), doc_id)
        return claims

    except Exception as e:
        logger.error("claim extraction failed for %s: %s", doc_id, e)
        return []
