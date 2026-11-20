"""Themes: group papers by embedding similarity, then have the model name them.

    which papers group   cosine between paper centroids (deterministic, free)
    what a group is      one model call, which cannot change membership

The model never decides membership (ADR 2026-08-01). Used by LitGraph's Themes
action and by the re-cluster precompute queues after each ingest.
"""

import json
import logging
import uuid

import numpy as np

from domain.analysis.models import Theme
from domain.knowledge_base.repository import get_doc_centroids
from infrastructure.ollama_client import ollama_client

logger = logging.getLogger(__name__)

# Cosine above which two papers are "about the same thing".
#
# Academic text embeds into a narrow cone -- all-MiniLM-L6-v2 scores two
# unrelated papers around 0.3-0.5 and two genuinely related ones around
# 0.7-0.85 -- so this sits above the noise floor but below the related band.
# A focused library collapsing to a single theme is the correct answer for a
# focused library, not a failure of the threshold.
THEME_THRESHOLD = 0.60

# Text per paper handed to the labelling call. Only needs to be enough to name
# a group whose membership is already decided, so it is deliberately small:
# the whole point of deciding membership from embeddings is that the model no
# longer needs to read everything.
_LABEL_EXCERPT = 700

LABEL_PROMPT = """below are groups of research papers. the grouping is already decided -- do not change it.

for each group, in the same order, provide:
1. label: a short descriptive theme name (2-5 words)
2. description: one or two sentences describing what unites the group
3. keywords: 3-5 keywords

{groups}

respond in json with key "groups" containing a list of objects with keys
label, description, keywords. return exactly {n} objects, in the same order."""

_SYSTEM = (
    "you are a research topic labelling tool. you are given groups of papers "
    "that are already clustered, and you name them. respond only with valid json."
)


def _components(ids: list[str], matrix: np.ndarray, threshold: float) -> list[list[str]]:
    """Connected components of the graph "cosine >= threshold", largest first.

    Single-linkage on purpose: a paper bridging two subtopics joins both, and
    a territory is a region of related work, not a tight ball. A paper similar
    to nothing is its own group.
    """
    n = len(ids)
    if n == 0:
        return []
    if n == 1:
        return [[ids[0]]]

    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    unit = matrix / norms
    sim = unit @ unit.T

    # union-find. n is a library, not a corpus, so the naive form is plenty.
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            if sim[i, j] >= threshold:
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[ri] = rj

    groups: dict[int, list[str]] = {}
    for i, doc_id in enumerate(ids):
        groups.setdefault(find(i), []).append(doc_id)

    return sorted(groups.values(), key=len, reverse=True)


async def _label(groups: list[list[str]], texts: dict[str, str]) -> list[dict]:
    """name each group with one slm call.

    returns a list aligned with ``groups``. a failed or short response yields
    empty dicts rather than raising: an unnamed theme still draws a correct
    hull, whereas dropping the theme would lose a correct grouping over a
    cosmetic failure.
    """
    blocks = []
    for i, group in enumerate(groups):
        excerpts = "\n".join(
            texts.get(d, "")[:_LABEL_EXCERPT] for d in group
        )
        blocks.append(f"--- group {i + 1} ({len(group)} papers) ---\n{excerpts}")

    prompt = LABEL_PROMPT.format(groups="\n\n".join(blocks), n=len(groups))

    try:
        response = await ollama_client.generate_json(
            prompt, system=_SYSTEM, max_tokens=200 + 120 * len(groups),
            task_type="analysis",
        )
        data = json.loads(response)
    except Exception as e:  # noqa: BLE001 - labelling is cosmetic, grouping is not
        logger.error("theme labelling failed, themes stay unnamed: %s", e)
        return [{} for _ in groups]

    got = data.get("groups")
    if not isinstance(got, list):
        logger.warning("theme labelling returned %s, not a list of groups", type(got).__name__)
        return [{} for _ in groups]

    # pad or truncate to the group count -- the model's job was naming, so a
    # miscount must not shift labels onto the wrong group.
    out = []
    for i in range(len(groups)):
        item = got[i] if i < len(got) and isinstance(got[i], dict) else {}
        out.append(item)
    return out


async def cluster_by_themes(texts: dict[str, str]) -> list[Theme]:
    """Themes for these papers. Every returned doc_id is real, and every paper
    appears exactly once."""
    doc_ids = list(texts.keys())
    ids, matrix = get_doc_centroids(doc_ids)

    if not ids:
        logger.warning("no stored embeddings for the requested papers; no themes")
        return []

    groups = _components(ids, matrix, THEME_THRESHOLD)
    labels = await _label(groups, texts)

    themes = []
    for i, (group, meta) in enumerate(zip(groups, labels)):
        themes.append(Theme(
            theme_id=uuid.uuid4().hex[:8],
            label=str(meta.get("label") or f"Theme {i + 1}"),
            description=str(meta.get("description") or ""),
            doc_ids=group,
            keywords=[str(k) for k in (meta.get("keywords") or []) if k],
        ))

    logger.info(
        "clustered %d papers into %d themes (sizes: %s)",
        len(ids), len(themes), [len(g) for g in groups],
    )
    return themes
