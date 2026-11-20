"""citing the library from inside a paper project.

Mounted under the papers router, so every path here is
``/api/papers/projects/{project_id}/citations``.

Two routes, because the editor asks two different questions:

    GET   what could I cite, and what key would each one have
    POST  I picked that one -- put it in references.bib and tell me its key

The GET is what fills the dropdown as the author types, so it answers for the
whole library at once and never writes. The POST is the commitment, and it is
the only place a key becomes permanent.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from domain.knowledge_base.author_codec import decode_authors
from domain.knowledge_base.repository import get_document_metadata
from domain.paper_writer import bibliography as B
from domain.paper_writer.compiler import ProjectIdError, _get_project_dir
from infrastructure.file_manager import list_stored_pdfs

logger = logging.getLogger(__name__)
router = APIRouter()


def _project(project_id: str) -> Path:
    try:
        d = _get_project_dir(project_id)
    except ProjectIdError:
        raise HTTPException(status_code=404, detail="project not found") from None
    if not d.is_dir():
        raise HTTPException(status_code=404, detail="project not found")
    return d


def _library() -> list[B.Citable]:
    """Every ingested document, in the order the dropdown should show them.

    Sorted by title so the list is stable between two requests, and because
    the author is scanning it by eye. That order also decides who keeps the
    unsuffixed key when two papers would collide, which is only ever a
    tiebreak between papers neither of which has been cited yet.

    The filename stands in for a missing title. A row the author cannot read
    is a row they cannot pick, and `attention.pdf` is at least recognisable.
    """
    meta_by_doc = get_document_metadata()

    docs: list[B.Citable] = []
    for pdf in list_stored_pdfs():
        doc_id = pdf["doc_id"]
        meta = meta_by_doc.get(doc_id)
        if meta is None:
            continue  # stored file with no chunks -- ingestion never finished
        docs.append(B.Citable(
            doc_id=doc_id,
            title=meta.get("title") or Path(pdf["filename"]).stem,
            authors=decode_authors(meta.get("authors", "")),
            year=str(meta.get("year") or ""),
            arxiv_id=str(meta.get("arxiv_id") or ""),
            doi=str(meta.get("doi") or ""),
        ))

    docs.sort(key=lambda d: (d.title.lower(), d.doc_id))
    return docs


def _library_with_keys():
    """Every citable paper with the key it would be cited by.

    The same pairing the dropdown uses, exposed so the bibliography panel can
    put a title against a key the document already cites.
    """
    taken: list[str] = []
    for doc in _library():
        key = B.bibkey(doc, taken)
        taken.append(key)
        yield doc, key


def _as_row(doc: B.Citable, key: str, cited: bool) -> dict:
    return {
        "doc_id": doc.doc_id,
        "key": key,
        "title": doc.title,
        "authors": doc.authors,
        "year": doc.year,
        "cited": cited,
    }


class CiteRequest(BaseModel):
    doc_id: str


@router.get("/projects/{project_id}/citations")
async def api_list_citations(project_id: str):
    """Everything citable, each with the key it would be cited by.

    `cited` says the entry is already in this project's references.bib. The
    dropdown does not hide those -- the same paper is cited many times in a
    real document, and the second citation is the common case, not the edge.
    """
    project_dir = _project(project_id)
    docs = _library()
    bib_text = B.read_bib(project_dir)
    already = set(B.parse_entries(bib_text))
    keys = B.assign_keys(docs, bib_text)

    return {
        "project_id": project_id,
        "citations": [_as_row(d, keys[d.doc_id], d.doc_id in already) for d in docs],
    }


@router.post("/projects/{project_id}/citations")
async def api_add_citation(project_id: str, req: CiteRequest):
    """Add the document to references.bib if it is not there, and return its key.

    Idempotent: citing the same paper twice writes one entry and returns the
    same key both times, which is what lets the editor call this on every
    insertion without tracking what it has already sent.
    """
    project_dir = _project(project_id)

    doc = next((d for d in _library() if d.doc_id == req.doc_id), None)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")

    try:
        key, added = B.cite(project_dir, doc)
    except OSError as e:
        logger.error("could not write references.bib for %s: %s", project_id, e)
        raise HTTPException(status_code=500, detail="Could not write the bibliography.") from e

    return {"key": key, "added": added, "cite": f"\\cite{{{key}}}"}


@router.get("/projects/{project_id}/bibliography")
async def api_bibliography(project_id: str):
    """What this document cites, and whether each citation will resolve.

    `references.bib` says what COULD be cited; the source says what IS. They
    drift both ways: a key cited but missing from the bib renders as [?], and
    an entry nothing cites is carried forever. Both are reported.
    """
    d = _project(project_id)
    tex = d / "main.tex"
    source = tex.read_text(encoding="utf-8") if tex.is_file() else ""

    used = B.cited_keys(source)
    defined = B.bib_keys(B.read_bib(d))
    library = {row["key"]: row for row in (_as_row(doc, key, False)
                                           for doc, key in _library_with_keys())}

    entries = []
    for key, count in sorted(used.items(), key=lambda kv: -kv[1]):
        known = library.get(key)
        entries.append({
            "key": key,
            "count": count,
            "in_bib": key in defined,
            "doc_id": (known or {}).get("doc_id"),
            "title": (known or {}).get("title"),
            "authors": (known or {}).get("authors"),
            "year": (known or {}).get("year"),
            # cited but undefined is the one that renders as [?]
            "status": "ok" if key in defined else "missing",
        })

    unused = [k for k in defined if k not in used]
    return {"entries": entries, "unused": unused, "total_cited": sum(used.values())}
