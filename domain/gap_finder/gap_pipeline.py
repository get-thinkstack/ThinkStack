"""merged gap analysis + research-direction suggestions.

identifies research gaps AND proposes directions to address them in a single
llm call, instead of two serialized generations. the model links each
suggestion to the gaps it addresses by 1-based index; those indexes are
remapped here to the gap ids we assign, so the api response keeps the same
``gaps`` / ``suggestions`` shape (with ``related_gaps`` populated) as before.
"""

import json
import logging
import uuid

from domain.gap_finder.models import ResearchGap, Suggestion
from infrastructure.ollama_client import ollama_client

logger = logging.getLogger(__name__)

# cap on the combined summaries+claims text fed to the model. the local
# context window is 4096 tokens and this single call must leave room for the
# gaps+suggestions output, so the grounding content is bounded here (~1.5k
# tokens) rather than growing without limit as more papers are selected.
_CONTENT_CHAR_BUDGET = 6000

COMBINED_PROMPT = """you are reviewing a collection of research paper summaries and claims to (a)
identify gaps in the current literature and (b) propose concrete research
directions that would address them.

gap types: contradictions, under_explored, methodological, missing_validation,
temporal.

paper summaries and claims:
{content}

respond in json with two keys:

"gaps": a list of 3-5 objects, each with keys: gap_type, description (concise),
evidence (list of up to 2 short supporting phrases, not long quotes),
severity (high/medium/low), related_doc_ids (list).

"suggestions": a list of 2-4 objects, each with keys: title, description
(concise), rationale (concise), feasibility (high/medium/low), potential_impact
(high/medium/low), related_gap_indexes (list of 1-based positions into the gaps
list above indicating which gaps the suggestion addresses)."""

_SYSTEM = (
    "you are a research gap analysis and advisory tool for academic "
    "literature review. identify meaningful gaps and propose actionable, "
    "specific research directions. respond only with valid json."
)


def _build_content(summaries: list[dict], claims: list[dict]) -> str:
    """assemble the bounded summaries+claims grounding block."""
    content = "summaries:\n"
    for s in summaries:
        content += f"- [{s.get('doc_id', 'unknown')}]: {s.get('text', '')[:500]}\n"

    content += "\nclaims:\n"
    for c in claims:
        content += (
            f"- [{c.get('doc_id', 'unknown')}] ({c.get('type', 'finding')}): "
            f"{c.get('text', '')[:200]}\n"
        )

    if len(content) > _CONTENT_CHAR_BUDGET:
        content = content[:_CONTENT_CHAR_BUDGET]
    return content


def _parse_gaps(gaps_data: list, doc_ids: list[str]) -> list[ResearchGap]:
    gaps = []
    for item in gaps_data:
        gaps.append(ResearchGap(
            gap_id=uuid.uuid4().hex[:8],
            gap_type=item.get("gap_type", "under_explored"),
            description=item.get("description", ""),
            evidence=item.get("evidence", []) or [],
            related_doc_ids=item.get("related_doc_ids", doc_ids),
            severity=item.get("severity", "medium"),
        ))
    return gaps


def _parse_suggestions(sugg_data: list, gaps: list[ResearchGap]) -> list[Suggestion]:
    suggestions = []
    for item in sugg_data:
        # remap 1-based gap indexes to the ids we assigned; drop anything
        # out of range so a hallucinated index can't crash the response.
        related = []
        for idx in item.get("related_gap_indexes", []) or []:
            if isinstance(idx, int) and 1 <= idx <= len(gaps):
                related.append(gaps[idx - 1].gap_id)
        suggestions.append(Suggestion(
            suggestion_id=uuid.uuid4().hex[:8],
            title=item.get("title", ""),
            description=item.get("description", ""),
            rationale=item.get("rationale", ""),
            related_gaps=related,
            feasibility=item.get("feasibility", "medium"),
            potential_impact=item.get("potential_impact", "medium"),
        ))
    return suggestions


async def analyze_gaps_and_suggestions(
    summaries: list[dict],
    claims: list[dict],
    doc_ids: list[str],
) -> tuple[list[ResearchGap], list[Suggestion]]:
    """identify gaps and propose research directions in one model call.

    args:
        summaries: per-paper summary dicts ``{doc_id, text}``.
        claims: claim dicts ``{doc_id, text, type}`` from all papers.
        doc_ids: the documents under analysis (used as the default
            ``related_doc_ids`` when the model omits them).

    returns:
        ``(gaps, suggestions)`` -- both empty if the call fails or its output
        cannot be parsed.
    """
    prompt = COMBINED_PROMPT.format(content=_build_content(summaries, claims))

    try:
        response = await ollama_client.generate_json(
            prompt,
            system=_SYSTEM,
            max_tokens=1100,
        )
        data = json.loads(response)
    except Exception as e:  # noqa: BLE001 - any failure -> no gaps/suggestions
        logger.error("gap analysis failed: %s", e)
        return [], []

    gaps = _parse_gaps(data.get("gaps", []) or [], doc_ids)
    suggestions = _parse_suggestions(data.get("suggestions", []) or [], gaps)

    logger.info(
        "identified %d gaps and %d suggestions across %d papers",
        len(gaps), len(suggestions), len(doc_ids),
    )
    return gaps, suggestions
