"""Summary and claims for one paper in ONE model call.

This is the per-paper unit written to the analysis cache at ingest
(precompute.py) and read by the gap finder and the canvas, so a paper is
analysed at most once however many scans include it.
"""

import json
import logging
from typing import Optional

from domain.analysis.parsing import as_dict, as_items, one_of
from infrastructure.ollama_client import ollama_client

logger = logging.getLogger(__name__)

# the claim categories the ui and the gap-finder actually handle.
CLAIM_TYPES = ("finding", "methodology", "limitation", "future_work")

# text budget per paper. the local model's context is small, and the summary
# only needs the paper's framing (abstract/intro/conclusion land early), so a
# generous head slice is enough while keeping prompt-eval fast.
_TEXT_LIMIT = 2500

DOCUMENT_ANALYSIS_PROMPT = """analyze the following research paper text and return a json object with:
1. summary: a concise 3-5 sentence summary
2. claims: a list of 3-5 key claims or findings

for each claim object include only:
- claim_text (one sentence, in your own words -- do not quote the paper)
- claim_type (finding, methodology, limitation, future_work)

paper text:
{text}

respond only in valid json with keys summary and claims."""

_SYSTEM = (
    "you are an academic analysis tool. produce concise, grounded output "
    "and respond only with valid json."
)


async def analyze_document(doc_id: str, text: str) -> Optional[dict]:
    """`{"summary", "claims": [{"text", "type"}]}`, or None on failure so the
    caller skips (and does not cache) the paper."""
    prompt = DOCUMENT_ANALYSIS_PROMPT.format(text=text[:_TEXT_LIMIT])

    try:
        response = await ollama_client.generate_json(
            prompt,
            system=_SYSTEM,
            max_tokens=600,
            # Analysis work, so task "analysis". Every generation must name its
            # task, or it silently routes as "general".
            task_type="analysis",
        )
        data = json.loads(response)
    except Exception as e:  # noqa: BLE001 - any failure -> treat as "no analysis"
        logger.error("document analysis failed for %s: %s", doc_id, e)
        return None

    claims = []
    for entry in as_items(data, "claims"):
        claim = as_dict(entry, "claim_text")
        text = claim.get("claim_text") or claim.get("text") or ""
        if not text:
            continue
        claims.append({
            "text": str(text),
            "type": one_of(claim.get("claim_type"), CLAIM_TYPES, "finding"),
        })

    summary = data.get("summary", "") if isinstance(data, dict) else ""
    return {"summary": str(summary or ""), "claims": claims}
