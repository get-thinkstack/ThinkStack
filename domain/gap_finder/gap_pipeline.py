"""Gap finding: gaps and research directions in ONE model call.

Input is each paper's cached summary and claims (bounded by a character cap),
never the full texts. The model links each suggestion to gaps by 1-based
index; those are remapped to the ids assigned here (`related_gaps`).

Model output is not trusted: unknown categories are coerced, invented doc_ids
dropped, out-of-range indexes ignored, and repeated findings merged.
"""

import json
import logging
import re
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


def _finding_key(description: str) -> str:
    """What makes two entries the same finding.

    Case, runs of whitespace and trailing punctuation only, deliberately. A
    looser rule -- stemming, or a similarity threshold -- would eventually
    merge two gaps that differ by one word, and the difference between
    "evaluated on non-stationary streams" and "evaluated on stationary
    streams" is the whole finding. Losing a real gap is worse than showing a
    near-duplicate.
    """
    return re.sub(r"\s+", " ", description).strip().strip(".!?,;:").casefold()


def _parse_gaps(gaps_data: list, doc_ids: list[str]) -> list[ResearchGap]:
    """Parse the model's gaps, treating the reply as findings rather than rows.

    Small models repeat themselves, and each entry gets a fresh id, so a
    repeat would be a second gap on the map (defect D-17). A repeat is merged,
    not dropped: it often carries evidence the first copy lacked.
    """
    gaps: list[ResearchGap] = []
    seen: dict[str, ResearchGap] = {}

    for entry in gaps_data:
        item = as_dict(entry, "description")
        description = item.get("description") or ""
        if not description:
            continue
        # a hallucinated doc_id would draw gap evidence to a paper that is not
        # on the canvas, so membership is intersected with the papers actually
        # under analysis rather than trusted.
        related = [d for d in as_str_list(item.get("related_doc_ids")) if d in doc_ids]
        severity = one_of(item.get("severity"), SEVERITIES, "medium")
        evidence = as_str_list(item.get("evidence"))

        key = _finding_key(str(description))
        existing = seen.get(key)
        if existing is not None:
            for e in evidence:
                if e not in existing.evidence:
                    existing.evidence.append(e)
            for d in related:
                if d not in existing.related_doc_ids:
                    existing.related_doc_ids.append(d)
            # The worse reading of one finding is the one worth reporting.
            # SEVERITIES runs worst-first ("high", "medium", "low"), so the
            # more severe value is the LOWER index.
            if SEVERITIES.index(severity) < SEVERITIES.index(existing.severity):
                existing.severity = severity
            continue

        gap = ResearchGap(
            gap_id=uuid.uuid4().hex[:8],
            gap_type=one_of(item.get("gap_type"), GAP_TYPES, "under_explored"),
            description=str(description),
            evidence=evidence,
            related_doc_ids=related or list(doc_ids),
            severity=severity,
        )
        seen[key] = gap
        gaps.append(gap)

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
    """`(gaps, suggestions)`, both empty if the call or parsing fails.

    `doc_ids` is the default evidence when the model names none.
    """
    prompt = COMBINED_PROMPT.format(content=_build_content(summaries, claims))

    try:
        response = await ollama_client.generate_json(
            prompt,
            system=_SYSTEM,
            max_tokens=1100,
            # Must name the task: without it the call routes as "general" and
            # ignores the model the user assigned to gap finding in Bench.
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
