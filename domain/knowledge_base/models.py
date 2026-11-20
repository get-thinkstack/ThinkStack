"""Data classes for stored chunks and store statistics."""

from dataclasses import dataclass, field


@dataclass
class KnowledgeEntry:
    """a single indexed entry in the knowledge base."""
    entry_id: str = ""
    doc_id: str = ""
    text: str = ""
    embedding: list[float] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class CollectionStats:
    """Counts for the vector store."""
    name: str = ""
    count: int = 0
    document_count: int = 0
