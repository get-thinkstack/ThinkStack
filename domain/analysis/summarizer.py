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
    """generate a structured summary of a single research paper.

    sends the paper text to the slm with a structured prompt requesting
    summary, key points, methodology, and limitations.

    args:
        doc_id: the document identifier.
        text: the paper text (or concatenated chunks) to summarize.

    returns:
        populated Summary instance with extracted information.
    """
    system = (
        "you are an academic research assistant specializing in "
        "literature review and paper summarization. respond only with "
        "valid json."
    )

    # How much paper actually fits, on THIS machine.
    #
    # The old code took a flat text[:6000] -- roughly 1500 tokens -- and asked
    # for 1024 tokens of output. That needs ~2650 tokens of context. A low-tier
    # machine gets 2048 (an 8 GB M1, the commonest Mac sold), so the request
    # could not fit in its own window and failed before model quality mattered.
    # The reader was told the response "could not be read", which was not true.
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
        # 1024, not 640. The prompt asks for a summary, key points, methodology
        # AND limitations; 640 tokens could not hold all four for a real paper,
        # so generation stopped mid-string and the JSON never closed. That
        # surfaced to users as "Unterminated string starting at: line 9".
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
    # Share the window between the papers instead of taking a flat 2000
    # characters from each. The old form grew with the number of papers and had
    # no relationship to the context at all: five papers is ~2500 tokens of
    # input against a 2048-token window on a low-tier machine, so adding papers
    # made the request progressively more impossible.
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
