"""Summaries: one paper, or a comparison across several.

Input is sized to THIS machine's context window
(`ollama_client.input_char_budget`), not a fixed slice. A paper that does not fit is summarised in pieces, then the pieces are
summarised (`_map_reduce`), and the result says so.
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

# Used for one PIECE of a paper that did not fit the context window. Kept
# deliberately small: the pieces are only raw material for the reduce step, so
# spending output tokens on structure here wastes the budget twice.
CHUNK_PROMPT = """summarize this section of a research paper in 2-3 sentences.
state only what this section says.

section:
{text}
"""

# Ceiling on the map pass. On a low-tier machine each piece is a separate
# generation on a 0.5B, so an unbounded count on a long thesis would look like
# a hang. Eight pieces at a low-tier window is roughly 45k characters, which
# covers abstract, method and results -- the parts a summary is built from.
MAX_MAP_PIECES = 8

SLOW_MACHINE_NOTICE = (
    "This paper was summarized in pieces because it does not fit this "
    "machine's context window. Add a better model to speed this up."
)

MULTI_PAPER_PROMPT = """you are analyzing multiple research papers on a related topic.
provide a comparative summary covering common themes, differing methodologies,
and points of agreement and disagreement.

papers:
{papers}

respond in json format with keys: summary (concise), key_points (4-6 short
strings capturing the comparison, in your own words -- do not quote)."""


async def _map_reduce(
    text: str, room: int, system: str, out_tokens: int
) -> tuple[str, list[str]]:
    """Summarize a paper that does not fit the context window, in two passes.

    MAP:    each piece is summarized on its own, as plain prose.
    REDUCE: those piece summaries become the input to the normal structured
            prompt, which produces the summary and key points.

    Only the reduce step asks for JSON. Structured output costs a small model
    both accuracy and tokens, and the map results are raw material nobody
    reads -- paying that cost per piece would spend the budget twice for no
    gain.

    The pieces are capped. Without a cap a long thesis on a low-tier machine
    would issue dozens of sequential generations on a 0.5B and appear to hang;
    the opening sections of a paper carry the abstract, method and results,
    which is what a summary is mostly built from anyway.
    """
    pieces = [text[i:i + room] for i in range(0, len(text), room)][:MAX_MAP_PIECES]
    logger.info("summarizing in %d piece(s): text=%d chars, room=%d",
                len(pieces), len(text), room)

    partials: list[str] = []
    for n, piece in enumerate(pieces, 1):
        part = await ollama_client.generate(
            CHUNK_PROMPT.format(text=piece),
            max_tokens=256,
            task_type="analysis",
        )
        part = (part or "").strip()
        if part:
            partials.append(part)
        logger.info("  piece %d/%d -> %d chars", n, len(pieces), len(part))

    if not partials:
        raise RuntimeError("every piece of the paper summarized to nothing")

    # The joined partials must themselves fit the window.
    joined = "\n".join(partials)[:room]
    response = await ollama_client.generate_json(
        SINGLE_PAPER_PROMPT.format(text=joined),
        system=system,
        max_tokens=out_tokens,
        task_type="analysis",
    )
    data = json.loads(response)
    return data.get("summary", ""), data.get("key_points", [])


async def summarize_single(doc_id: str, text: str) -> Summary:
    """Summary, key points, methodology and limitations for one paper."""
    system = (
        "you are an academic research assistant specializing in "
        "literature review and paper summarization. respond only with "
        "valid json."
    )

    # How much paper fits on THIS machine. Never a fixed slice: a low-tier
    # machine's window (2048) cannot hold a 6000-character slice plus 1024
    # output tokens, and the request fails before model quality matters.
    out_tokens = ollama_client.output_token_budget("analysis")
    budget = ollama_client.input_char_budget(max_tokens=out_tokens, task_type="analysis")
    overhead = len(SINGLE_PAPER_PROMPT.replace("{text}", ""))
    room = max(0, budget - overhead)

    try:
        if room and len(text) > room:
            # Does not fit: summarize the pieces, then summarize those.
            # Slower, and on a small model noticeably so -- hence the notice.
            summary_text, key_points = await _map_reduce(
                text, room, system, out_tokens
            )
            return Summary(
                doc_ids=[doc_id],
                summary_text=summary_text,
                key_points=key_points,
                summary_type="single",
                notice=SLOW_MACHINE_NOTICE,
            )

        # Fits in one pass. Still bounded by `room` rather than a flat 6000, so
        # a roomy machine uses more of the paper and a cramped one does not
        # overflow.
        prompt = SINGLE_PAPER_PROMPT.format(text=text[:room or 6000])
        # At least 1024: four fields do not fit in less, and a cut-off reply is
        # unterminated JSON.
        response = await ollama_client.generate_json(
            prompt, system=system, max_tokens=out_tokens, task_type="analysis"
        )
        data = json.loads(response)
        return Summary(
            doc_ids=[doc_id],
            summary_text=data.get("summary", ""),
            key_points=data.get("key_points", []),
            summary_type="single",
        )
    except Exception as e:
        # The exception goes to the log, never into summary_text (the UI would
        # show it as the summary).
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
    """Themes, agreements and disagreements across several papers."""
    # Share the window between the papers. A fixed amount per paper grows
    # with the selection and overflows a small window.
    out_tokens = ollama_client.output_token_budget("analysis")
    budget = ollama_client.input_char_budget(max_tokens=out_tokens, task_type="analysis")
    overhead = len(MULTI_PAPER_PROMPT.replace("{papers}", ""))
    # each paper also carries its own "--- paper N (id: ...) ---" header
    per_paper = max(400, (max(0, budget - overhead) // max(1, len(texts))) - 60)

    papers_text = ""
    for i, (doc_id, text) in enumerate(texts.items()):
        excerpt = text[:per_paper]
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
            prompt, system=system, max_tokens=out_tokens, task_type="analysis"
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
