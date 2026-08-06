"""
metadata extractor module.

extracts bibliographic metadata (title, authors, abstract, year) from
research paper text using regex pattern matching with an optional slm
fallback for papers with non-standard formatting.
"""

import json
import logging
import re

from domain.ingestion.models import DocumentMetadata
from infrastructure.ollama_client import ollama_client

logger = logging.getLogger(__name__)


def _extract_title(text: str) -> str:
    """extract the paper title from the first lines of text.

    assumes the title appears in the first few non-empty lines before
    any abstract or author section.

    args:
        text: the full document text.

    returns:
        extracted title string, or empty string if not found.
    """
    lines = text.strip().split("\n")
    title_lines = []

    for line in lines[:10]:
        line = line.strip()
        if not line:
            if title_lines:
                break
            continue
        lower = line.lower()
        if any(kw in lower for kw in ["abstract", "introduction", "keywords", "@"]):
            break
        if len(line) > 10:
            title_lines.append(line)
        if len(title_lines) >= 3:
            break

    return " ".join(title_lines).strip()


def _extract_authors(text: str) -> list[str]:
    """extract author names from the text near the title.

    looks for common author formatting patterns including comma-separated
    names, numbered affiliations, and email-adjacent lines.

    args:
        text: the full document text.

    returns:
        list of author name strings.
    """
    lines = text.strip().split("\n")
    authors = []

    for i, line in enumerate(lines[:20]):
        line = line.strip()
        if re.search(r"[a-z]\.[a-z]", line) and "@" in line:
            continue
        if re.match(r"^[A-Z][a-z]+ [A-Z][a-z]+", line):
            if "abstract" not in line.lower() and len(line) < 200:
                names = re.split(r",\s*|\s+and\s+", line)
                for name in names:
                    name = name.strip()
                    if re.match(r"^[A-Z][a-z]+ [A-Z]", name) and len(name) < 50:
                        authors.append(name)

    return authors[:10]


def _extract_abstract(text: str) -> str:
    """extract the abstract section from the paper text.

    searches for explicit abstract markers and captures the text between
    the abstract heading and the next major section heading.

    args:
        text: the full document text.

    returns:
        abstract text string, or empty string if not found.
    """
    patterns = [
        r"(?i)abstract[\s\.\-:]*\n(.*?)(?:\n\s*(?:introduction|keywords|1[\.\s]))",
        r"(?i)abstract[\s\.\-:]*(.*?)(?:\n\s*\n)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            abstract = match.group(1).strip()
            abstract = re.sub(r"\s+", " ", abstract)
            if len(abstract) > 50:
                return abstract[:2000]

    return ""


def _extract_year(text: str) -> str:
    """extract the publication year from the text.

    looks for four-digit years in common academic formats such as
    copyright notices, date lines, and citation patterns.

    args:
        text: the full document text.

    returns:
        year string, or empty string if not found.
    """
    patterns = [
        r"(?:published|accepted|received|copyright|©)\s*:?\s*\w*\s*(\d{4})",
        r"\b((?:19|20)\d{2})\b",
    ]

    first_section = text[:3000]
    for pattern in patterns:
        matches = re.findall(pattern, first_section, re.IGNORECASE)
        for year in matches:
            if 1950 <= int(year) <= 2030:
                return year
    return ""


def extract_metadata_regex(text: str) -> DocumentMetadata:
    """extract paper metadata using regex patterns.

    applies multiple heuristic regex patterns to extract title, authors,
    abstract, and publication year from the raw paper text.

    args:
        text: the full document text.

    returns:
        populated DocumentMetadata instance.
    """
    return DocumentMetadata(
        title=_extract_title(text),
        authors=_extract_authors(text),
        abstract=_extract_abstract(text),
        year=_extract_year(text),
    )


async def extract_metadata_slm(text: str) -> DocumentMetadata:
    """extract paper metadata using the local slm via ollama.

    sends the first portion of the paper text to the language model
    with a structured extraction prompt. falls back to regex extraction
    if the slm is unavailable or returns unparseable output.

    args:
        text: the full document text.

    returns:
        populated DocumentMetadata instance.
    """
    excerpt = text[:3000]

    prompt = (
        "extract the following metadata from this research paper text. "
        "return a json object with keys: title, authors (list of strings), "
        "abstract, year. if a field cannot be determined, use an empty "
        "string or empty list.\n\n"
        f"paper text:\n{excerpt}"
    )

    system = (
        "you are an academic metadata extraction tool. "
        "respond only with valid json, no explanation."
    )

    try:
        response = await ollama_client.generate_json(
            prompt, system=system, max_tokens=640,
            # "general" here is a choice, not an oversight. Pulling a title and
            # an author list off the first page is shallow work that runs on
            # EVERY upload, and there is a regex fallback right below if it
            # fails. Routing it to the heavy analysis model would make every
            # ingest wait on a model swap to do a job the small one does fine.
            task_type="general",
        )
        data = json.loads(response)
        return DocumentMetadata(
            title=data.get("title", ""),
            authors=data.get("authors", []),
            abstract=data.get("abstract", ""),
            year=str(data.get("year", "")),
        )
    except Exception as e:
        logger.warning("slm metadata extraction failed, using regex: %s", e)
        return extract_metadata_regex(text)


async def extract_metadata(text: str, use_slm: bool = True) -> DocumentMetadata:
    """extract paper metadata with optional slm enhancement.

    tries regex extraction first. if the result is incomplete and
    use_slm is enabled, falls back to slm-based extraction.

    args:
        text: the full document text.
        use_slm: whether to attempt slm extraction for incomplete results.

    returns:
        populated DocumentMetadata instance.
    """
    metadata = extract_metadata_regex(text)

    if use_slm and (not metadata.title or not metadata.abstract):
        logger.info("regex extraction incomplete, trying slm")
        metadata = await extract_metadata_slm(text)

    return metadata
