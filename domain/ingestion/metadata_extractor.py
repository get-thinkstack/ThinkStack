"""Bibliographic metadata: title, authors, abstract, year, arXiv id, DOI.

Called by the upload route with the flat text and page 1's layout. Its result
labels map nodes and search hits and becomes BibTeX entries in Scribe.

Three sources, in descending order of how much they know:

    layout   font size and position on page 1 -- exact on standard papers
    regex    patterns over flat text -- abstract and year only
    slm      the local model, when the first two produce something implausible

Layout comes first because the signal it reads (the title is the biggest text
at the top) is the one the typesetter actually encoded. Flat text has already
thrown that away.
"""

import json
import logging
import re
from datetime import datetime

from domain.ingestion.layout_metadata import (
    NAME_SEPARATOR,
    looks_like_name,
    authors_from_layout,
    layout_digest,
    title_from_layout,
)
from domain.ingestion.models import DocumentMetadata, PageLayout
from infrastructure.ollama_client import ollama_client

logger = logging.getLogger(__name__)

_CURRENT_YEAR = datetime.now().year


def _line_is_authors(line: str) -> bool:
    """Whether a line is the author list, judged without any layout.

    Needs two or more separated parts that all look like people. Without the
    separator rule "Deep Residual Learning" reads as a name; without this check
    at all, the author line is glued onto the title.
    """
    parts = [p.strip() for p in NAME_SEPARATOR.split(line) if p.strip()]
    return len(parts) >= 2 and all(looks_like_name(p) for p in parts)


def _extract_title(text: str) -> str:
    """Title from the first non-empty lines of flat text, or "". The
    no-layout fallback."""
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
        if _line_is_authors(line):
            break
        if len(line) > 10:
            title_lines.append(line)
        if len(title_lines) >= 3:
            break

    return " ".join(title_lines).strip()


def _extract_authors(text: str) -> list[str]:
    """Author names near the title in flat text (comma lists, numbered
    affiliations, lines beside emails). The no-layout fallback."""
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
    """Text between an "Abstract" heading and the next section heading, or ""."""
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


ARXIV_RE = re.compile(r"arXiv:\s*(\d{2})(\d{2})\.(\d{4,5})", re.IGNORECASE)
DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b")


def find_arxiv_id(text: str) -> str:
    """The arXiv identifier, or "". `1706.03762` -- YYMM plus a serial."""
    m = ARXIV_RE.search(text)
    return f"{m.group(1)}{m.group(2)}.{m.group(3)}" if m else ""


def find_doi(text: str) -> str:
    """The first DOI, or "". Trailing sentence punctuation is stripped."""
    m = DOI_RE.search(text)
    return m.group(0).rstrip(".,;)") if m else ""


def _extract_year(text: str) -> str:
    """Publication year, or "" when the page does not state one.

    Ordered by how much the source actually knows:

        arXiv id     YYMM is the submission date, encoded in the identifier
        stated year  a copyright line or "Published ... at VENUE 2019"
        (nothing)    an empty year is a fact; a wrong one poisons a bibliography

    Never "the first four-digit number": on attention.pdf that is 2014, from
    Google's copyright boilerplate, three years off.
    """
    # `arXiv:` is unambiguous, so it is worth finding wherever it is. The
    # stamp is rotated in the left margin, and PyMuPDF emits rotated text
    # after the page body -- past character 3000 on two of three papers here.
    # The looser patterns below stay windowed; away from the front matter a
    # bare year is as likely to belong to a reference as to this paper.
    head = text[:3000]

    arxiv = find_arxiv_id(text)
    if arxiv:
        year = 2000 + int(arxiv[:2])
        if 1990 <= year <= _CURRENT_YEAR + 1:
            return str(year)

    stated = [
        r"(?:©|\(c\)\s|copyright)\s*(?:by\s+)?(?:\w+\s+)?((?:19|20)\d{2})",
        r"(?:published|presented|accepted|appeared|to appear)\b[^.\n]{0,60}?((?:19|20)\d{2})",
    ]
    for pattern in stated:
        for year in re.findall(pattern, head, re.IGNORECASE):
            if 1950 <= int(year) <= _CURRENT_YEAR + 1:
                return year

    return ""


def extract_metadata_regex(text: str) -> DocumentMetadata:
    """All four fields from flat text by pattern. Used when there is no layout."""
    return DocumentMetadata(
        title=_extract_title(text),
        authors=_extract_authors(text),
        abstract=_extract_abstract(text),
        year=_extract_year(text),
    )


async def extract_metadata_slm(
    text: str,
    page: PageLayout | None = None,
) -> DocumentMetadata:
    """Metadata from the local model. Falls back to regex if it is unavailable.

    Given a page, the prompt carries font sizes (`layout_digest`), not flat
    text: flat text has lost the signal that marks the title.
    """
    if page is not None and page.spans:
        body = (
            "page 1, one row per line, prefixed by its font size in points. "
            "the title is normally the largest text near the top; the authors "
            "are on the rows just below it.\n\n"
            f"{layout_digest(page)}"
        )
    else:
        body = f"paper text:\n{text[:3000]}"

    prompt = (
        "extract the following metadata from this research paper. "
        "return a json object with keys: title, authors (list of strings), "
        "abstract, year. authors are people -- never institutions, "
        "departments or email addresses. if a field cannot be determined, "
        "use an empty string or empty list.\n\n"
        f"{body}"
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


# Page furniture that a "biggest text at the top" rule can legitimately pick up:
# journal banners, licence boilerplate, cover pages.
_NOT_A_TITLE = re.compile(
    r"^(abstract|introduction|contents|references|keywords|acknowledg"
    r"|provided proper attribution|copyright|©|downloaded from|licensed under"
    r"|proceedings of|preprint|under review|submitted to|draft)",
    re.IGNORECASE,
)

TITLE_MIN_CHARS = 8
TITLE_MAX_CHARS = 300


def title_is_plausible(title: str) -> bool:
    """Whether a title is worth keeping, or whether something else should try.

    Not "is this correct" -- nothing here can know that. This rejects the
    shapes that are certainly wrong, so the model gets a turn on those and
    only those.
    """
    title = title.strip()
    if not (TITLE_MIN_CHARS <= len(title) <= TITLE_MAX_CHARS):
        return False
    if _NOT_A_TITLE.match(title):
        return False
    if len(title.split()) < 2:
        return False
    letters = sum(c.isalpha() for c in title)
    return letters >= len(title) * 0.5


def metadata_is_plausible(metadata: DocumentMetadata) -> bool:
    """A usable result has a plausible title AND at least one author.

    Test plausibility, never just emptiness: extraction fails confidently (a
    copyright notice as the title), not silently, and a guard that waits for
    an empty title never hands the model the papers it exists to rescue.
    """
    return title_is_plausible(metadata.title) and bool(metadata.authors)


def extract_metadata_layout(page: PageLayout, text: str) -> DocumentMetadata:
    """Title and authors from geometry; abstract and year from the text."""
    return DocumentMetadata(
        title=title_from_layout(page),
        authors=authors_from_layout(page),
        abstract=_extract_abstract(text),
        year=_extract_year(text),
    )


async def extract_metadata(
    text: str,
    page: PageLayout | None = None,
    use_slm: bool = True,
) -> DocumentMetadata:
    """Best available metadata for one document.

    Layout when there is a page to read, regex otherwise, and the model only
    when what came back fails `metadata_is_plausible`. That last condition is
    the point: the model is slow enough that running it on every upload is not
    an option, and precise enough on cover pages and unusual templates to be
    worth waiting for on the few that need it.

    Whichever path answers, the identifiers are stamped on the way out. They
    come from the raw text on all three, so finding them once here keeps the
    extractors to the job their names describe.
    """
    metadata = await _best_metadata(text, page, use_slm)
    metadata.arxiv_id = find_arxiv_id(text)
    metadata.doi = find_doi(text)
    return metadata


async def _best_metadata(
    text: str,
    page: PageLayout | None,
    use_slm: bool,
) -> DocumentMetadata:
    """Title, authors, abstract and year -- the fields that need a strategy."""
    if page is not None and page.spans:
        metadata = extract_metadata_layout(page, text)
        if metadata_is_plausible(metadata):
            return metadata
        logger.info("layout metadata implausible (title=%r), trying slm", metadata.title)
    else:
        metadata = extract_metadata_regex(text)
        if metadata_is_plausible(metadata):
            return metadata
        logger.info("regex metadata implausible, trying slm")

    if not use_slm:
        return metadata

    from_slm = await extract_metadata_slm(text, page=page)
    # The model is a second opinion, not an override. Keep whichever fields
    # it actually improved; a model that returns "" must not erase a good
    # title that layout already found.
    return DocumentMetadata(
        title=from_slm.title if title_is_plausible(from_slm.title) else metadata.title,
        authors=from_slm.authors or metadata.authors,
        abstract=from_slm.abstract or metadata.abstract,
        year=from_slm.year or metadata.year,
    )
