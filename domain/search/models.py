"""Data classes for a search query, a result, and a response."""

from dataclasses import dataclass, field


@dataclass
class SearchQuery:
    """a user search request with optional filters."""
    query: str = ""
    top_k: int = 10
    doc_ids: list[str] = field(default_factory=list)
    min_score: float = 0.0


@dataclass
class SearchResult:
    """a single search result with relevance scoring."""
    chunk_id: str = ""
    doc_id: str = ""
    text: str = ""
    score: float = 0.0
    metadata: dict = field(default_factory=dict)
    source: str = ""


@dataclass
class SearchResponse:
    """aggregated search response containing ranked results."""
    query: str = ""
    results: list[SearchResult] = field(default_factory=list)
    total_found: int = 0
    search_type: str = "hybrid"
