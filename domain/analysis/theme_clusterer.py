"""
theme clusterer module.

groups research papers into thematic clusters based on their content
similarity. uses the slm to label and describe identified clusters.
"""

import json
import logging
import uuid

from domain.analysis.models import Theme
from infrastructure.ollama_client import ollama_client

logger = logging.getLogger(__name__)

CLUSTERING_PROMPT = """analyze these research paper summaries and group them into thematic clusters.
for each cluster, provide:
1. a short descriptive label
2. a brief description of the theme
3. which paper ids belong to this cluster
4. keywords associated with this theme

papers:
{papers}

respond in json format with key "themes" containing a list of objects,
each with keys: label, description (1-2 sentences), doc_ids (list),
keywords (list of 3-5). identify between 2 and 4 themes."""


async def cluster_by_themes(texts: dict[str, str]) -> list[Theme]:
    """cluster papers into thematic groups using the slm.

    sends paper excerpts to the language model which identifies
    common themes, assigns papers to clusters, and generates
    descriptive labels and keywords.

    args:
        texts: mapping of doc_id to paper text content.

    returns:
        list of Theme objects representing identified clusters.
    """
    papers_text = ""
    for doc_id, text in texts.items():
        excerpt = text[:1500]
        papers_text += f"\n--- paper (id: {doc_id}) ---\n{excerpt}\n"

    prompt = CLUSTERING_PROMPT.format(papers=papers_text)

    system = (
        "you are a research topic modeling tool. identify thematic "
        "clusters in sets of academic papers. respond only with valid json."
    )

    try:
        response = await ollama_client.generate_json(
            prompt, system=system, max_tokens=640
        )
        data = json.loads(response)
        themes_data = data.get("themes", [])

        themes = []
        for item in themes_data:
            themes.append(Theme(
                theme_id=uuid.uuid4().hex[:8],
                label=item.get("label", ""),
                description=item.get("description", ""),
                doc_ids=item.get("doc_ids", []),
                keywords=item.get("keywords", []),
            ))

        logger.info("identified %d themes across %d papers", len(themes), len(texts))
        return themes

    except Exception as e:
        logger.error("theme clustering failed: %s", e)
        return []
