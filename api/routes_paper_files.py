"""Scribe's file tree: the files in a project, linked files, the directory
browser, and source <-> PDF sync.

Mounted under the papers router: ``/api/papers/projects/{project_id}/...``.
The logic is domain/paper_writer/files.py (inside a project) and links.py
(outside it).

**Security boundary.** The webview can reach this API, so every filename is
untrusted. Paths inside a project go through `files.safe_path`; nothing builds
a path by concatenation. The link and browse routes are the exception and take
absolute paths (see the comment above those routes).
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from domain.paper_writer import files as F
from domain.paper_writer import links as L
from domain.paper_writer import synctex as SX
from domain.paper_writer.compiler import ProjectIdError, _get_project_dir

logger = logging.getLogger(__name__)
router = APIRouter()


def _project(project_id: str) -> Path:
    """The project directory, or 404. A malformed id gets the same 404 as a
    missing one, so a probe learns nothing about the id format."""
    try:
        d = _get_project_dir(project_id)
    except ProjectIdError:
        raise HTTPException(status_code=404, detail="project not found") from None
    if not d.is_dir():
        raise HTTPException(status_code=404, detail="project not found")
    return d


def _tree(project_dir: Path) -> list[dict]:
    return [
        {"path": e.path, "name": e.name, "is_dir": e.is_dir, "size": e.size}
        for e in F.list_files(project_dir)
    ]


def _guard(fn):
    """FileError -> 400 with its message (written for a person). Anything else
    is a bug and its internals must not reach the webview."""
    try:
        return fn()
    except F.FileError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.error("project file operation failed: %s", e)
        raise HTTPException(status_code=500, detail="That did not work.") from e


class WriteRequest(BaseModel):
    path: str
    content: str = ""


class PathRequest(BaseModel):
    path: str


class MoveRequest(BaseModel):
    src: str
    dst: str


@router.get("/projects/{project_id}/files")
async def api_list_files(project_id: str):
    """every author-visible file, build artefacts excluded."""
    return {"project_id": project_id, "files": _tree(_project(project_id))}


@router.get("/projects/{project_id}/files/content")
async def api_read_file(project_id: str, path: str):
    """the text of one file, for the editor."""
    d = _project(project_id)
    return {"path": path, "content": _guard(lambda: F.read_file(d, path))}


@router.put("/projects/{project_id}/files/content")
async def api_write_file(project_id: str, req: WriteRequest):
    """create or overwrite a text file. Returns the tree, so the UI re-renders
    from one authoritative payload rather than patching a local guess."""
    d = _project(project_id)
    entry = _guard(lambda: F.write_file(d, req.path, req.content))
    return {"file": entry.__dict__, "files": _tree(d)}


@router.post("/projects/{project_id}/files/upload")
async def api_upload_file(
    project_id: str,
    file: UploadFile = File(...),
    dest: str = "",
):
    """Store an uploaded file in folder `dest` ("" = project root).

    The upload's filename is untrusted (`../../../evil.png` is legal to send)
    and goes through the same boundary; an existing file is never replaced.
    """
    d = _project(project_id)
    raw = await file.read()

    name = Path(file.filename or "").name  # strip any directory the client sent
    if not name:
        raise HTTPException(status_code=400, detail="That upload had no file name.")

    target = f"{dest.strip('/')}/{name}" if dest.strip("/") else name
    free = _guard(lambda: F.unique_name(d, target))
    entry = _guard(lambda: F.write_bytes(d, free, raw))
    return {"file": entry.__dict__, "files": _tree(d)}


@router.get("/projects/{project_id}/files/raw")
async def api_raw_file(project_id: str, path: str):
    """serve a file as-is, so the tree can preview a figure."""
    d = _project(project_id)
    target = _guard(lambda: F.safe_path(d, path))
    if not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(target, filename=target.name)


@router.post("/projects/{project_id}/files/folder")
async def api_make_folder(project_id: str, req: PathRequest):
    d = _project(project_id)
    entry = _guard(lambda: F.make_dir(d, req.path))
    return {"file": entry.__dict__, "files": _tree(d)}


class MoveAcrossRequest(BaseModel):
    src: str
    to_project: str
    dst: str = ""


@router.post("/projects/{project_id}/files/move-to")
async def api_move_across(project_id: str, req: MoveAcrossRequest):
    """Move a file into a different paper. Each end is resolved against its
    own project root, so a crafted destination is a 404, not an escape."""
    src_dir = _project(project_id)
    dst_dir = _project(req.to_project)
    dst = req.dst or Path(req.src).name
    entry = _guard(lambda: F.move_between(src_dir, req.src, dst_dir, dst))
    return {
        "file": entry.__dict__,
        "files": _tree(src_dir),
        "to_files": _tree(dst_dir),
    }


@router.post("/projects/{project_id}/files/move")
async def api_move(project_id: str, req: MoveRequest):
    """rename, or move into a folder -- drag-and-drop inside the tree."""
    d = _project(project_id)
    entry = _guard(lambda: F.move_path(d, req.src, req.dst))
    return {"file": entry.__dict__, "files": _tree(d)}


@router.post("/projects/{project_id}/files/copy")
async def api_copy(project_id: str, req: MoveRequest):
    """the paste half of copy/paste."""
    d = _project(project_id)
    entry = _guard(lambda: F.copy_path(d, req.src, req.dst))
    return {"file": entry.__dict__, "files": _tree(d)}


@router.delete("/projects/{project_id}/files")
async def api_delete(project_id: str, path: str):
    d = _project(project_id)
    _guard(lambda: F.delete_path(d, path))
    return {"files": _tree(d)}


# ── files that live outside the project ──────────────────────────────────
#
# These take an ABSOLUTE path, the thing `safe_path` refuses everywhere else,
# and can reach any file the user can. That is acceptable only because:
#
#   1. another web page cannot read the replies (CORS allowlist, main.py), and
#      cannot send these routes' JSON bodies without a preflight the allowlist
#      refuses;
#   2. the path comes from a chooser the user drove;
#   3. a served file goes out as Content-Disposition: attachment, never as
#      something a page could script.
#
# There is no suffix allowlist (removed, ADR 2026-08-23). If (1) ever weakens,
# these routes become a file reader for any website. A linked file is never
# modified; a link is a note about where something is.


class LinkRequest(BaseModel):
    path: str


class RelinkRequest(BaseModel):
    path: str


class CopyInRequest(BaseModel):
    dest: str = ""


@router.get("/projects/{project_id}/links")
async def api_list_links(project_id: str):
    """Every linked file and where it is now, resolved on read (no watcher)."""
    d = _project(project_id)
    return {"links": [r.as_dict() for r in L.list_links(d)]}


@router.post("/projects/{project_id}/links")
async def api_add_link(project_id: str, req: LinkRequest):
    d = _project(project_id)
    link = _guard(lambda: L.add_link(d, req.path))
    return {"link": link.as_dict(), "links": [r.as_dict() for r in L.list_links(d)]}


@router.put("/projects/{project_id}/links/{link_id}")
async def api_relink(project_id: str, link_id: str, req: RelinkRequest):
    """The user has found a file we lost. Remember where, keep the same link."""
    d = _project(project_id)
    link = _guard(lambda: L.relink(d, link_id, req.path))
    return {"link": link.as_dict(), "links": [r.as_dict() for r in L.list_links(d)]}


@router.delete("/projects/{project_id}/links/{link_id}")
async def api_remove_link(project_id: str, link_id: str):
    """Forget the link. The file is not ours and is not touched."""
    d = _project(project_id)
    _guard(lambda: L.remove(d, link_id))
    return {"links": [r.as_dict() for r in L.list_links(d)]}


@router.post("/projects/{project_id}/links/{link_id}/copy")
async def api_copy_link_in(project_id: str, link_id: str, req: CopyInRequest):
    """Take a copy into the project, on purpose."""
    d = _project(project_id)
    rel = _guard(lambda: L.copy_into_project(d, link_id, req.dest))
    return {"path": rel, "files": _tree(d), "links": [r.as_dict() for r in L.list_links(d)]}


@router.get("/projects/{project_id}/links/{link_id}/raw")
async def api_link_raw(project_id: str, link_id: str):
    """Serve a linked file, so a figure can be previewed where it lies."""
    d = _project(project_id)
    link = _guard(lambda: L.get(d, link_id))
    if link.kind == "dir":
        # A linked folder is a remembered location, never served: that
        # would make this a remote directory listing.
        raise HTTPException(status_code=400, detail=f"{link.name} is a folder.")
    r = L.resolve(d, link)
    if r.resolved is None:
        raise HTTPException(status_code=404, detail=f"{link.name} cannot be found.")
    return FileResponse(r.resolved, filename=r.resolved.name)


# ── browsing the machine, for the chooser ─────────────────────────────────
#
# A browser has no native file dialog and a file input withholds the path, so
# the backend lists directories and the interface draws the chooser (the same
# in the desktop window and a tab). It lists only: names, sizes, is-directory.
# Nothing is read, opened or written; other pages cannot read the reply.


@router.get("/browse")
async def api_browse(path: str = ""):
    """One directory, listed for the chooser. Empty `path` = the home folder.

    Unreadable directories answer 403, not an empty listing: "nothing here"
    and "not allowed to look" are different facts.
    """
    root = Path(path).expanduser() if path else Path.home()
    try:
        root = root.resolve(strict=True)
    except (OSError, RuntimeError):
        raise HTTPException(status_code=404, detail="That folder does not exist.") from None
    if not root.is_dir():
        raise HTTPException(status_code=400, detail="That is not a folder.")

    dirs, files = [], []
    try:
        for entry in root.iterdir():
            if entry.name.startswith("."):
                continue                     # dotfiles are noise in a chooser
            try:
                if entry.is_dir():
                    dirs.append({"name": entry.name, "path": str(entry), "is_dir": True})
                elif entry.is_file():
                    files.append({
                        "name": entry.name,
                        "path": str(entry),
                        "is_dir": False,
                        "size": entry.stat().st_size,
                        # Every file can be linked; `latex` only hints that a
                        # document could reference it.
                        "linkable": True,
                        "latex": entry.suffix.lower() in F.LATEX_SUFFIXES,
                    })
            except OSError:
                continue                     # a broken symlink is not a reason to fail
    except PermissionError:
        raise HTTPException(status_code=403, detail="That folder cannot be opened.") from None

    dirs.sort(key=lambda e: e["name"].lower())
    files.sort(key=lambda e: e["name"].lower())
    return {
        "path": str(root),
        "parent": None if root.parent == root else str(root.parent),
        "home": str(Path.home()),
        "entries": dirs + files,
    }


# ── source <-> page (synctex) ────────────────────────────────────────────
#
# Both directions read the `main.synctex.gz` every compile writes. Parsed per
# request, not cached: it changes on every compile and parsing is cheap, so a
# cache could only ever point at the previous draft. No interface calls these
# yet (FUTURE_WORK).


@router.get("/projects/{project_id}/sync/forward")
async def api_sync_forward(project_id: str, line: int, file: str = "main.tex"):
    """Where on the page did this source line end up?"""
    d = _project(project_id)
    sx = d / "main.synctex.gz"
    if not sx.is_file():
        raise HTTPException(status_code=404,
                            detail="Compile the document first; there is no position map yet.")
    m = SX.parse(sx)
    box = m.forward(line, m.tag_for(file))
    if box is None:
        # A line that produced no box -- a comment, a blank, a macro that
        # expanded to nothing -- has no position, and saying so is better than
        # moving the reader somewhere arbitrary.
        raise HTTPException(status_code=404, detail="That line does not appear in the PDF.")
    return {
        "page": box.page,
        "line": box.line,
        "x": box.x, "y": box.y,
        "width": box.width, "height": box.height, "depth": box.depth,
        "sp_per_inch": SX.SP_PER_INCH,
    }


@router.get("/projects/{project_id}/sync/reverse")
async def api_sync_reverse(project_id: str, page: int, x: int, y: int):
    """Which source line produced what is at this point on the page?"""
    d = _project(project_id)
    sx = d / "main.synctex.gz"
    if not sx.is_file():
        raise HTTPException(status_code=404,
                            detail="Compile the document first; there is no position map yet.")
    m = SX.parse(sx)
    box = m.reverse(page, x, y)
    if box is None:
        raise HTTPException(status_code=404, detail="Nothing on that page came from the source.")
    return {"line": box.line, "file": m.inputs.get(box.tag) or "main.tex", "page": box.page}
