"""
analysis domain models.

data classes for paper summaries, extracted claims, and thematic
clusters produced by the slm-powered analysis engine.
"""

from dataclasses import dataclass, field


@dataclass
class Summary:
    """a generated summary of one or more papers."""
    doc_ids: list[str] = field(default_factory=list)
    summary_text: str = ""
    key_points: list[str] = field(default_factory=list)
    summary_type: str = "single"
    # Set when the paper had to be summarized in pieces because it did not fit
    # the machine's context window. Shown beside the summary, not inside it --
    # it is a fact about this machine, not about the paper.
    notice: str = ""


@dataclass
class Claim:
    """a key finding or claim extracted from a paper."""
    doc_id: str = ""
    claim_text: str = ""
    claim_type: str = ""
    confidence: str = ""
    supporting_text: str = ""


@dataclass
class Theme:
    """a thematic cluster grouping related papers."""
    theme_id: str = ""
    label: str = ""
    description: str = ""
    doc_ids: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)


@dataclass
class AnalysisResult:
    """combined analysis output for a set of papers."""
    summaries: list[Summary] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    themes: list[Theme] = field(default_factory=list)
