"""Data classes for gaps, suggestions, and a gap-analysis result."""

from dataclasses import dataclass, field


@dataclass
class ResearchGap:
    """an identified gap in the research literature."""
    gap_id: str = ""
    gap_type: str = ""
    description: str = ""
    evidence: list[str] = field(default_factory=list)
    related_doc_ids: list[str] = field(default_factory=list)
    severity: str = "medium"


@dataclass
class Suggestion:
    """a suggested research direction based on identified gaps."""
    suggestion_id: str = ""
    title: str = ""
    description: str = ""
    rationale: str = ""
    related_gaps: list[str] = field(default_factory=list)
    feasibility: str = "medium"
    potential_impact: str = "medium"


@dataclass
class GapAnalysisResult:
    """complete output from a gap analysis run."""
    gaps: list[ResearchGap] = field(default_factory=list)
    suggestions: list[Suggestion] = field(default_factory=list)
    papers_analyzed: int = 0
    analysis_scope: str = ""
