"""what gets computed ahead of time, and when.

the rule: anything the canvas needs in order to be worth looking at is paid for
at ingest, in the background, not when the user opens it. that is summaries and
claims per paper, and then themes and gaps across the library.

the ordering matters and is why this is a queue rather than three fire-and-
forget tasks. gaps read the per-paper summaries out of the analysis cache, so a
gap scan enqueued before the papers are analyzed would score a half-empty
library. running them in submission order gets this for free.
"""

import logging

from infrastructure.analysis_cache import doc_analysis_cache
from infrastructure.jobs import Job, job_queue

logger = logging.getLogger(__name__)


async def _analyze_one(doc_id: str, text: str) -> None:
    """summary + claims for one paper, into the cache the graph reads."""
    from domain.analysis.document_analysis import analyze_document

    analysis = await analyze_document(doc_id, text)
    if analysis is None:
        logger.warning("no analysis produced for %s; it will show unanalyzed", doc_id)
        return
    doc_analysis_cache.put(doc_id, analysis["summary"], analysis["claims"])


async def _recluster() -> None:
    """re-cluster the whole library and record it as the newest themes run.

    written through analysis_history because that is where
    ``graph_builder._latest_themes`` reads from -- so the canvas picks this up
    with no change to the graph path at all.
    """
    from domain.analysis.theme_clusterer import cluster_by_themes
    from domain.knowledge_base.repository import get_all_doc_ids, get_chunks_by_doc_id
    from infrastructure.analysis_history import analysis_history
    from dataclasses import asdict

    doc_ids = get_all_doc_ids()
    if len(doc_ids) < 2:
        logger.info("themes need at least 2 papers, have %d; skipping", len(doc_ids))
        return

    texts = {d: " ".join(get_chunks_by_doc_id(d)["documents"]) for d in doc_ids}
    themes = await cluster_by_themes(texts)
    if not themes:
        return

    analysis_history.add({
        "type": "themes",
        "doc_ids": doc_ids,
        "result": {
            "themes": [asdict(t) for t in themes],
            "total": len(themes),
            "doc_ids": doc_ids,
        },
    })


async def _rescan_gaps() -> None:
    """re-run the library-wide gap scan from the cached per-paper analysis.

    every summary it needs is already in the cache by the time this runs, so
    the expensive part is the single combined gaps+suggestions call -- the same
    one the manual button pays for, just not while the user waits for it.
    """
    from domain.gap_finder.gap_pipeline import analyze_gaps_and_suggestions
    from domain.knowledge_base.repository import get_all_doc_ids
    from infrastructure.gap_history import gap_history
    from dataclasses import asdict

    doc_ids = get_all_doc_ids()
    if len(doc_ids) < 2:
        logger.info("gaps need at least 2 papers, have %d; skipping", len(doc_ids))
        return

    summaries, claims = [], []
    for doc_id in doc_ids:
        cached = doc_analysis_cache.get(doc_id)
        if not cached:
            continue
        summaries.append({"doc_id": doc_id, "text": cached.get("summary", "")})
        for c in cached.get("claims", []):
            claims.append({
                "doc_id": doc_id,
                "text": c.get("text", ""),
                "type": c.get("type", "finding"),
            })

    if len(summaries) < 2:
        logger.info("only %d analyzed papers; skipping the gap scan", len(summaries))
        return

    gaps, suggestions = await analyze_gaps_and_suggestions(summaries, claims, doc_ids)
    if not gaps:
        return

    gap_history.add({
        "doc_ids": doc_ids,
        "gaps": [asdict(g) for g in gaps],
        "suggestions": [asdict(s) for s in suggestions],
        "papers_analyzed": len(summaries),
        "total_claims": len(claims),
        "total_gaps": len(gaps),
        "total_suggestions": len(suggestions),
    })


def schedule_for_new_document(doc_id: str, text: str, title: str = "") -> None:
    """queue everything a newly ingested paper makes stale.

    called from the upload route *after* the response is built, so the upload
    itself never waits on the model.

    args:
        doc_id: the freshly ingested document.
        text: its full text, already in memory from ingestion.
        title: for the progress label; falls back to the id.
    """
    name = (title or doc_id)[:60]

    job_queue.submit(Job(
        kind="analyze",
        label=f"Analysing {name}",
        run=lambda: _analyze_one(doc_id, text),
    ))
    # library-wide work coalesces: adding five papers at once must re-cluster
    # once, after the last of them, not five times.
    job_queue.submit(Job(
        kind="themes",
        label="Grouping the library into themes",
        run=_recluster,
        coalesce=True,
    ))
    job_queue.submit(Job(
        kind="gaps",
        label="Scanning the library for gaps",
        run=_rescan_gaps,
        coalesce=True,
    ))
