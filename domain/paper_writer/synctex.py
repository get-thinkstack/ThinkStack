"""Source line to page position, and back.

Every compile runs with `--synctex`, so every project carries a
`main.synctex.gz`. This parses it; api/routes_paper_files.py serves both
directions (no interface calls them yet).

WHAT THE FILE IS. A gzipped text log of boxes. After a small header giving the
unit and the input files, the body is one record per box:

    [1,24:4736287,52610785:29685704,47874498,0
    ^ ^  ^  ^       ^         ^        ^      ^
    |  \\  \\   \\       \\         \\        \\      depth
    |   \\  \\   \\       \\         \\        height
    |    \\  \\   \\       \\         width
    |     \\  \\   \\       y
    |      \\  \\   x
    |       \\  line in the source
    |        input file tag
    box kind

`{n` opens page n and `}n` closes it. Coordinates are TeX scaled points, and
there are 65536 of them to a point and 72.27 points to an inch -- so a PDF
viewer working in CSS pixels at 96 dpi wants sp / 65536 / 72.27 * 96.

WHY PARSE IT HERE rather than reach for a library. The format is a dozen lines
of text and the two questions this application asks of it are the two simplest
ones it answers. A dependency would be larger than the parser, and it would be
another compiled thing to carry into a bundle built for three operating
systems -- the argument that already retired ChromaDB and d3-force.

WHAT IT CANNOT DO, stated because the alternative is a feature that lies. TeX
records where a BOX went, not where a character went, so the answer is a line
and a rectangle rather than a column and a caret. A line that produced no box --
a comment, a blank, a macro that expanded to nothing -- has no position at all,
and the honest reply is the nearest line that did.
"""

from __future__ import annotations

import gzip
import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# 65536 scaled points to a TeX point, 72.27 TeX points to an inch.
SP_PER_INCH = 65536 * 72.27

# A box record: kind, tag, line, x, y, width, height, depth.
_RECORD = re.compile(
    r"^([\[\(hvxkgr\$])(\d+),(\d+)(?::(-?\d+),(-?\d+))?(?::(-?\d+),(-?\d+),(-?\d+))?"
)
_INPUT = re.compile(r"^Input:(\d+):(.*)$")


def _extent(box: "Box") -> float:
    """Area, with zero-size records ranked last rather than first.

    TeX writes marker records with no width or height -- kerns, glyph anchors --
    and "smallest box wins" would always choose one of those, which points at a
    position with no extent to highlight. They are still kept, because a line
    that produced nothing else is better located by a marker than not at all;
    they are simply never preferred to a box that occupies space.
    """
    area = box.width * box.height
    return area if area > 0 else float("inf")


@dataclass(frozen=True)
class Box:
    """One box TeX placed, and the source line that asked for it."""

    page: int
    tag: int
    line: int
    x: int          # scaled points, from the left of the page
    y: int          # scaled points, from the TOP of the page
    width: int
    height: int
    depth: int

    def rect_in(self, page_width_px: float, page_height_px: float,
                page_width_sp: float, page_height_sp: float) -> dict:
        """The box as a fraction-free rectangle in a viewer's pixels."""
        sx = page_width_px / page_width_sp if page_width_sp else 0
        sy = page_height_px / page_height_sp if page_height_sp else 0
        return {
            "x": self.x * sx,
            "y": (self.y - self.height) * sy,
            "width": self.width * sx,
            "height": (self.height + self.depth) * sy,
        }


@dataclass
class SyncMap:
    """Everything one `.synctex.gz` knows."""

    boxes: list[Box]
    inputs: dict[int, str]

    def tag_for(self, filename: str) -> int | None:
        """The input tag for a source file, matched on its name.

        Matched on the NAME rather than the full path: the path in the file is
        the one the compiler saw, and a project that has been moved -- or
        compiled inside a container -- carries a path that no longer exists
        while still describing the same document.
        """
        for tag, path in self.inputs.items():
            if path and Path(path).name == Path(filename).name:
                return tag
        return None

    def forward(self, line: int, tag: int | None = None) -> Box | None:
        """Where on the page did this source line end up?

        The smallest box on the earliest page, because the smallest box that
        claims a line is the tightest thing TeX will admit to having put there.
        A line with no box of its own answers with the nearest following line
        that has one -- the paragraph it belongs to -- rather than nothing.
        """
        candidates = [b for b in self.boxes
                      if b.line == line and (tag is None or b.tag == tag)]
        if not candidates:
            later = [b for b in self.boxes
                     if b.line > line and (tag is None or b.tag == tag)]
            if not later:
                return None
            nearest = min(b.line for b in later)
            candidates = [b for b in later if b.line == nearest]
        return min(candidates, key=lambda b: (b.page, _extent(b)))

    def reverse(self, page: int, x: int, y: int) -> Box | None:
        """Which source line produced what is at this point on the page?

        Boxes containing the point, smallest first: they nest, and the innermost
        one is the specific thing rather than the paragraph around it. Nothing
        contains the point -- a margin, a gap between lines -- answers with the
        nearest box on the page instead of nothing, because a click in a margin
        still means "somewhere about here".
        """
        on_page = [b for b in self.boxes if b.page == page]
        if not on_page:
            return None
        inside = [
            b for b in on_page
            if b.x <= x <= b.x + b.width
            and (b.y - b.height) <= y <= (b.y + b.depth)
        ]
        if inside:
            return min(inside, key=_extent)
        return min(on_page, key=lambda b: (b.x - x) ** 2 + (b.y - y) ** 2)


def parse(path: str | Path) -> SyncMap:
    """Read a `.synctex.gz`. A malformed one is empty, never an exception.

    This is called to answer a click. A parse failure means the feature does
    nothing that time, which is a great deal better than a traceback where a
    cursor move was expected.
    """
    boxes: list[Box] = []
    inputs: dict[int, str] = {}
    page = 0
    try:
        with gzip.open(path, "rt", errors="replace") as fh:
            for raw in fh:
                row = raw.rstrip("\n")
                if not row:
                    continue
                if row[0] == "{":
                    page = int(row[1:] or 0)
                    continue
                if row[0] == "}":
                    page = 0
                    continue
                if row.startswith("Input:"):
                    m = _INPUT.match(row)
                    if m:
                        inputs[int(m.group(1))] = m.group(2)
                    continue
                m = _RECORD.match(row)
                if not m or not page:
                    continue
                _, tag, line, x, y, w, h, d = m.groups()
                if x is None:
                    continue                       # a record with no position
                boxes.append(Box(
                    page=page, tag=int(tag), line=int(line),
                    x=int(x), y=int(y),
                    width=int(w or 0), height=int(h or 0), depth=int(d or 0),
                ))
    except (OSError, EOFError, ValueError) as e:
        logger.warning("could not read %s: %s", path, e)
        return SyncMap(boxes=[], inputs={})
    return SyncMap(boxes=boxes, inputs=inputs)
