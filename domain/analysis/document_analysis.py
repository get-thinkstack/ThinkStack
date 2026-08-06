"""single-call per-document analysis.

produces a paper's summary and key claims in ONE llm call (rather than
separate summary + claim-extraction passes). this is the per-paper unit the
gap-finder caches, so each paper is analyzed at most once regardless of how
many times it appears in a gap scan.
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
    """summarize a paper and extract its claims in a single model call.

    args:
        doc_id: the document identifier (used only for logging here).
        text: the paper text (or concatenated chunks) to analyze.

    returns:
        ``{"summary": str, "claims": [{"text": str, "type": str}, ...]}`` on
        success, or ``None`` if the model call fails or its output cannot be
        parsed -- so the caller can skip (and not cache) a failed paper.
    """
    prompt = DOCUMENT_ANALYSIS_PROMPT.format(text=text[:_TEXT_LIMIT])

    try:
        response = await ollama_client.generate_json(
            prompt,
            system=_SYSTEM,
            max_tokens=600,
            # summary + claims in one call is still analysis work, so it routes
            # like the two separate passes it replaced. Merging them is exactly
            # how the task got dropped in the gap pipeline; stating it here
            # keeps this call honest about what it is.
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
