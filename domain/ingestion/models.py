"""Data classes for ingestion: metadata, page layout (spans), and chunks."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class DocumentMetadata:
    """metadata extracted from a research paper."""
    title: str = ""
    authors: list[str] = field(default_factory=list)
    abstract: str = ""
    year: str = ""
    source: str = ""
    pages: int = 0
    # Kept for citing: a BibTeX entry with neither is a dead reference.
    arxiv_id: str = ""
    doi: str = ""


@dataclass
class TextSpan:
    """one run of glyphs sharing a font and size, at a position on the page.

    `horizontal` is false for rotated text. arXiv stamps the left margin
    sideways at a larger size than the title, so rotation has to be visible
    here or the stamp wins every "largest text" comparison.
    """
    text: str = ""
    size: float = 0.0
    x0: float = 0.0
    y0: float = 0.0
    x1: float = 0.0
    y1: float = 0.0
    horizontal: bool = True
    # The line the glyphs sit on. Two sizes on one line do NOT share a y0 --
    # a small-caps title is one row typeset in two sizes, and grouping it by
    # bounding-box top splits it into two. They always share a baseline.
    baseline: float = 0.0


@dataclass
class PageLayout:
    """a page as positioned spans rather than a flat string.

    width/height are needed to reason in fractions -- "top third", "left
    margin" -- since page sizes differ between A4 and US Letter papers.
    """
    page_number: int = 0
    width: float = 0.0
    height: float = 0.0
    spans: list["TextSpan"] = field(default_factory=list)


@dataclass
class TextChunk:
    """a segment of text from a document with positional information."""
    chunk_id: str = ""
    doc_id: str = ""
    text: str = ""
    page_number: int = 0
    chunk_index: int = 0
    token_count: int = 0


@dataclass
class Document:
    """a fully processed research document ready for knowledge base storage."""
    doc_id: str = ""
    filename: str = ""
    file_path: str = ""
    metadata: DocumentMetadata = field(default_factory=DocumentMetadata)
    chunks: list[TextChunk] = field(default_factory=list)
    raw_text: str = ""
    ingested_at: str = field(default_factory=lambda: datetime.now().isoformat())
    status: str = "pending"
