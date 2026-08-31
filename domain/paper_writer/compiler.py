"""
paper writer compiler module.

handles latex compilation to pdf using pdflatex, and manages
the working directory for latex projects on disk.
"""

import logging
import os
import re
import shutil
import sys
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


_CITE_RE = re.compile(r"\\(?:no)?cite[a-zA-Z]*\s*(?:\[[^\]]*\])*\s*\{")


def _ensure_bibliography(source: str, project_dir: Path) -> str:
    """Give a citing document somewhere to print its references.

    `\\cite{key}` on its own resolves to `[?]` and prints no reference list.
    BibTeX is only invoked at all because `\\bibliography` puts a `\\bibdata`
    line in the .aux, and the entries are only typeset because that command is
    also where the list goes. A document with citations and no bibliography is
    not a style choice, it is the citation silently not working -- which is
    exactly what it looked like.

    Added at the end of the body, before `\\end{document}`, which is where a
    reference list belongs and where the template already put it.

    Only when the project actually has a references.bib. Pointing
    `\\bibliography` at a file that is not there turns a working compile into
    a failed one, and an author who has typed `\\cite` by hand without ever
    using the picker has no such file.
    """
    if not _CITE_RE.search(source):
        return source
    if "\\bibliography" in source or "\\begin{thebibliography}" in source:
        return source
    if not (Path(project_dir) / "references.bib").is_file():
        return source

    end = source.rfind(r"\end{document}")
    if end == -1:
        return source

    block = (
        "\n% --- bibliography auto-added by thinkstack ---\n"
        "\\bibliographystyle{plain}\n"
        "\\bibliography{references}\n\n"
    )
    return source[:end] + block + source[end:]


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


# ── tables the model got wrong ───────────────────────────────────────────
#
# A tabular declares its columns once and then every row has to agree. A model
# writing one from a prompt loses count, and TeX answers with
#
#     ! Extra alignment tab has been changed to \cr
#
# which names a line and says nothing a person who did not write LaTeX can act
# on. A tester on Windows hit exactly this. The engine was right and the
# document was wrong; `_ensure_packages` can declare a missing package but has
# no opinion about arithmetic.
#
# Counting is the whole fix, and it is worth doing HERE rather than by prompting
# more carefully: a grammar or a better instruction makes the mistake rarer,
# while counting makes it impossible to reach the engine.

# The column specification, reduced to the letters that consume a cell. Anything
# in @{...}, !{...} or >{...} is material between columns, not a column, and a
# p/m/b takes a width argument that must not be read as more columns.
_COLSPEC_NOISE = re.compile(r"[@!>]\{(?:[^{}]|\{[^{}]*\})*\}")
# siunitx writes S[table-format=2.1]; the bracket is an option, not six columns.
_COLSPEC_OPTION = re.compile(r"\[[^\]]*\]")
_COLSPEC_SIZED = re.compile(r"[pmb]\{(?:[^{}]|\{[^{}]*\})*\}")
_COLSPEC_STAR = re.compile(r"\*\{(\d+)\}\{([^{}]*)\}")


def _count_columns(spec: str) -> int:
    """How many cells one row of this tabular is allowed to have."""
    # *{3}{c} means three of them; expand before anything else counts letters.
    while True:
        m = _COLSPEC_STAR.search(spec)
        if not m:
            break
        spec = spec[:m.start()] + m.group(2) * int(m.group(1)) + spec[m.end():]
    spec = _COLSPEC_NOISE.sub("", spec)
    spec = _COLSPEC_OPTION.sub("", spec)
    spec = _COLSPEC_SIZED.sub("X", spec)      # one column each, width consumed
    return sum(1 for ch in spec if ch in "lcrXsSY")


def _cells_in_row(row: str) -> int:
    r"""Cells in one row, counting only ampersands TeX would treat as separators.

    An escaped \& is text -- a column headed "R&D" is not two columns -- and a
    \multicolumn{n}{...}{...} occupies n of them while carrying one separator.
    """
    body = re.sub(r"\\&", "", row)                 # \& is a literal ampersand
    body = re.sub(r"%.*", "", body)                # a comment cannot hold a cell
    cells = 1 + body.count("&")
    for n in re.findall(r"\\multicolumn\s*\{\s*(\d+)\s*\}", body):
        cells += int(n) - 1                        # it spans n, was counted once
    return cells


def _check_tables(source: str) -> list[str]:
    r"""Rows whose cell count disagrees with their tabular's declaration.

    Reported rather than repaired. Padding a short row with `&` would put empty
    cells into a table an author believes is finished, and truncating a long one
    silently deletes their data -- both are worse than being told which line is
    wrong while the rest of the document still compiles.
    """
    problems: list[str] = []
    pattern = re.compile(
        r"\\begin\{(tabular\*?|array|longtable)\}\s*(?:\[[^\]]*\])?\s*"
        r"(?:\{[^{}]*\}\s*)??\{((?:[^{}]|\{[^{}]*\})*)\}",
    )
    for m in pattern.finditer(source):
        env, spec = m.group(1), m.group(2)
        declared = _count_columns(spec)
        if declared < 1:
            continue
        end = source.find(rf"\end{{{env}}}", m.end())
        body = source[m.end():end if end != -1 else len(source)]
        line_of_start = source.count("\n", 0, m.end()) + 1
        # Newlines BEFORE each row, accumulated as we walk -- counting the ones
        # inside the current row put every message one line early.
        consumed = 0
        for row in body.split(r"\\"):
            stripped = re.sub(r"\\(hline|toprule|midrule|bottomrule|cmidrule)"
                              r"(\([^)]*\))?(\{[^}]*\})?", "", row).strip()
            found = _cells_in_row(stripped) if stripped else 0
            if stripped and found > declared:
                # A chunk runs from one row separator to the next, so it may
                # open with a rule on its own line. The cells are on the chunk's
                # LAST line, which is where a reader will look.
                line = line_of_start + consumed + row.count("\n")
                problems.append(
                    f"A row near line {line} has {found} cells but the table "
                    f"declares {declared} column{'s' if declared != 1 else ''}."
                )
            consumed += row.count("\n")
    return problems


def _ensure_workspace() -> Path:
    """create the papers workspace directory if it doesn't exist."""
    PAPERS_DIR.mkdir(parents=True, exist_ok=True)
    return PAPERS_DIR


# A project id is one path segment, never a path. Ids are uuid4 hex, but two
# early projects were named by hand ("texbundle", "tex015"), so this admits any
# ordinary name rather than only hex -- and admits nothing that can leave the
# directory it is joined to.
_PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class ProjectIdError(ValueError):
    """The project id was not a name this module will join to a path."""


def _get_project_dir(project_id: str) -> Path:
    """Return the directory for a project, or refuse the id.

    THE boundary for project ids, and the only place that joins one to a path.
    Twenty-seven call sites reach the filesystem through here, so validating at
    the join is what makes all of them safe at once; validating at each caller
    would be twenty-seven chances to forget.

    It was missing, and the consequence was not theoretical: `_project()` in the
    routes only checked `is_dir()`, so an id of "../../../../etc" resolved to a
    real directory, passed that check, and let `list_files` enumerate it and
    `read_file` return /etc/passwd. The webview can reach this API, so a project
    id is untrusted input in exactly the sense a filename is.

    Two checks, deliberately. The pattern refuses separators and traversal
    before any filesystem call. The containment check then resolves and confirms
    the result is still inside the workspace, which is what catches a symlink --
    a string test cannot see that `mine` is a link to `/`.
    """
    if project_id is None:
        raise ProjectIdError("No project was named.")
    text = str(project_id).strip()
    if not _PROJECT_ID_RE.match(text) or text in (".", ".."):
        raise ProjectIdError(f"{project_id!r} is not a valid project id.")

    root = _ensure_workspace().resolve()
    target = (root / text).resolve()
    if target != root and root not in target.parents:
        raise ProjectIdError(f"{project_id!r} is not a valid project id.")
    return root / text


def create_project(name: str = "untitled", template: str | None = None) -> dict:
    """Create a project from a starter document.

    `template` names one of `domain.paper_writer.templates`; omitting it gives
    the research paper, which is what most people here are writing. It is an
    argument rather than a fixed shape because Scribe is a LaTeX editor that
    happens to live inside a research application -- a letter or a CV is a
    perfectly good reason to open it, and the paper template's abstract and
    methodology sections are noise for both.

    args:
        name: human-readable project name.
        template: which starter to use; unknown ids fall back to the paper.

    returns:
        dict with project_id, name, template and initial latex source.
    """
    from domain.paper_writer import templates as _templates

    project_id = uuid.uuid4().hex[:12]
    project_dir = _get_project_dir(project_id)
    project_dir.mkdir(parents=True, exist_ok=True)

    chosen = _templates.get(template)
    template_text = _templates.render(chosen.id, name)
    tex_file = project_dir / "main.tex"
    tex_file.write_text(template_text, encoding="utf-8")

    # persist project metadata
    meta_file = project_dir / "meta.json"
    import json
    meta_file.write_text(json.dumps({
        "project_id": project_id,
        "name": name,
        "template": chosen.id,
    }), encoding="utf-8")

    return {
        "project_id": project_id,
        "name": name,
        "template": chosen.id,
        "source": template_text,
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


def _tex_install_hint() -> str:
    """The install command for THIS machine's OS.

    We printed `sudo dnf install texlive-...` to every user on every platform,
    so a macOS tester chasing a missing package was handed a Fedora command.
    Advice written by a Linux developer must not be shown to everyone.
    """
    if sys.platform == "darwin":
        return "brew install --cask mactex-no-gui"
    if sys.platform.startswith("win"):
        return "install MiKTeX from https://miktex.org"
    return ("sudo dnf install texlive-scheme-basic  (fedora) or "
            "sudo apt install texlive-latex-recommended  (debian/ubuntu)")


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


def _detect_missing_packages(log_text: str) -> list[str]:
    """detect 'File X.sty not found' errors and return install hints.

    these happen when the TeX distribution is missing packages that our
    preamble or the AI-generated content needs (e.g. pgfplots, multirow).
    """
    missing = re.findall(r"File `([^']+\.sty)' not found", log_text)
    if not missing:
        return []
    hints = []
    for sty in dict.fromkeys(missing):  # deduplicate
        pkg = sty.replace(".sty", "")
        hints.append(
            f"missing TeX package: {sty} ({pkg}) - "
            f"install a fuller TeX distribution: {_tex_install_hint()}"
        )
    return hints


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
        # replacement must be a function, not a string: _PLACEHOLDER is latex full
        # of backslash sequences (\parbox, \fbox, ...) and re.sub would try to
        # interpret them as group escapes ("bad escape \p"), crashing the very
        # last-resort salvage that is meant to guarantee a PDF.
        new, count = pattern.subn(lambda _m: _PLACEHOLDER, new)
        total += count
    if total == 0:
        return source, None
    return new, f"{total} figure(s) could not be rendered and were replaced with placeholders"


def _find_engine() -> tuple[str, str] | None:
    """Locate a TeX engine: bundled Tectonic first, then anything on PATH.

    The bundled copy is preferred so a packaged install compiles with no LaTeX
    on the machine. Requiring users to install MacTeX or MiKTeX made the
    flagship feature fail on every clean machine, which is not a documentation
    problem -- it is a missing dependency.

    returns (executable_path, kind) where kind is "tectonic" or "pdflatex".
    """
    exe = "tectonic.exe" if sys.platform.startswith("win") else "tectonic"
    bundled = settings.bundled_tex_dir / exe
    if bundled.is_file():
        return str(bundled), "tectonic"
    found = shutil.which("tectonic")
    if found:
        return found, "tectonic"
    found = shutil.which("pdflatex")
    if found:
        return found, "pdflatex"
    return None


def _link_search_paths(project_dir: Path) -> list[Path]:
    """Directories a compile should look in besides the project itself.

    A link records where a file IS rather than taking a copy. Until this
    existed that was bookkeeping and nothing more: Tectonic runs with the
    project as its working directory, so a linked figure was invisible to the
    compile and `\includegraphics{chart.png}` failed on a file the panel
    listed as present. The only thing that worked was typing an absolute path,
    which works whether or not the file was ever linked and breaks the moment
    it moves -- which is the exact thing linking exists to survive.

    A linked FILE contributes its parent; a linked FOLDER contributes itself,
    which is what makes a shared `figures/` directory work.

    Failures here are not the compile's problem. A missing link is already
    reported in the panel, and a compile that refused to start because one of
    several linked files had moved would be a worse answer than one that runs
    and reports what it could not find.
    """
    from domain.paper_writer import links as _links

    out: list[Path] = []
    try:
        resolved = _links.list_links(project_dir)
    except Exception as e:  # noqa: BLE001 - never block a compile on this
        logger.warning("could not read links for the search path: %s", e)
        return out

    for r in resolved:
        if r.status == "missing" or r.resolved is None:
            continue
        d = r.resolved if r.link.kind == "dir" else r.resolved.parent
        try:
            d = d.resolve()
        except OSError:
            continue
        if d.is_dir() and d not in out:
            out.append(d)
    return out


def _tectonic_env() -> dict:
    """Environment for Tectonic, pointing it at a writable, pre-warmed cache.

    The cache we ship holds every package the writer's preamble uses, so a
    compile needs no network. Tectonic writes to its cache, and the bundle is
    read-only, so the shipped copy is seeded into the user's data dir once --
    the same approach used for the gguf models.
    """
    env = dict(os.environ)
    cache = settings.tex_cache_dir
    try:
        seed = settings.bundled_tex_dir / "cache"
        seed_marker = cache / ".thinkstack-bundled-cache-seeded"
        if seed.is_dir() and not seed_marker.exists():
            # The application or an installer may create the state directory
            # before the first compile.  `cache.exists()` is therefore not a
            # reliable indication that its bundled package data was copied.
            shutil.copytree(seed, cache, dirs_exist_ok=True)
            seed_marker.write_text("1\n", encoding="utf-8")
            logger.info("seeded bundled TeX cache into %s", cache)
        cache.mkdir(parents=True, exist_ok=True)
        env["TECTONIC_CACHE_DIR"] = str(cache)
    except OSError as e:  # noqa: BLE001 - fall back to tectonic's own default
        logger.warning("could not prepare the TeX cache: %s", e)
    return env


def _run_engine(engine: str, kind: str, tex_file: Path, project_dir: Path):
    """Run one compile pass with whichever engine we found.

    Both engines are asked to keep going after errors rather than halting:
    a document that is mid-edit usually still produces a usable PDF, and
    "a PDF exists" is what we treat as success (overleaf behaviour), with the
    errors surfaced as warnings.
    """
    search = _link_search_paths(project_dir)

    if kind == "tectonic":
        # -Z search-path, NOT TEXINPUTS. Tectonic has its own IO layer and
        # ignores the environment variable outright -- verified against the
        # bundled 0.15.0: with TEXINPUTS set it still reports "Unable to load
        # picture or PDF file" and writes no PDF, and with -Z search-path the
        # same document compiles. The flag covers \input, \includegraphics
        # and \bibliography alike, because BibTeX runs inside Tectonic's own
        # multi-pass build and inherits it.
        cmd = [
            engine, "-X", "compile", str(tex_file),
            "--outdir", str(project_dir),
            "--keep-logs", "--synctex",
            "-Z", "continue-on-errors",
        ]
        for d in search:
            cmd += ["-Z", f"search-path={d}"]
        return subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=180,
            cwd=str(project_dir), env=_tectonic_env(),
        )

    # pdflatex is the fallback engine and is the one that DOES read TEXINPUTS.
    # The trailing empty entry is load-bearing: without it this replaces the
    # default search path instead of extending it, and the document loses the
    # standard classes and packages rather than gaining a figure.
    env = dict(os.environ)
    if search:
        env["TEXINPUTS"] = "".join(f"{d}:" for d in search) + os.environ.get("TEXINPUTS", "")
    return subprocess.run(
        [
            engine,
            "-interaction=nonstopmode",
            "-output-directory", str(project_dir),
            str(tex_file),
        ],
        capture_output=True, text=True, timeout=60, cwd=str(project_dir), env=env,
    )


def _needs_bibtex_pass(project_dir: Path, tex_file: Path, kind: str) -> bool:
    """Resolve citations if the engine will not do it itself. True if it ran.

    Tectonic drives BibTeX as part of its own multi-pass build, so the bundled
    engine needs nothing here. pdflatex does not: it writes `\\citation{...}`
    into the .aux and stops, and every citation in the PDF renders as `[?]`
    with the bibliography missing entirely. That is the state a machine
    running from source is in, which is every developer's machine.

    Driven off the .aux rather than off the source, because that is what
    BibTeX itself reads -- a `\\cite` inside a commented-out paragraph is in
    the source and not in the .aux.
    """
    if kind == "tectonic":
        return False

    aux = project_dir / f"{tex_file.stem}.aux"
    try:
        if "\\citation{" not in aux.read_text(encoding="utf-8", errors="replace"):
            return False
    except OSError:
        return False

    bibtex = shutil.which("bibtex")
    if not bibtex:
        logger.warning("bibtex is not installed; citations will render as [?]")
        return False

    # Only reached on the fallback engine -- Tectonic drives BibTeX itself and
    # passes its own search path down. Standalone bibtex reads BIBINPUTS, not
    # TEXINPUTS, so a linked .bib needs this or every citation renders as [?].
    env = dict(os.environ)
    search = _link_search_paths(project_dir)
    if search:
        env["BIBINPUTS"] = "".join(f"{d}:" for d in search) + os.environ.get("BIBINPUTS", "")

    try:
        subprocess.run(
            [bibtex, tex_file.stem],
            capture_output=True, text=True, timeout=60, cwd=str(project_dir), env=env,
        )
    except (OSError, subprocess.SubprocessError) as e:
        # A missing bibliography must not cost the author their PDF.
        logger.warning("bibtex pass failed: %s", e)
        return False
    return True


def _needs_index_pass(project_dir: Path, tex_file: Path) -> bool:
    """build the .ind if the document asked for an index. True if it changed.

    Only when the source actually uses \\printindex: writing an .ind beside a
    document that never reads it is harmless but pointless, and the extra engine
    pass it triggers is not -- a real TeX run on a long paper is seconds.
    """
    try:
        if "\\printindex" not in tex_file.read_text(encoding="utf-8", errors="replace"):
            return False
        from domain.paper_writer.indexing import write_index
        before = (project_dir / f"{tex_file.stem}.ind")
        previous = before.read_text(encoding="utf-8") if before.exists() else None
        if not write_index(project_dir, tex_file.stem):
            return False
        # a second pass is only worth it when the index actually changed
        return before.read_text(encoding="utf-8") != previous
    except Exception as e:  # noqa: BLE001 - an index must never lose the PDF
        logger.warning("index generation skipped: %s", e)
        return False


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

    # Tables the model miscounted, checked BEFORE the engine sees them.
    #
    # These are reported, never repaired. Padding a short row puts empty cells
    # into a table the author believes is finished; truncating a long one
    # deletes their data. Both are worse than a sentence naming the line, which
    # is what the engine could not give them: "! Extra alignment tab has been
    # changed to \cr" names a line and nothing a person who did not write LaTeX
    # can act on.
    table_warnings: list[str] = []
    try:
        table_warnings = _check_tables(tex_file.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001 - a checker must never block a compile
        logger.warning("table check skipped: %s", e)

    # auto-heal: wrap bare fragments + declare any packages the body relies on
    # (fixes "Environment tikzpicture undefined" and similar).
    try:
        source = tex_file.read_text(encoding="utf-8")
        fixed = _ensure_bibliography(_ensure_compilable(source), project_dir)
        if fixed != source:
            tex_file.write_text(fixed, encoding="utf-8")
            logger.info("auto-wrapped / healed latex for %s", project_id)
    except Exception as e:  # noqa: BLE001 - best-effort, never block compile
        logger.warning("latex auto-heal skipped: %s", e)

    found = _find_engine()
    if not found:
        raise RuntimeError(
            "No TeX engine found, so the PDF cannot be compiled. This build "
            "should ship one -- if you are running from source, install a TeX "
            f"distribution to enable PDF export: {_tex_install_hint()}"
        )
    engine, kind = found
    logger.info("compiling with %s (%s)", kind, engine)

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
        result = _run_engine(engine, kind, tex_file, project_dir)
        if pdf_path.exists():
            # An index is a two-pass affair: the first run writes .idx, something
            # has to turn that into .ind, and only then can \printindex read it.
            # Tectonic runs BibTeX by itself but not makeindex, so without this
            # a paper using \index compiled to "Undefined control sequence
            # \indexentry" -- imakeidx falling back to \input-ing the raw .idx.
            # Generated in Python rather than shelled out to makeindex, which is
            # not in the bundle and would put us back to needing a TeX install.
            # BibTeX before the index: it rewrites the .aux, and \printindex
            # reads what the pass after that leaves behind.
            if _needs_bibtex_pass(project_dir, tex_file, kind):
                _run_engine(engine, kind, tex_file, project_dir)
            if _needs_index_pass(project_dir, tex_file):
                _run_engine(engine, kind, tex_file, project_dir)
            break

        log_text = log_file.read_text(encoding="utf-8", errors="replace") if log_file.exists() else ""
        source = tex_file.read_text(encoding="utf-8")
        new_source, note = _salvage_one(source, log_text)
        if note is None:
            new_source, note = _neutralize_all_figures(source)
        if note is None:
            # can't localize and nothing to neutralize -> genuine hard failure
            errors = _extract_errors(log_text)
            pkg_hints = _detect_missing_packages(log_text)
            detail = "\n\n".join(pkg_hints + errors) if (pkg_hints or errors) else (result.stdout or "")[-1500:]
            raise RuntimeError(f"{kind} failed:\n{detail}")
        tex_file.write_text(new_source, encoding="utf-8")
        warnings.append(note)
    else:
        # exhausted retries without ever producing a PDF
        log_text = log_file.read_text(encoding="utf-8", errors="replace") if log_file.exists() else ""
        errors = _extract_errors(log_text)
        pkg_hints = _detect_missing_packages(log_text)
        detail = "\n\n".join(pkg_hints + errors) if (pkg_hints or errors) else (result.stdout if result else "")[-1500:]
        raise RuntimeError(f"{kind} failed to produce a PDF:\n{detail}")

    # second pass for cross-references / toc (best effort; PDF already exists)
    try:
        _run_engine(engine, kind, tex_file, project_dir)
    except Exception as e:  # noqa: BLE001
        logger.warning("%s reference pass skipped: %s", kind, e)

    # The table warnings go FIRST. They are the ones written for a person, and
    # they explain the engine errors that follow rather than competing with
    # them -- a reader who sees "row 4 has 7 cells, the table declares 3" does
    # not need to decode "Extra alignment tab" underneath it.
    for w in table_warnings:
        if w not in warnings:
            warnings.insert(0, w)

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
    """Every paper project, newest work first.

    Ordered by when `main.tex` was last written, because that is what a person
    means by "the one I was working on". It used to come back in whatever order
    the filesystem listed the directories -- effectively creation order, which
    puts the paper you touched a minute ago wherever it happens to fall among
    two dozen others. With seven projects named `bundle-validation` and four
    named `untitled`, finding one was a visual scan of near-identical rows.

    `modified` is carried so the interface can say *when* rather than only
    imply it by position, and `name_lower` so sorting by name does not put
    `Zebra` above `apple`.
    """
    import json
    workspace = _ensure_workspace()
    projects = []

    for child in workspace.iterdir():
        if not child.is_dir():
            continue
        meta_file = child / "meta.json"
        if not meta_file.exists():
            continue
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        pdf = child / "main.pdf"
        tex = child / "main.tex"
        meta["has_pdf"] = pdf.exists()
        try:
            # The source, not the directory: compiling rewrites the folder's
            # own mtime, so a project you only opened and built would sort as
            # though you had written it.
            meta["modified"] = tex.stat().st_mtime if tex.exists() else child.stat().st_mtime
        except OSError:
            meta["modified"] = 0.0
        meta["name_lower"] = str(meta.get("name", "")).lower()
        projects.append(meta)

    projects.sort(key=lambda m: m.get("modified", 0.0), reverse=True)
    return projects


def rename_project(project_id: str, name: str) -> dict:
    """change a project's display name.

    Only meta.json changes. The directory is named after the project id, not
    the title, so renaming costs nothing and cannot break a path the compiler,
    the PDF preview or an \\includegraphics is using -- which is exactly why
    the id was never the title in the first place.

    args:
        project_id: the project identifier.
        name: the new display name.

    returns:
        the updated metadata.

    raises:
        FileNotFoundError: no such project.
        ValueError: the name is empty.
    """
    import json

    clean = (name or "").strip()
    if not clean:
        raise ValueError("A paper needs a name.")
    clean = clean[:120]

    project_dir = _get_project_dir(project_id)
    meta_file = project_dir / "meta.json"
    if not meta_file.exists():
        raise FileNotFoundError(f"project {project_id} not found")

    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    meta["name"] = clean
    meta_file.write_text(json.dumps(meta), encoding="utf-8")
    meta["has_pdf"] = (project_dir / "main.pdf").exists()
    return meta


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
