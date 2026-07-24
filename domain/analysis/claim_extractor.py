"""
claim extractor module.

extracts structured claims, findings, and methodological details from
research papers using the local slm. produces typed claim objects
for downstream gap analysis.
"""

import json
import logging
import uuid

from domain.analysis.models import Claim
from infrastructure.ollama_client import ollama_client

logger = logging.getLogger(__name__)

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
        claims_data = data.get("claims", [])

        claims = []
        for item in claims_data:
            claims.append(Claim(
                doc_id=doc_id,
                claim_text=item.get("claim_text", ""),
                claim_type=item.get("claim_type", "finding"),
                confidence=item.get("confidence", "medium"),
                supporting_text=item.get("supporting_text", ""),
            ))

        logger.info("extracted %d claims from document %s", len(claims), doc_id)
        return claims

    except Exception as e:
        logger.error("claim extraction failed for %s: %s", doc_id, e)
        return []
