"""
suggestion engine module.

generates actionable research direction suggestions based on
identified gaps in the literature. ranks suggestions by feasibility
and potential impact.
"""

import json
import logging
import uuid

from domain.gap_finder.models import ResearchGap, Suggestion
from infrastructure.ollama_client import ollama_client

logger = logging.getLogger(__name__)

SUGGESTION_PROMPT = """based on the following research gaps identified in a literature review,
suggest concrete research directions that would address these gaps.

for each suggestion, provide:
1. a clear title for the proposed research
2. a description of what the research would involve
3. rationale for why this direction is promising
4. feasibility assessment (high/medium/low)
5. potential impact assessment (high/medium/low)
6. which gap ids it addresses

identified gaps:
{gaps}

respond in json format with key "suggestions" containing a list of objects,
each with keys: title, description (concise), rationale (concise), feasibility,
potential_impact, related_gap_ids (list). provide 2 to 4 suggestions."""


async def generate_suggestions(gaps: list[ResearchGap]) -> list[Suggestion]:
    """generate research direction suggestions from identified gaps.

    sends the gap descriptions to the slm which proposes concrete
    research directions with feasibility and impact assessments.

    args:
        gaps: list of identified research gaps to address.

    returns:
        list of Suggestion objects with proposed research directions.
    """
    if not gaps:
        return []

    gaps_text = ""
    for gap in gaps:
        gaps_text += (
            f"\n- [gap_id: {gap.gap_id}] ({gap.gap_type}, {gap.severity}): "
            f"{gap.description}"
        )
        if gap.evidence:
            gaps_text += f"\n  evidence: {'; '.join(gap.evidence[:3])}"

    prompt = SUGGESTION_PROMPT.format(gaps=gaps_text)

    system = (
        "you are a research advisor helping identify promising research "
        "directions based on literature gaps. provide actionable and "
        "specific suggestions. respond only with valid json."
    )

    try:
        response = await ollama_client.generate_json(
            prompt,
            system=system,
            max_tokens=800,
        )
        data = json.loads(response)
        suggestions_data = data.get("suggestions", [])

        suggestions = []
        for item in suggestions_data:
            suggestions.append(Suggestion(
                suggestion_id=uuid.uuid4().hex[:8],
                title=item.get("title", ""),
                description=item.get("description", ""),
                rationale=item.get("rationale", ""),
                related_gaps=item.get("related_gap_ids", []),
                feasibility=item.get("feasibility", "medium"),
                potential_impact=item.get("potential_impact", "medium"),
            ))

        logger.info("generated %d suggestions from %d gaps", len(suggestions), len(gaps))
        return suggestions

    except Exception as e:
        logger.error("suggestion generation failed: %s", e)
        return []
