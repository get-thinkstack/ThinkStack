r"""build the index a document asked for, without shipping makeindex.

`\index{term}` writes a line into `main.idx`; something then has to turn that
into `main.ind`, which `\printindex` reads. Nothing did. Tectonic runs BibTeX on
its own but not makeindex, so a paper using an index compiled into:

    ! Undefined control sequence.
    l.26 \indexentry
                    {federated learning|hyperpage}{1}

which is `imakeidx` falling back to `\input`-ing the raw `.idx` -- a file full
of a command LaTeX does not define.

The obvious fix is to shell out to `makeindex`. It is on this developer's
machine and would not be in the installer, and the whole premise of the
bundled TeX engine is that a user needs nothing installed. So the `.ind` is
generated here instead. It is a small format, and this is the same
auto-healing the compiler already does for missing packages.

Supported, because real papers use them:
  ``term``                a plain entry
  ``main!sub``            a subentry, nested under its parent
  ``sort@typeset``        sort by one string, print another (\\emph{X} etc.)
  ``term|hyperpage``      an encapsulator; the page number is wrapped in it
  ``term|(`` / ``term|)`` a page RANGE, opened and closed across the document
"""

from __future__ import annotations

import re
from collections import OrderedDict
from pathlib import Path

# \indexentry{WHAT}{PAGE}. The braces inside WHAT nest (sort@\emph{x}), so the
# split is done by counting rather than by a non-greedy match, which would stop
# at the first inner brace.
_ENTRY = re.compile(r"\\indexentry\s*\{")


def _read_braced(text: str, start: int) -> tuple[str, int]:
    """read a balanced {...} beginning at ``start`` (the opening brace)."""
    depth, i = 0, start
    while i < len(text):
        c = text[i]
        if c == "\\":            # an escaped brace is content, not structure
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:i], i + 1
        i += 1
    return text[start + 1:], len(text)


def parse_idx(raw: str) -> list[tuple[str, str]]:
    """every ``(what, page)`` in an .idx file, in the order written."""
    out: list[tuple[str, str]] = []
    for m in _ENTRY.finditer(raw):
        what, after = _read_braced(raw, m.end() - 1)
        rest = raw[after:].lstrip()
        if not rest.startswith("{"):
            continue
        page, _ = _read_braced(rest, 0)
        out.append((what, page))
    return out


def _split_encap(what: str) -> tuple[str, str]:
    """``term|hyperpage`` -> ``("term", "hyperpage")``."""
    # not rsplit: a term may legitimately contain a pipe inside braces
    depth = 0
    for i, c in enumerate(what):
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif c == "|" and depth == 0:
            return what[:i], what[i + 1:]
    return what, ""


def _split_levels(term: str) -> list[str]:
    """``main!sub!subsub`` -> its levels, ignoring ! inside braces."""
    levels, depth, current = [], 0, ""
    for c in term:
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        if c == "!" and depth == 0:
            levels.append(current)
            current = ""
        else:
            current += c
    levels.append(current)
    return [x for x in levels if x.strip()]


def _sort_and_print(level: str) -> tuple[str, str]:
    """``sort@printed`` -> ``(sort_key, what_to_typeset)``."""
    depth = 0
    for i, c in enumerate(level):
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif c == "@" and depth == 0:
            return level[:i], level[i + 1:]
    return level, level


def _page_key(page: str):
    """sort pages numerically where possible, and roman/appendix pages after."""
    try:
        return (0, int(page), "")
    except ValueError:
        return (1, 0, page)


def build_ind(raw_idx: str) -> str:
    r"""turn the contents of an .idx into a ``theindex`` environment.

    Returns the full text of the .ind file. An empty index still produces a
    valid (empty) environment, because `\printindex` must have something to
    read -- the alternative is the error this module exists to prevent.
    """
    # level path -> {typeset name, pages}
    tree: OrderedDict[tuple, dict] = OrderedDict()
    # ranges opened with |( and awaiting their |)
    open_ranges: dict[tuple, str] = {}

    for what, page in parse_idx(raw_idx):
        term, encap = _split_encap(what)
        levels = _split_levels(term)
        if not levels:
            continue

        path, printed = [], []
        for level in levels:
            sort_key, shown = _sort_and_print(level)
            path.append(sort_key.strip().lower())
            printed.append(shown)
        key = tuple(path)

        node = tree.setdefault(key, {"printed": printed, "pages": []})

        # makeindex writes the encapsulator AFTER the paren: "|(hyperpage"
        # opens a range wrapped in \hyperpage, "|(" opens a bare one.
        if encap.startswith("("):
            open_ranges[key] = page
            continue
        if encap.startswith(")"):
            start = open_ranges.pop(key, None)
            wrap = encap[1:]
            span = f"{start}--{page}" if start and start != page else page
            node["pages"].append((_page_key(start or page),
                                  f"\\{wrap}{{{span}}}" if wrap else span))
            continue

        node["pages"].append((_page_key(page),
                              f"\\{encap}{{{page}}}" if encap else page))

    # a range never closed still deserves its opening page rather than vanishing
    for key, start in open_ranges.items():
        tree.setdefault(key, {"printed": [key[-1]], "pages": []})
        tree[key]["pages"].append((_page_key(start), start))

    lines = ["\\begin{theindex}", ""]
    previous: tuple = ()
    for key in sorted(tree):
        node = tree[key]
        depth = len(key) - 1
        # emit any parent that has no entries of its own, or the subentry would
        # be printed with nothing to sit under
        for d in range(depth):
            if previous[:d + 1] != key[:d + 1]:
                cmd = "item" if d == 0 else "subitem"
                parent = tree.get(key[:d + 1])
                label = parent["printed"][d] if parent else key[d]
                lines.append(f"  \\{cmd} {label}")

        cmd = ("item", "subitem", "subsubitem")[min(depth, 2)]
        label = node["printed"][depth] if depth < len(node["printed"]) else key[depth]

        seen, pages = set(), []
        for _, rendered in sorted(node["pages"]):
            if rendered not in seen:
                seen.add(rendered)
                pages.append(rendered)

        lines.append(f"  \\{cmd} {label}" + (f", {', '.join(pages)}" if pages else ""))
        previous = key

    lines += ["", "\\end{theindex}"]
    return "\n".join(lines) + "\n"


def write_index(project_dir: Path, stem: str = "main") -> bool:
    """generate ``<stem>.ind`` from ``<stem>.idx`` if there is one.

    Returns True when an index was written, which tells the compiler another
    pass is needed so ``\\printindex`` can pick it up.
    """
    idx = Path(project_dir) / f"{stem}.idx"
    if not idx.is_file():
        return False
    try:
        raw = idx.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    if "\\indexentry" not in raw:
        return False

    (Path(project_dir) / f"{stem}.ind").write_text(build_ind(raw), encoding="utf-8")
    return True
