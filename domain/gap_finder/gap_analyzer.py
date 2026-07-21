"""
gap analyzer module.

identifies research gaps by analyzing claims, findings, and limitations
across multiple papers. detects contradictions, under-explored areas,
methodological weaknesses, and missing validations.
"""

import json
import logging
import uuid

from domain.gap_finder.models import ResearchGap
from infrastructure.ollama_client import ollama_client

logger = logging.getLogger(__name__)

GAP_ANALYSIS_PROMPT = """you are analyzing a collection of research paper summaries and extracted claims
to identify gaps in the current research literature.

identify the following types of gaps:
1. contradictions: findings that conflict between papers
2. under_explored: subtopics or areas with insufficient research
3. methodological: recurring limitations in research methods
4. missing_validation: claims lacking experimental or empirical support
5. temporal: outdated findings that need re-examination

paper summaries and claims:
{content}

respond in json format with key "gaps" containing a list of objects,
each with keys: gap_type, description, evidence (list of supporting quotes
or references), severity (high/medium/low), related_doc_ids (list).
identify at least 3 gaps."""


async def analyze_gaps(
    summaries: list[dict],
    claims: list[dict],
    doc_ids: list[str],
) -> list[ResearchGap]:
    """analyze papers for research gaps using the slm.

    combines paper summaries and extracted claims into a single prompt
    for the language model to identify contradictions, methodological
    gaps, under-explored areas, and missing validations.

    args:
        summaries: list of summary dictionaries with doc_id and text.
        claims: list of claim dictionaries from all analyzed papers.
        doc_ids: list of document ids being analyzed.

    returns:
        list of ResearchGap objects describing identified gaps.
    """
    content = "summaries:\n"
    for s in summaries:
        content += f"- [{s.get('doc_id', 'unknown')}]: {s.get('text', '')[:500]}\n"

    content += "\nclaims:\n"
    for c in claims:
        content += (
            f"- [{c.get('doc_id', 'unknown')}] ({c.get('type', 'finding')}): "
            f"{c.get('text', '')[:200]}\n"
        )

    prompt = GAP_ANALYSIS_PROMPT.format(content=content)

    system = (
        "you are a research gap analysis tool for academic literature review. "
        "identify meaningful gaps that could lead to new research directions. "
        "respond only with valid json."
    )

    try:
        response = await ollama_client.generate_json(
            prompt,
            system=system,
            max_tokens=800,
            task_type="gap_analysis",
        )
        data = json.loads(response)
        gaps_data = data.get("gaps", [])

        gaps = []
        for item in gaps_data:
            gaps.append(ResearchGap(
                gap_id=uuid.uuid4().hex[:8],
                gap_type=item.get("gap_type", "under_explored"),
                description=item.get("description", ""),
                evidence=item.get("evidence", []),
                related_doc_ids=item.get("related_doc_ids", doc_ids),
                severity=item.get("severity", "medium"),
            ))

        logger.info("identified %d gaps across %d papers", len(gaps), len(doc_ids))
        return gaps

    except Exception as e:
        logger.error("gap analysis failed: %s", e)
        return []
