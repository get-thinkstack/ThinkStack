"""Scribe routes: projects, templates, write-at-the-cursor, compile, export.

Files inside a project are api/routes_paper_files.py; citations are
api/routes_citations.py. The work is in domain/paper_writer/ (files,
templates, compiler).

`POST /generate` is the only route here that calls a model. Its output is not
trusted: `_strip_echoed_context` and `_clean_latex` remove what a small model
adds beyond the fragment it was asked for, before it reaches the document.
"""

import logging
import re
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from domain.paper_writer.compiler import (
    ProjectIdError,
    create_project,
    rename_project,
    save_source,
    compile_pdf,
    list_projects,
    get_source,
    delete_project,
)
from domain.search.grounding import build_grounding_context
from domain.fine_tuning.data_collector import save_latex_pair
from infrastructure.ollama_client import ollama_client

logger = logging.getLogger(__name__)
router = APIRouter()



# How much of the document to show the model. 6000 characters is roughly 1500
# tokens, which leaves room for the system prompt, any grounding context, and
# the 2048-token output budget.
_CONTEXT_BUDGET = 6000


def _build_edit_prompt(source: str, request: str, cursor: int | None) -> str:
    """Show the model the document centred on the cursor.

    Preamble (so it knows what is loaded), the text before the cursor, an
    insertion marker, the text after. The model is asked only for the fragment
    at the marker. Sending the start of the file instead shows the model the
    introduction, never the place being edited, and it repeats sections.
    """
    marker = "%%% WRITE THE NEW CONTENT HERE %%%"

    # the preamble is short and always relevant: it says what is already loaded
    body_at = source.find("\\begin{document}")
    preamble = source[:body_at] if body_at != -1 else ""
    if len(preamble) > 1200:
        preamble = preamble[:1200] + "\n% (preamble truncated)"

    at = cursor if isinstance(cursor, int) else len(source)
    at = max(0, min(at, len(source)))

    # split the remaining budget either side of the cursor
    room = max(1000, _CONTEXT_BUDGET - len(preamble))
    before = source[max(0, at - room // 2):at]
    after = source[at:at + room // 2]

    if len(preamble) + len(before) + len(after) < len(source):
        logger.info(
            "windowed %d-char document to %d chars around cursor %d",
            len(source), len(preamble) + len(before) + len(after), at,
        )

    parts = []
    if preamble.strip():
        parts.append(
            "The document already has this preamble. These packages are loaded, "
            "so use them without adding \\usepackage:\n"
            f"```\n{preamble.strip()}\n```"
        )
    parts.append(
        "This is the document around the point you are writing into. Produce "
        f"only what replaces {marker}, keeping the surrounding structure "
        "intact and not repeating sections that already exist:\n"
        f"```\n{before}\n{marker}\n{after}\n```"
    )
    parts.append(f"What to write at that point:\n{request}")
    return "\n\n".join(parts)



def _strip_echoed_context(generated: str, before: str, after: str) -> str:
    """Remove document text the model copied back around its new content.

    Asked for a table, a small model often repeats the surrounding headings and
    prose first, and instructions do not stop it. So: drop the longest tail of
    the text before the cursor that the output starts with, and the longest
    head of the text after that it ends with. What remains is what it added.
    """
    out = (generated or "").strip()
    if not out:
        return out

    def norm(x: str) -> str:
        return " ".join(x.split())

    # leading overlap with the text before the cursor
    tail = before[-2000:]
    n_out, n_tail = norm(out), norm(tail)
    best = 0
    for size in range(min(len(n_tail), len(n_out)), 30, -1):
        if n_out.startswith(n_tail[-size:]):
            best = size
            break
    if best:
        # map the normalised match back onto the raw string
        consumed, seen = 0, 0
        for i, ch in enumerate(out):
            if not ch.isspace():
                seen += 1
            elif i and out[i - 1].isspace():
                continue
            else:
                seen += 1
            if seen >= best:
                consumed = i + 1
                break
        out = out[consumed:].lstrip()

    # trailing overlap with the text after the cursor
    head = after[:2000]
    n_out, n_head = norm(out), norm(head)
    best = 0
    for size in range(min(len(n_head), len(n_out)), 30, -1):
        if n_out.endswith(n_head[:size]):
            best = size
            break
    if best:
        cut = len(out)
        seen = 0
        for i in range(len(out) - 1, -1, -1):
            if not out[i].isspace():
                seen += 1
            if seen >= best:
                cut = i
                break
        out = out[:cut].rstrip()

    return out.strip()


def _clean_latex(text: str) -> str:
    """Reduce the model's reply to body content that can go into a document.

    A small model sometimes emits a whole document despite the prompt; pasted
    in, that is a second \\documentclass and preamble mid-paper. Strip it
    here rather than trust the instruction.
    """
    t = (text or "").strip()

    # markdown fences
    fence = re.search(r"```(?:latex|tex)?\s*(.*?)```", t, re.DOTALL)
    if fence:
        t = fence.group(1).strip()
    t = t.replace("```latex", "").replace("```tex", "").replace("```", "").strip()

    # If the model returned a whole document, keep only what is between the
    # document markers; that is the part the caller asked for.
    body = re.search(
        r"\\begin\{document\}(.*?)(?:\\end\{document\}|\Z)", t, re.DOTALL
    )
    if body:
        t = body.group(1)

    # Otherwise drop preamble lines it may have emitted without a document
    # environment. These belong to the template that already exists.
    preamble = re.compile(
        r"^\s*\\(?:documentclass|usepackage|geometry|pgfplotsset|"
        r"begin\{document\}|end\{document\})\b.*$",
        re.MULTILINE,
    )
    t = preamble.sub("", t)

    return t.strip()


class CreateProjectRequest(BaseModel):
    name: str = "untitled"
    template: str | None = None


class SaveSourceRequest(BaseModel):
    project_id: str
    source: str


class GenerateLatexRequest(BaseModel):
    project_id: str
    prompt: str
    current_source: str = ""
    # The caret offset in current_source; see _build_edit_prompt.
    cursor: int | None = None
    doc_ids: list[str] = []          # papers to ground the writing on (rag)
    analysis_context: str = ""       # optional analysis findings to incorporate


class CompileRequest(BaseModel):
    project_id: str


@router.get("/templates")
async def api_templates():
    """The starter documents. Served, not hardcoded in the interface, so the
    picker can never offer a template that does not exist."""
    from domain.paper_writer import templates as T

    return {
        "templates": [
            {"id": t.id, "label": t.label, "description": t.description}
            for t in T.ALL
        ],
        "default": T.DEFAULT,
    }


@router.post("/projects")
async def api_create_project(req: CreateProjectRequest):
    """create a new paper project with a starter template."""
    try:
        return create_project(req.name, req.template)
    except Exception as e:
        logger.error("failed to create project: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects")
async def api_list_projects():
    """list all paper projects."""
    return {"projects": list_projects()}


@router.get("/projects/{project_id}")
async def api_get_project(project_id: str):
    """The project's LaTeX source and display name (for save dialogs and titles)."""
    try:
        source = get_source(project_id)
        return {
            "project_id": project_id,
            "source": source,
            "name": _pdf_name(project_id),
        }
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="project not found")


class RenameProjectRequest(BaseModel):
    name: str


@router.patch("/projects/{project_id}")
async def api_rename_project(project_id: str, req: RenameProjectRequest):
    """rename a paper. Only the display name; the directory keeps its id."""
    try:
        return rename_project(project_id, req.name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="project not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/save")
async def api_save_source(req: SaveSourceRequest):
    """save updated latex source."""
    try:
        return save_source(req.project_id, req.source)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="project not found")
    except ProjectIdError:
        raise                      # answered as 404 by the handler in main
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate")
async def api_generate_latex(req: GenerateLatexRequest):
    """Turn plain language (or pseudocode, or partial LaTeX) into LaTeX for the
    cursor. Routed as task `latex_writer`; optionally grounded in papers."""
    system = (
        "you are a latex expert. the user will give you a prompt describing "
        "what they want written in their academic paper. respond ONLY with "
        "valid, compilable latex code. do not include \\documentclass, "
        "\\begin{document}, or \\end{document} - just the body content. "
        "do not include any explanation or markdown formatting. "
        "only output raw latex code. "
        "the document preamble already loads these packages, so you MAY use "
        "them WITHOUT adding \\usepackage: amsmath, amssymb, graphicx, "
        "booktabs and tabularx (for professional tables), float, caption, "
        "xcolor, tikz and pgfplots (for charts/plots/diagrams; use "
        "\\begin{tikzpicture} or pgfplots axis environments), multirow, array. "
        "for tables prefer booktabs (\\toprule/\\midrule/\\bottomrule) inside a "
        "table float with a caption. for charts use pgfplots axis environments "
        "inside a figure float. "
        "use only widely-supported, standard latex commands; do NOT invent or "
        "\\newcommand-define macros, and do NOT rely on packages other than "
        "those listed. the snippet must compile on its own. "
        "you are editing an existing document, not starting a new one: write "
        "ONLY the fragment that belongs at the marked position, do not repeat "
        "sections, headings or text that already appear around it, and do not "
        "restate the preamble."
    )

    # optional grounding: relevant excerpts from selected papers + analysis
    grounding_parts: list[str] = []
    if req.doc_ids:
        try:
            context_text, _ = build_grounding_context(req.prompt, req.doc_ids)
            if context_text:
                grounding_parts.append(
                    "relevant excerpts from the user's selected papers - "
                    "ground the writing in these and do not fabricate facts:\n"
                    f"{context_text}"
                )
        except Exception as e:  # noqa: BLE001 - grounding is best-effort
            logger.warning("paper grounding skipped: %s", e)
    if req.analysis_context.strip():
        grounding_parts.append(
            f"analysis findings to incorporate:\n{req.analysis_context.strip()}"
        )

    prompt = req.prompt
    if req.current_source:
        prompt = _build_edit_prompt(req.current_source, req.prompt, req.cursor)
    if grounding_parts:
        prompt = "\n\n".join(grounding_parts) + "\n\n" + prompt

    try:
        latex_output = await ollama_client.generate(
            prompt=prompt,
            system=system,
            temperature=0.2,
            max_tokens=2048,
            task_type="latex_writer",
        )
        cleaned = _clean_latex(latex_output)
        if req.current_source:
            at = req.cursor if isinstance(req.cursor, int) else len(req.current_source)
            at = max(0, min(at, len(req.current_source)))
            cleaned = _strip_echoed_context(
                cleaned, req.current_source[:at], req.current_source[at:]
            )

        # save training pair for future fine-tuning (best-effort)
        try:
            save_latex_pair(
                prompt=prompt,
                system=system,
                generated_latex=cleaned,
                current_source=req.current_source,
                grounding_context="\n".join(grounding_parts),
            )
        except Exception:  # noqa: BLE001 - data collection is non-critical
            pass

        return {
            "project_id": req.project_id,
            "generated_latex": cleaned,
        }
    except Exception as e:
        logger.error("latex generation failed: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"ai generation failed: {str(e)}",
        )


@router.post("/compile")
async def api_compile_pdf(req: CompileRequest):
    """compile the project's latex source into a pdf."""
    try:
        _, warnings = compile_pdf(req.project_id)
        return {
            "project_id": req.project_id,
            "status": "compiled",
            "pdf_url": f"/api/papers/download/{req.project_id}",
            "warnings": warnings,
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except ProjectIdError:
        raise                      # answered as 404 by the handler in main
    except Exception as e:
        logger.error("compilation failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


def _pdf_name(project_id: str) -> str:
    """A filename a person would recognise, from the paper's own name.

    Reduced to what every filesystem accepts rather than what any one of them
    does: Windows refuses < > : " / \\ | ? * and trailing dots, and a name that
    works on the machine that saved it should work on the machine it is sent to.
    """
    from domain.paper_writer.compiler import list_projects

    name = ""
    for p in list_projects():
        if p.get("project_id") == project_id:
            name = str(p.get("name") or "")
            break
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name).strip(" .")
    return cleaned[:80] or project_id


class ExportRequest(BaseModel):
    path: str


@router.post("/projects/{project_id}/export-pdf")
async def api_export_pdf(project_id: str, req: ExportRequest):
    """Copy the compiled PDF to a path the author chose in a save dialog.

    An absolute destination is normally the shape of a traversal. Acceptable
    here because the body is JSON (another web page cannot send it without a
    refused preflight), and the caller does not choose the CONTENT: only the
    project's own compiled PDF is copied. The destination must end in .pdf, so
    it cannot drop a file the system would treat as executable.
    """
    from domain.paper_writer.compiler import ProjectIdError, _get_project_dir

    try:
        pdf_file = _get_project_dir(project_id) / "main.pdf"
    except ProjectIdError:
        raise HTTPException(status_code=404, detail="project not found") from None
    if not pdf_file.exists():
        raise HTTPException(status_code=404, detail="Compile the paper first.")

    target = Path(req.path).expanduser()
    if not target.is_absolute():
        raise HTTPException(status_code=400, detail="Choose a full path to save to.")
    if target.suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="The file must be saved as a .pdf.")
    if not target.parent.is_dir():
        raise HTTPException(status_code=400, detail="That folder does not exist.")

    try:
        shutil.copyfile(pdf_file, target)
    except OSError as e:
        raise HTTPException(status_code=400, detail=f"Could not save there: {e}") from None
    return {"saved": str(target), "bytes": target.stat().st_size}


@router.get("/download/{project_id}")
async def api_download_pdf(project_id: str, download: bool = False):
    """serve the compiled pdf for a project.

    served ``inline`` by default so the preview pane's <iframe> can render it -
    an ``attachment`` disposition makes the browser download the file instead,
    leaving the iframe blank. pass ``?download=1`` for the save-to-disk button.
    """
    try:
        from domain.paper_writer.compiler import ProjectIdError, _get_project_dir
        try:
            pdf_file = _get_project_dir(project_id) / "main.pdf"
        except ProjectIdError:
            raise HTTPException(status_code=404, detail="project not found") from None
        if not pdf_file.exists():
            raise HTTPException(status_code=404, detail="pdf not found. compile first.")
        # Named after the paper, not its id, so it is recognisable later.
        return FileResponse(
            path=str(pdf_file),
            media_type="application/pdf",
            filename=f"{_pdf_name(project_id)}.pdf",
            content_disposition_type="attachment" if download else "inline",
        )
    except HTTPException:
        raise
    except ProjectIdError:
        raise                      # answered as 404 by the handler in main
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/projects/{project_id}")
async def api_delete_project(project_id: str):
    """delete a paper project."""
    if delete_project(project_id):
        return {"status": "deleted", "project_id": project_id}
    raise HTTPException(status_code=404, detail="project not found")
