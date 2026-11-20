"""What a new document starts as.

Six starters: paper (the default), article, letter, CV, report, Beamer
slides. Scribe is a LaTeX editor first; citing the library makes it better for
research, not usable at all (ADR 2026-08-22).

Each template is a complete document. They deliberately do not share a preamble
beyond what `compiler._PREAMBLE` provides: a CV wants different packages from a
Beamer deck, and a shared preamble that carries everything for everyone is how
a two-page letter ends up loading pgfplots.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Template:
    id: str
    label: str
    description: str
    body: str          # what follows the preamble, including \begin{document}
    packages: tuple[str, ...] = ()   # anything beyond the standard preamble


def _escape(text: str) -> str:
    return text.replace("\\", "").replace("_", r"\_").replace("&", r"\&").replace("#", r"\#")


PAPER = Template(
    id="paper",
    label="Research paper",
    description="Abstract, sections, and a bibliography that Scribe can fill.",
    body=r"""
\title{{{title}}}
\author{{author name}}
\date{{\today}}

\begin{{document}}

\maketitle

\begin{{abstract}}
% write your abstract here
\end{{abstract}}

\section{{Introduction}}

% start writing here. type `cite` to cite a paper from your library.

\section{{Method}}

\section{{Results}}

\section{{Conclusion}}

\end{{document}}
""",
)

ARTICLE = Template(
    id="article",
    label="Plain article",
    description="A title and sections. Nothing assumed about what you are writing.",
    body=r"""
\title{{{title}}}
\author{{}}
\date{{\today}}

\begin{{document}}

\maketitle

% start writing here

\end{{document}}
""",
)

LETTER = Template(
    id="letter",
    label="Letter",
    description="Sender, recipient, and a signature.",
    body=r"""
\begin{{document}}

\begin{{flushright}}
Your Name \\
Your Address \\
\today
\end{{flushright}}

\vspace{{1em}}
Dear Sir or Madam,

\vspace{{1em}}
% what you want to say

\vspace{{2em}}
Yours faithfully,

\vspace{{3em}}
Your Name

\end{{document}}
""",
)

CV = Template(
    id="cv",
    label="CV",
    description="Sections with dated entries, and no page numbers.",
    body=r"""
\pagestyle{{empty}}

\begin{{document}}

\begin{{center}}
{{\LARGE {title}}}\\[0.3em]
your.email@example.com $\cdot$ +00 0000 000000
\end{{center}}

\vspace{{1em}}
\section*{{Education}}
\textbf{{Institution}} \hfill 2020--2024 \\
What you studied.

\section*{{Experience}}
\textbf{{Role, Organisation}} \hfill 2024--present \\
What you did.

\section*{{Skills}}
% list them

\end{{document}}
""",
)

REPORT = Template(
    id="report",
    label="Report",
    description="Chapters and a table of contents.",
    body=r"""
\title{{{title}}}
\author{{}}
\date{{\today}}

\begin{{document}}

\maketitle
\tableofcontents
\newpage

\section{{Introduction}}

\section{{Findings}}

\section{{Recommendations}}

\end{{document}}
""",
)

SLIDES = Template(
    id="slides",
    label="Slides",
    description="Beamer. One frame per slide.",
    # Beamer replaces the document class entirely, so this one carries its own
    # and the standard preamble is not used.
    body=r"""
\documentclass{{beamer}}
\usetheme{{default}}
\usepackage[utf8]{{inputenc}}

\title{{{title}}}
\author{{}}
\date{{\today}}

\begin{{document}}

\frame{{\titlepage}}

\begin{{frame}}{{First slide}}
  \begin{{itemize}}
    \item a point
    \item another
  \end{{itemize}}
\end{{frame}}

\end{{document}}
""",
)

ALL: tuple[Template, ...] = (PAPER, ARTICLE, LETTER, CV, REPORT, SLIDES)
DEFAULT = PAPER.id


def get(template_id: str | None) -> Template:
    """The template asked for, or the paper. An unknown id is not an error.

    A new document is not the place to refuse: if the id is stale or misspelled
    the author still wants a document, and the paper is the shape most of them
    are here for.
    """
    for t in ALL:
        if t.id == (template_id or DEFAULT):
            return t
    return PAPER


def render(template_id: str | None, title: str) -> str:
    """A complete document, ready to compile."""
    from domain.paper_writer.compiler import _PREAMBLE

    t = get(template_id)
    body = t.body.replace("{title}", _escape(title) or "Untitled")
    body = body.replace("{{", "{").replace("}}", "}")
    # Beamer brings its own class; anything else sits on the standard preamble.
    return body.lstrip("\n") if t.id == "slides" else _PREAMBLE + body
