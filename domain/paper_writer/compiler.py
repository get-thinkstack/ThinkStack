"""
paper writer compiler module.

handles latex compilation to pdf using pdflatex, and manages
the working directory for latex projects on disk.
"""

import logging
import re
import shutil
import subprocess
import uuid
from pathlib import Path

from config import settings

logger = logging.getLogger(__name__)

PAPERS_DIR = settings.data_dir / "papers_workspace"

# if the body uses one of these (left = regex), the package (middle) must be in
# the preamble, plus any extra setup lines (right). this lets us auto-heal
# documents whose preamble is missing a \usepackage the content relies on
# (e.g. AI-generated tikz/pgfplots charts or booktabs tables).
_PACKAGE_RULES = [
    (r"\\begin\{tikzpicture\}|\\usetikzlibrary", "tikz", []),
    (r"\\begin\{axis\}|\\addplot|pgfplots", "pgfplots", [r"\pgfplotsset{compat=1.18}"]),
    (r"\\toprule|\\midrule|\\bottomrule|\\cmidrule", "booktabs", []),
    (r"\\begin\{tabularx\}", "tabularx", []),
    (r"\\multirow", "multirow", []),
    (r"\\includegraphics", "graphicx", []),
    (r"\\(text)?color\b|\\definecolor", "xcolor", []),
    (r"\\href|\\url\b", "hyperref", []),
    (r"\{[^}]*\}\[H\]|\}\[H\]", "float", []),
    # common academic commands that otherwise throw "undefined control sequence"
    (r"\\citep|\\citet|\\citeauthor|\\citeyear", "natbib", []),
    (r"\\SI\b|\\si\b|\\num\b|\\SIrange\b|\\ang\b", "siunitx", []),
    (r"\\bm\b", "bm", []),
    (r"\\enquote\b", "csquotes", []),
    (r"\\begin\{subfigure\}|\\subcaptionbox", "subcaption", []),
    (r"\\mathbb|\\mathfrak|\\mathscr", "amssymb", []),
    (r"\\begin\{enumerate\}\[|\\begin\{itemize\}\[|\\setlist", "enumitem", []),
]

# the standard preamble shared by the starter template and the fragment
# wrapper, so a bare snippet (the AI often returns only body content) still
# compiles into a complete document.
_PREAMBLE = r"""\documentclass[12pt,a4paper]{article}

\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{amsmath,amssymb}
\usepackage{graphicx}
% --- tables ---
\usepackage{booktabs}
\usepackage{tabularx}
\usepackage{array}
\usepackage{multirow}
% --- figures / charts ---
\usepackage{float}
\usepackage{caption}
\usepackage{xcolor}
\usepackage{tikz}
\usepackage{pgfplots}
\pgfplotsset{compat=1.18}
\usetikzlibrary{arrows.meta, positioning, shapes.geometric}
% --- links ---
\usepackage{hyperref}
\usepackage[margin=1in]{geometry}
"""


# shown in place of an environment we could not render, so the rest of the
# document still produces a PDF (overleaf-style graceful degradation). uses only
# core latex primitives so it can never itself fail to compile.
_PLACEHOLDER = (
    "\n\\begin{center}\\fbox{\\parbox{0.7\\linewidth}{\\centering "
    "\\textit{[a figure/table here could not be rendered and was omitted -- "
    "check its LaTeX]}}}\\end{center}\n"
)

# environments worth replacing with a placeholder when they break compilation
# (vs. failing the whole document). ordered so the most likely culprit wins.
_SALVAGE_ENVS = {"tikzpicture", "axis", "pgfplots", "figure", "table"}


def _has_package(preamble: str, pkg: str) -> bool:
    """true if the preamble already loads ``pkg`` (handles grouped imports)."""
    return bool(
        re.search(r"\\usepackage(\[[^\]]*\])?\{[^}]*\b" + re.escape(pkg) + r"\b[^}]*\}", preamble)
    )


def _ensure_packages(source: str) -> str:
    """inject any \\usepackage lines the document body needs but is missing.

    keeps compilation robust when the AI generates charts/tables/figures whose
    packages were never declared (the classic "Environment tikzpicture
    undefined" error).
    """
    doc_start = source.find(r"\begin{document}")
    if doc_start == -1:
        return source  # not a complete document; leave untouched
    preamble = source[:doc_start]

    missing: list[str] = []
    extras: list[str] = []
    for pattern, pkg, extra in _PACKAGE_RULES:
        if re.search(pattern, source) and not _has_package(preamble, pkg):
            missing.append(pkg)
            extras.extend(extra)

    # pgfplots is built on tikz
    if "pgfplots" in missing and "tikz" not in missing and not _has_package(preamble, "tikz"):
        missing.insert(0, "tikz")

    missing = list(dict.fromkeys(missing))
    if not missing:
        return source

    inject = "% --- packages auto-added by thinkstack ---\n"
    inject += "".join(f"\\usepackage{{{p}}}\n" for p in missing)
    inject += "".join(f"{line}\n" for line in dict.fromkeys(extras))

    m = re.search(r"\\documentclass[^\n]*\n", preamble)
    if m:
        return source[: m.end()] + inject + source[m.end():]
    # no documentclass line found; prepend (best effort)
    return inject + source


def _ensure_compilable(source: str) -> str:
    """guarantee the source is a complete, compilable document.

    the AI is instructed to return only body content (no \\documentclass /
    \\begin{document}); if such a fragment is compiled directly you get
    "Environment figure undefined" (no class loaded). here we wrap any bare
    fragment in the standard preamble + document, then ensure packages.
    """
    s = (source or "").strip()
    if "\\documentclass" in s and "\\begin{document}" in s:
        return _ensure_packages(source)  # already a full document

    # extract the body if it is wrapped in document tags without a class,
    # otherwise treat the whole snippet as the body
    body = s
    m = re.search(r"\\begin\{document\}(.*?)\\end\{document\}", s, re.DOTALL)
    if m:
        body = m.group(1).strip()

    wrapped = f"{_PREAMBLE}\n\\begin{{document}}\n\n{body}\n\n\\end{{document}}\n"
    return _ensure_packages(wrapped)


def _ensure_workspace() -> Path:
    """create the papers workspace directory if it doesn't exist."""
    PAPERS_DIR.mkdir(parents=True, exist_ok=True)
    return PAPERS_DIR


def _get_project_dir(project_id: str) -> Path:
    """return the directory for a specific paper project."""
    return _ensure_workspace() / project_id


def create_project(name: str = "untitled") -> dict:
    """create a new paper project with a starter latex template.

    args:
        name: human-readable project name.

    returns:
        dict with project_id, name, and initial latex source.
    """
    project_id = uuid.uuid4().hex[:12]
    project_dir = _get_project_dir(project_id)
    project_dir.mkdir(parents=True, exist_ok=True)

    template = _default_template(name)
    tex_file = project_dir / "main.tex"
    tex_file.write_text(template, encoding="utf-8")

    # persist project metadata
    meta_file = project_dir / "meta.json"
    import json
    meta_file.write_text(json.dumps({
        "project_id": project_id,
        "name": name,
    }), encoding="utf-8")

    return {
        "project_id": project_id,
        "name": name,
        "source": template,
    }


def save_source(project_id: str, source: str) -> dict:
    """save the latex source for a project.

    args:
        project_id: the project identifier.
        source: raw latex source code.

    returns:
        dict confirming the save.
    """
    project_dir = _get_project_dir(project_id)
    if not project_dir.exists():
        raise FileNotFoundError(f"project {project_id} not found")

    tex_file = project_dir / "main.tex"
    tex_file.write_text(source, encoding="utf-8")

    return {"project_id": project_id, "status": "saved"}


def _extract_errors(log_text: str) -> list[str]:
    """pull the meaningful ``! ...`` error blocks out of a pdflatex log.

    each block is the error line plus a few non-blank context lines (which carry
    the ``l.NN`` source line and the offending control sequence), deduplicated.
    """
    lines = log_text.splitlines()
    blocks: list[str] = []
    for i, line in enumerate(lines):
        if line.startswith("!"):
            ctx = [l for l in lines[i:i + 5] if l.strip()]
            blocks.append("\n".join(ctx))
    seen: set[str] = set()
    out: list[str] = []
    for b in blocks:
        if b not in seen:
            seen.add(b)
            out.append(b)
    return out[:4]


def _first_error_line(log_text: str) -> int | None:
    """return the source line number from the first ``l.NN`` marker in the log."""
    m = re.search(r"^l\.(\d+)", log_text, re.MULTILINE)
    return int(m.group(1)) if m else None


def _find_env_spans(source: str) -> list[tuple[str, int, int]]:
    """find balanced ``\\begin{env}...\\end{env}`` spans (handles nesting).

    returns ``(env_name, start_offset, end_offset)`` tuples where end_offset is
    just past the closing ``\\end{env}``.
    """
    spans: list[tuple[str, int, int]] = []
    stack: list[tuple[str, int]] = []
    for m in re.finditer(r"\\(begin|end)\{([^}]+)\}", source):
        kind, env = m.group(1), m.group(2)
        if kind == "begin":
            stack.append((env, m.start()))
        else:
            for i in range(len(stack) - 1, -1, -1):
                if stack[i][0] == env:
                    _, s_start = stack[i]
                    spans.append((env, s_start, m.end()))
                    del stack[i:]
                    break
    return spans


def _salvage_one(source: str, log_text: str) -> tuple[str, str | None]:
    """replace the single broken environment around the error line with a
    placeholder so the rest of the document can compile.

    returns ``(new_source, note)`` where note is None if nothing could be
    localized (so the caller can fall back to a coarser strategy).
    """
    line_no = _first_error_line(log_text)
    if not line_no:
        return source, None
    lines = source.splitlines(keepends=True)
    idx = line_no - 1
    if idx < 0 or idx >= len(lines):
        return source, None
    err_pos = sum(len(l) for l in lines[:idx])  # char offset of the error line

    enclosing = [
        (env, s, e) for (env, s, e) in _find_env_spans(source)
        if env in _SALVAGE_ENVS and s <= err_pos <= e
    ]
    if not enclosing:
        return source, None
    # innermost enclosing env = the one whose \begin is closest before the error
    env, s, e = max(enclosing, key=lambda t: t[1])
    new_source = source[:s] + _PLACEHOLDER + source[e:]
    note = (
        f"the '{env}' block near line {line_no} could not be rendered "
        "and was replaced with a placeholder"
    )
    return new_source, note


def _neutralize_all_figures(source: str) -> tuple[str, str | None]:
    """last resort: replace every tikz/pgfplots picture with a placeholder.

    used only when no PDF can be produced and the failing environment could not
    be localized, so at least the document's text renders.
    """
    new = source
    total = 0
    for env in ("tikzpicture", "axis"):
        pattern = re.compile(
            r"\\begin\{" + env + r"\}.*?\\end\{" + env + r"\}", re.DOTALL
        )
        new, count = pattern.subn(_PLACEHOLDER, new)
        total += count
    if total == 0:
        return source, None
    return new, f"{total} figure(s) could not be rendered and were replaced with placeholders"


def _run_pdflatex(pdflatex: str, tex_file: Path, project_dir: Path):
    """run a single non-interactive pdflatex pass.

    note: there is intentionally NO ``-halt-on-error``. in nonstopmode pdflatex
    recovers from most errors and still ships a PDF (overleaf behaviour); we then
    treat "a PDF exists" as success and surface the errors as warnings.
    """
    return subprocess.run(
        [
            pdflatex,
            "-interaction=nonstopmode",
            "-output-directory", str(project_dir),
            str(tex_file),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(project_dir),
    )


def compile_pdf(project_id: str) -> tuple[Path, list[str]]:
    """compile the project's main.tex into a pdf, overleaf-style.

    compiles in non-interactive mode WITHOUT halting on the first error, so a
    single broken figure/table no longer prevents a PDF. if a PDF is produced,
    any errors pdflatex recovered from are returned as warnings. only if no PDF
    can be produced at all do we surgically replace the offending environment
    with a placeholder and retry; failing that, raise.

    args:
        project_id: the project identifier.

    returns:
        ``(pdf_path, warnings)`` -- the generated pdf and a list of human-readable
        warning strings (empty on a fully clean compile).

    raises:
        FileNotFoundError: if the project doesn't exist.
        RuntimeError: if pdflatex is not installed or no PDF could be produced.
    """
    project_dir = _get_project_dir(project_id)
    tex_file = project_dir / "main.tex"
    log_file = project_dir / "main.log"
    pdf_path = project_dir / "main.pdf"

    if not tex_file.exists():
        raise FileNotFoundError(f"project {project_id} has no main.tex")

    # auto-heal: wrap bare fragments + declare any packages the body relies on
    # (fixes "Environment tikzpicture undefined" and similar).
    try:
        source = tex_file.read_text(encoding="utf-8")
        fixed = _ensure_compilable(source)
        if fixed != source:
            tex_file.write_text(fixed, encoding="utf-8")
            logger.info("auto-wrapped / healed latex for %s", project_id)
    except Exception as e:  # noqa: BLE001 - best-effort, never block compile
        logger.warning("latex auto-heal skipped: %s", e)

    pdflatex = shutil.which("pdflatex")
    if not pdflatex:
        raise RuntimeError(
            "pdflatex is not installed. install texlive-latex-base or equivalent."
        )

    # remove any stale pdf so "pdf exists" reliably means "this run produced one"
    try:
        pdf_path.unlink(missing_ok=True)
    except OSError:
        pass

    warnings: list[str] = []
    result = None
    MAX_SALVAGE = 4

    # try to produce a PDF; if a pass yields none, salvage the broken env + retry
    for _ in range(MAX_SALVAGE + 1):
        result = _run_pdflatex(pdflatex, tex_file, project_dir)
        if pdf_path.exists():
            break

        log_text = log_file.read_text(encoding="utf-8", errors="replace") if log_file.exists() else ""
        source = tex_file.read_text(encoding="utf-8")
        new_source, note = _salvage_one(source, log_text)
        if note is None:
            new_source, note = _neutralize_all_figures(source)
        if note is None:
            # can't localize and nothing to neutralize -> genuine hard failure
            errors = _extract_errors(log_text)
            detail = "\n\n".join(errors) if errors else (result.stdout or "")[-1500:]
            raise RuntimeError(f"pdflatex failed:\n{detail}")
        tex_file.write_text(new_source, encoding="utf-8")
        warnings.append(note)
    else:
        # exhausted retries without ever producing a PDF
        log_text = log_file.read_text(encoding="utf-8", errors="replace") if log_file.exists() else ""
        errors = _extract_errors(log_text)
        detail = "\n\n".join(errors) if errors else (result.stdout if result else "")[-1500:]
        raise RuntimeError(f"pdflatex failed to produce a PDF:\n{detail}")

    # second pass for cross-references / toc (best effort; PDF already exists)
    try:
        _run_pdflatex(pdflatex, tex_file, project_dir)
    except Exception as e:  # noqa: BLE001
        logger.warning("pdflatex reference pass skipped: %s", e)

    # surface any errors pdflatex recovered from as warnings (overleaf-style)
    if log_file.exists():
        recovered = _extract_errors(log_file.read_text(encoding="utf-8", errors="replace"))
        for err in recovered:
            if err not in warnings:
                warnings.append(err)

    if not pdf_path.exists():
        raise RuntimeError("pdflatex completed but no pdf was generated")

    return pdf_path, warnings


def list_projects() -> list[dict]:
    """list all paper projects.

    returns:
        list of project metadata dicts.
    """
    import json
    workspace = _ensure_workspace()
    projects = []

    for child in sorted(workspace.iterdir()):
        if not child.is_dir():
            continue
        meta_file = child / "meta.json"
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                meta["has_pdf"] = (child / "main.pdf").exists()
                projects.append(meta)
            except Exception:
                continue

    return projects


def get_source(project_id: str) -> str:
    """read the latex source for a project.

    args:
        project_id: the project identifier.

    returns:
        the latex source string.
    """
    tex_file = _get_project_dir(project_id) / "main.tex"
    if not tex_file.exists():
        raise FileNotFoundError(f"project {project_id} not found")
    return tex_file.read_text(encoding="utf-8")


def delete_project(project_id: str) -> bool:
    """delete a paper project and all its files.

    args:
        project_id: the project identifier.

    returns:
        true if the project was deleted.
    """
    project_dir = _get_project_dir(project_id)
    if project_dir.exists():
        shutil.rmtree(project_dir)
        return True
    return False


def _default_template(title: str) -> str:
    """return a minimal academic paper latex template."""
    safe_title = title.replace("_", r"\_").replace("&", r"\&")
    return _PREAMBLE + rf"""
\title{{{safe_title}}}
\author{{author name}}
\date{{\today}}

\begin{{document}}

\maketitle

\begin{{abstract}}
% write your abstract here
\end{{abstract}}

\section{{introduction}}

% start writing here

\section{{methodology}}

\section{{results}}

\section{{conclusion}}

\bibliographystyle{{plain}}
\bibliography{{references}}

\end{{document}}
"""
