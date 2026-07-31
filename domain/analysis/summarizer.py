"""
summarizer module.

generates single-paper and multi-paper comparative summaries using
the local slm via ollama. designed for academic literature review
with structured output including key points.
"""

import json
import logging

from domain.analysis.models import Summary
from infrastructure.ollama_client import ollama_client

logger = logging.getLogger(__name__)

SINGLE_PAPER_PROMPT = """summarize the following research paper text. provide:
1. summary: a concise 3-5 sentence overview
2. key_points: 4-6 short bullet strings covering the main findings,
   methodology, and limitations -- in your own words, do not quote the paper

paper text:
{text}

respond in json format with keys: summary, key_points (list of strings)."""

MULTI_PAPER_PROMPT = """you are analyzing multiple research papers on a related topic.
provide a comparative summary covering common themes, differing methodologies,
and points of agreement and disagreement.

papers:
{papers}

respond in json format with keys: summary (concise), key_points (4-6 short
strings capturing the comparison, in your own words -- do not quote)."""


async def summarize_single(doc_id: str, text: str) -> Summary:
    """generate a structured summary of a single research paper.

    sends the paper text to the slm with a structured prompt requesting
    summary, key points, methodology, and limitations.

    args:
        doc_id: the document identifier.
        text: the paper text (or concatenated chunks) to summarize.

    returns:
        populated Summary instance with extracted information.
    """
    truncated = text[:6000]
    prompt = SINGLE_PAPER_PROMPT.format(text=truncated)

    system = (
        "you are an academic research assistant specializing in "
        "literature review and paper summarization. respond only with "
        "valid json."
    )

    try:
        # 1024, not 640. The prompt asks for a summary, key points, methodology
        # AND limitations; 640 tokens could not hold all four for a real paper,
        # so generation stopped mid-string and the JSON never closed. That
        # surfaced to users as "Unterminated string starting at: line 9".
        response = await ollama_client.generate_json(
            prompt, system=system, max_tokens=1024, task_type="analysis"
        )
        data = json.loads(response)
        return Summary(
            doc_ids=[doc_id],
            summary_text=data.get("summary", ""),
            key_points=data.get("key_points", []),
            summary_type="single",
        )
    except Exception as e:
        # The exception text is for the log, not the reader. Putting str(e) in
        # summary_text meant a parser error was rendered in the UI as though it
        # were the summary of the paper.
        logger.error("summarization failed for %s: %s", doc_id, e, exc_info=True)
        return Summary(
            doc_ids=[doc_id],
            summary_text=(
                "This paper could not be summarized. The local model returned a "
                "response that could not be read. Try running it again, or select "
                "fewer papers so each one gets more of the model's attention."
            ),
            summary_type="single",
        )


async def summarize_multiple(doc_ids: list[str], texts: dict[str, str]) -> Summary:
    """generate a comparative summary across multiple papers.

    creates a combined prompt with excerpts from each paper and asks
    the slm for a comparative analysis identifying themes, agreements,
    and disagreements.

    args:
        doc_ids: list of document identifiers being compared.
        texts: mapping of doc_id to paper text content.

    returns:
        populated Summary instance with comparative analysis.
    """
    papers_text = ""
    for i, (doc_id, text) in enumerate(texts.items()):
        excerpt = text[:2000]
        papers_text += f"\n--- paper {i + 1} (id: {doc_id}) ---\n{excerpt}\n"

    prompt = MULTI_PAPER_PROMPT.format(papers=papers_text)

    system = (
        "you are an academic research assistant specializing in "
        "comparative literature review. respond only with valid json."
    )

    try:
        # A comparative summary grows with the number of papers, so it needs
        # more room than the single-paper case, not less. See the note there.
        response = await ollama_client.generate_json(
            prompt, system=system, max_tokens=1280, task_type="analysis"
        )
        data = json.loads(response)
        return Summary(
            doc_ids=doc_ids,
            summary_text=data.get("summary", ""),
            key_points=data.get("key_points", []),
            summary_type="comparative",
        )
    except Exception as e:
        logger.error("multi-paper summarization failed: %s", e, exc_info=True)
        return Summary(
            doc_ids=doc_ids,
            summary_text=(
                "These papers could not be compared. The local model returned a "
                "response that could not be read. Try again with fewer papers "
                "selected."
            ),
            summary_type="comparative",
        )
