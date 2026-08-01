"""
search api routes.

exposes semantic search over the knowledge base, either as a ranked list
of chunks or rolled up to the papers that contain them.
"""

import logging
from dataclasses import asdict

from fastapi import APIRouter
from pydantic import BaseModel, Field

from domain.search.models import SearchQuery
from domain.search.semantic_search import semantic_search, search_papers

logger = logging.getLogger(__name__)
router = APIRouter()


class SearchRequest(BaseModel):
    """request body for search endpoints."""
    query: str
    top_k: int = Field(default=10, ge=1, le=50)
    doc_ids: list[str] = Field(default_factory=list)
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)
    group_by_doc: bool = False


@router.post("")
async def search(request: SearchRequest):
    """search the knowledge base by meaning.

    embeds the query and ranks it against every stored chunk by cosine
    similarity, with a small bonus for chunks containing query tokens
    verbatim so rare literal terms stay findable.

    args:
        request: search parameters including query text and filters.

    returns:
        ranked results with relevance scores. with ``group_by_doc`` the
        results are papers carrying their matching chunks; otherwise they
        are individual chunks.
    """
    search_query = SearchQuery(
        query=request.query,
        top_k=request.top_k,
        doc_ids=request.doc_ids,
        min_score=request.min_score,
    )

    if request.group_by_doc:
        papers = search_papers(search_query)
        return {
            "query": request.query,
            "results": papers,
            "total_found": len(papers),
            "search_type": "semantic",
            "grouped": True,
        }

    results = semantic_search(search_query)
    return {
        "query": request.query,
        "results": [asdict(r) for r in results],
        "total_found": len(results),
        "search_type": "semantic",
        "grouped": False,
    }
