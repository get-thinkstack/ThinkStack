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
from infrastructure.ollama_client import ollama_client

logger = logging.getLogger(__name__)
router = APIRouter()


def _clean_latex(text: str) -> str:
    """strip markdown fences / stray wrapping the model may add around latex."""
    t = (text or "").strip()
    fence = re.search(r"```(?:latex|tex)?\s*(.*?)```", t, re.DOTALL)
    if fence:
        t = fence.group(1).strip()
    return t.replace("```latex", "").replace("```tex", "").replace("```", "").strip()


class CreateProjectRequest(BaseModel):
    name: str = "untitled"


class SaveSourceRequest(BaseModel):
    project_id: str
    source: str


class GenerateLatexRequest(BaseModel):
    project_id: str
    prompt: str
    current_source: str = ""
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
        "\\begin{document}, or \\end{document} — just the body content. "
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
        "those listed. the snippet must compile on its own."
    )

    # optional grounding: relevant excerpts from selected papers + analysis
    grounding_parts: list[str] = []
    if req.doc_ids:
        try:
            context_text, _ = _build_context(req.prompt, req.doc_ids)
            if context_text:
                grounding_parts.append(
                    "relevant excerpts from the user's selected papers — "
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
        prompt = (
            f"here is the current document source for context:\n"
            f"```\n{req.current_source}\n```\n\n"
            f"now generate latex for this request:\n{req.prompt}"
        )
    if grounding_parts:
        prompt = "\n\n".join(grounding_parts) + "\n\n" + prompt

    try:
        latex_output = await ollama_client.generate(
            prompt=prompt,
            system=system,
            temperature=0.2,
            max_tokens=2048,
        )
        return {
            "project_id": req.project_id,
            "generated_latex": _clean_latex(latex_output),
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
async def api_download_pdf(project_id: str):
    """download the compiled pdf for a project."""
    try:
        pdf_path = compile_pdf.__wrapped__ if hasattr(compile_pdf, '__wrapped__') else None
        # just build the path directly
        from domain.paper_writer.compiler import _get_project_dir
        pdf_file = _get_project_dir(project_id) / "main.pdf"
        if not pdf_file.exists():
            raise HTTPException(status_code=404, detail="pdf not found. compile first.")
        return FileResponse(
            path=str(pdf_file),
            media_type="application/pdf",
            filename=f"{project_id}.pdf",
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
