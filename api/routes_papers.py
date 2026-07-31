"""
paper writer api routes.

provides endpoints for creating, editing, ai-generating, compiling,
and managing latex paper projects.
"""

import logging
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from domain.paper_writer.compiler import (
    create_project,
    save_source,
    compile_pdf,
    list_projects,
    get_source,
    delete_project,
)
from domain.chat.chat_service import _build_context
from domain.fine_tuning.data_collector import save_latex_pair
from infrastructure.ollama_client import ollama_client

logger = logging.getLogger(__name__)
router = APIRouter()



# How much of the document to show the model. 6000 characters is roughly 1500
# tokens, which leaves room for the system prompt, any grounding context, and
# the 2048-token output budget.
_CONTEXT_BUDGET = 6000


def _build_edit_prompt(source: str, request: str, cursor: int | None) -> str:
    """Show the model the document it is editing, centred on where the author is.

    The document is presented as: its preamble (so the model knows which
    packages are already loaded and does not redeclare them), then the text
    immediately before the cursor, an explicit insertion marker, and the text
    immediately after. The model is asked for the fragment that belongs at the
    marker and nothing else.

    This replaces sending the first 6000 characters of the file, which on a real
    paper is the preamble and introduction. The model never saw the section
    being worked on, so it wrote as if beginning a new document and repeated
    structure that already existed.
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
    """Remove document text the model copied back instead of only writing new content.

    Asked to write a table into an existing paper, a 1.5B model reproduces the
    surrounding section headings and prose and then appends the table. Inserting
    that verbatim duplicates whole sections, which is what made the feature feel
    like it appends rather than edits.

    Instructing the model not to do this is unreliable, so the overlap is
    removed deterministically: the longest tail of the preceding text that the
    output starts with is dropped, and likewise the longest head of the
    following text that it ends with. What remains is what the model actually
    added.

    A fine-tuned writer model is the real answer; this makes the feature
    dependable in the meantime.
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
    """Reduce the model's reply to body content that can be dropped into a document.

    The system prompt tells the model to emit body content only, with no
    preamble. A small model does not always comply, and when it does not the
    result is a second \\documentclass and a second preamble injected into the
    middle of the user's paper, which breaks the template it was supposed to be
    writing into. Stripping here rather than trusting the instruction is the
    difference between an edit and a mess.
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


class SaveSourceRequest(BaseModel):
    project_id: str
    source: str


class GenerateLatexRequest(BaseModel):
    project_id: str
    prompt: str
    current_source: str = ""
    # Where the author is working. Without it the model was shown the first
    # 6000 characters of the document, which on any real paper is the preamble
    # and introduction, never the place being edited. It then wrote as though
    # starting a fresh document and repeated sections that already existed.
    cursor: int | None = None
    doc_ids: list[str] = []          # papers to ground the writing on (rag)
    analysis_context: str = ""       # optional analysis findings to incorporate


class CompileRequest(BaseModel):
    project_id: str


@router.post("/projects")
async def api_create_project(req: CreateProjectRequest):
    """create a new paper project with a starter template."""
    try:
        return create_project(req.name)
    except Exception as e:
        logger.error("failed to create project: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects")
async def api_list_projects():
    """list all paper projects."""
    return {"projects": list_projects()}


@router.get("/projects/{project_id}")
async def api_get_project(project_id: str):
    """get the latex source for a project."""
    try:
        source = get_source(project_id)
        return {"project_id": project_id, "source": source}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="project not found")


@router.post("/save")
async def api_save_source(req: SaveSourceRequest):
    """save updated latex source."""
    try:
        return save_source(req.project_id, req.source)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="project not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate")
async def api_generate_latex(req: GenerateLatexRequest):
    """use the local llm to convert a prompt into latex code.

    the prompt can be pseudocode, natural language instructions, or
    partial latex that needs completion. the ai returns compilable
    latex that can be inserted into the document.
    """
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
            context_text, _ = _build_context(req.prompt, req.doc_ids)
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
    except Exception as e:
        logger.error("compilation failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/download/{project_id}")
async def api_download_pdf(project_id: str, download: bool = False):
    """serve the compiled pdf for a project.

    served ``inline`` by default so the preview pane's <iframe> can render it -
    an ``attachment`` disposition makes the browser download the file instead,
    leaving the iframe blank. pass ``?download=1`` for the save-to-disk button.
    """
    try:
        from domain.paper_writer.compiler import _get_project_dir
        pdf_file = _get_project_dir(project_id) / "main.pdf"
        if not pdf_file.exists():
            raise HTTPException(status_code=404, detail="pdf not found. compile first.")
        return FileResponse(
            path=str(pdf_file),
            media_type="application/pdf",
            filename=f"{project_id}.pdf",
            content_disposition_type="attachment" if download else "inline",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/projects/{project_id}")
async def api_delete_project(project_id: str):
    """delete a paper project."""
    if delete_project(project_id):
        return {"status": "deleted", "project_id": project_id}
    raise HTTPException(status_code=404, detail="project not found")
