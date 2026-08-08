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

from domain.analysis.parsing import as_dict, as_items, as_str_list, one_of
from domain.gap_finder.models import ResearchGap, Suggestion
from infrastructure.ollama_client import ollama_client

logger = logging.getLogger(__name__)

# the gap categories the prompt offers and the ui knows how to render. a
# category the model invents reaches the canvas as a label and the severity
# chart as a bucket that matches nothing.
GAP_TYPES = (
    "contradictions", "under_explored", "methodological",
    "missing_validation", "temporal",
)
SEVERITIES = ("high", "medium", "low")
LEVELS = ("high", "medium", "low")

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
    for entry in gaps_data:
        item = as_dict(entry, "description")
        description = item.get("description") or ""
        if not description:
            continue
        # a hallucinated doc_id would draw gap evidence to a paper that is not
        # on the canvas, so membership is intersected with the papers actually
        # under analysis rather than trusted.
        related = [d for d in as_str_list(item.get("related_doc_ids")) if d in doc_ids]
        gaps.append(ResearchGap(
            gap_id=uuid.uuid4().hex[:8],
            gap_type=one_of(item.get("gap_type"), GAP_TYPES, "under_explored"),
            description=str(description),
            evidence=as_str_list(item.get("evidence")),
            related_doc_ids=related or list(doc_ids),
            severity=one_of(item.get("severity"), SEVERITIES, "medium"),
        ))
    return gaps


def _parse_suggestions(sugg_data: list, gaps: list[ResearchGap]) -> list[Suggestion]:
    suggestions = []
    for entry in sugg_data:
        item = as_dict(entry, "title")
        # remap 1-based gap indexes to the ids we assigned; drop anything
        # out of range so a hallucinated index can't crash the response.
        related = []
        for idx in item.get("related_gap_indexes", []) or []:
            # bool is an int subclass, and True would silently mean gap 1.
            if isinstance(idx, int) and not isinstance(idx, bool) and 1 <= idx <= len(gaps):
                related.append(gaps[idx - 1].gap_id)
        title = item.get("title") or ""
        if not title:
            continue
        suggestions.append(Suggestion(
            suggestion_id=uuid.uuid4().hex[:8],
            title=str(title),
            description=str(item.get("description") or ""),
            rationale=str(item.get("rationale") or ""),
            related_gaps=related,
            feasibility=one_of(item.get("feasibility"), LEVELS, "medium"),
            potential_impact=one_of(item.get("potential_impact"), LEVELS, "medium"),
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
            # naming the task is what makes the user's choice count: the router
            # looks up whatever model is assigned to THIS task in Bench. Omit it
            # and the argument defaults to "general", so the lookup happens
            # against the wrong task, finds nothing, and quietly falls back to
            # the base model -- while Bench still shows the model the user
            # picked for gap finding.
            task_type="gap_analysis",
        )
        data = json.loads(response)
    except Exception as e:  # noqa: BLE001 - any failure -> no gaps/suggestions
        logger.error("gap analysis failed: %s", e)
        return [], []

    gaps = _parse_gaps(as_items(data, "gaps"), doc_ids)
    suggestions = _parse_suggestions(as_items(data, "suggestions"), gaps)

    logger.info(
        "identified %d gaps and %d suggestions across %d papers",
        len(gaps), len(suggestions), len(doc_ids),
    )
    return gaps, suggestions
