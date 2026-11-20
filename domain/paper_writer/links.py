"""Files a project uses that do not live inside it.

A separate module, not a loosening of `files.safe_path()`, so the boundary
that protects the workspace has no exception in it.

A link records where a file IS; nothing is copied unless the user asks
(`copy_into_project`). The compiler puts linked files' directories on its
search path (ADR 2026-08-23). The cost is that a referenced file can move,
which is the rest of this module.

── Finding it again ──

Every link stores the path AND the operating system's identity for the file:
`st_dev` and `st_ino`. That pair survives a rename and a move within a
filesystem, so a user who reorganises their documents does not silently lose
half a project. Resolution, in order:

    the stored path still holds a file        -> use it, refresh the identity
    the path is gone, the identity is nearby  -> use it, and remember the path
    neither                                   -> say so, and ask once

"Nearby" is deliberately small: the folders this project's other links sit in,
their parents, and one level of subdirectory beneath those. That catches a
rename, a drop into `figures/`, and a move beside a sibling chapter. It does not
walk the filesystem -- searching a home directory while somebody waits is worse
than asking them where the file went, and the ask is already built.

Limits: a copy has a new identity (it is a different file); a move to another
filesystem loses the inode; an editor that saves via temp-file-and-rename
changes the identity, which is why the PATH is tried first. Content hashing
was rejected: a full read per check, and it cannot tell two copies of one
shared .bib apart.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from domain.paper_writer.files import (
    MAX_FILE_BYTES,
    FileError,
    unique_name,
    write_bytes,
)

logger = logging.getLogger(__name__)

LINKS_FILE = "links.json"


@dataclass
class LinkedFile:
    """One file outside the project that the project uses."""

    id: str
    path: str            # absolute, as last known
    name: str            # what to show
    dev: int             # st_dev  ─┐ together, the identity that
    ino: int             # st_ino  ─┘ survives a rename or a move
    size: int
    mtime: float
    added_at: float
    kind: str = "file"        # "file" | "dir"

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class ResolvedLink:
    """A link, plus where it actually is now."""

    link: LinkedFile
    status: str          # "ok" | "moved" | "missing"
    resolved: Path | None

    def as_dict(self) -> dict:
        d = self.link.as_dict()
        d["status"] = self.status
        d["resolved"] = str(self.resolved) if self.resolved else None
        return d


def _links_path(project_dir: Path) -> Path:
    return project_dir / LINKS_FILE


def _read(project_dir: Path) -> list[LinkedFile]:
    p = _links_path(project_dir)
    if not p.is_file():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        # One unreadable index must not make the project unopenable. The links
        # are a convenience over files that still exist; the project does not
        # depend on them to compile.
        logger.warning("could not read %s: %s", p, e)
        return []
    out = []
    for row in raw if isinstance(raw, list) else []:
        try:
            out.append(LinkedFile(**row))
        except TypeError:
            continue          # a row from a future or broken version
    return out


def _write(project_dir: Path, links: list[LinkedFile]) -> None:
    """Write the index, atomically.

    Temp file then rename, so an interrupted write cannot leave a half-written
    index that the reader above would discard entirely.
    """
    p = _links_path(project_dir)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps([link.as_dict() for link in links], indent=2),
                   encoding="utf-8")
    tmp.replace(p)


def _identity(p: Path) -> tuple[int, int]:
    st = p.stat()
    return st.st_dev, st.st_ino


def add_link(project_dir: Path, target: str | Path) -> LinkedFile:
    r"""Record a file or a folder that lives outside the project.

    ── Why a file is filtered by suffix and a folder is not ──

    For a FILE the suffix allowlist is load-bearing rather than tidy. This is
    the one place the application takes an absolute path from its caller, and
    restricting it to what a LaTeX project can use is what keeps the things
    worth stealing unreachable: `~/.ssh/id_rsa` has no suffix, and neither does
    `/etc/passwd`.

    A FOLDER cannot be filtered that way -- a directory has no extension -- so
    it earns its safety differently: nothing here ever reads or serves the
    contents of a linked folder. It is a remembered location, for the author to
    point `\graphicspath` at and for `copy_into_project` to duplicate on an
    explicit instruction. That is why the raw endpoint refuses a folder rather
    than listing it: a browsable remote directory is a much larger thing to
    offer than a remembered one, and it is not what a paper needs.
    """
    p = Path(target).expanduser()
    if not p.is_absolute():
        raise FileError("A linked file needs a full path.")
    try:
        p = p.resolve(strict=True)
    except (OSError, RuntimeError):
        raise FileError(f"{p} does not exist.") from None

    if p.is_dir():
        kind, size = "dir", 0
    elif p.is_file():
        kind = "file"
        size = p.stat().st_size
        if size > MAX_FILE_BYTES:
            raise FileError(
                f"{p.name} is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB."
            )
    else:
        raise FileError(f"{p.name} is neither a file nor a folder.")

    links = _read(project_dir)
    dev, ino = _identity(p)
    for existing in links:
        if (existing.dev, existing.ino) == (dev, ino):
            existing.path, existing.name = str(p), p.name
            existing.size, existing.mtime = size, p.stat().st_mtime
            existing.kind = kind
            _write(project_dir, links)
            return existing

    link = LinkedFile(
        id=uuid.uuid4().hex[:12],
        path=str(p),
        name=p.name,
        dev=dev,
        ino=ino,
        size=size,
        mtime=p.stat().st_mtime,
        added_at=time.time(),
        kind=kind,
    )
    links.append(link)
    _write(project_dir, links)
    return link


# How many entries the search will look at before giving up. A user who moved
# one figure is found in the first handful; a user whose "known directory" is
# their home folder is not worth making everyone else wait for.
SEARCH_BUDGET = 4000


def _search_known_dirs(project_dir: Path, links: list[LinkedFile],
                       dev: int, ino: int) -> Path | None:
    """Look for a moved file where it is plausible to look.

    Only near directories this project already refers to: the folder each other
    link sits in, that folder's parent, and one level of subdirectories beneath
    them. That covers what people actually do -- rename it, drop it in a
    `figures/` folder, move it beside the chapter it belongs to.

    It deliberately does NOT walk the filesystem. Searching a home directory to
    find one .bib while somebody waits is a worse experience than being asked
    where the file went, and the ask is already built.
    """
    roots: list[Path] = []
    seen_roots: set[Path] = set()
    for other in links:
        d = Path(other.path).parent
        for candidate in (d, d.parent):
            if candidate in seen_roots or not candidate.is_dir():
                continue
            seen_roots.add(candidate)
            roots.append(candidate)

    budget = SEARCH_BUDGET
    for root in roots:
        try:
            entries = list(root.iterdir())
        except (OSError, PermissionError):
            continue
        subdirs = []
        for entry in entries:
            budget -= 1
            if budget <= 0:
                return None
            try:
                if entry.is_dir():
                    subdirs.append(entry)
                    if _identity(entry) == (dev, ino):
                        return entry          # a linked FOLDER that was renamed
                elif entry.is_file() and _identity(entry) == (dev, ino):
                    return entry
            except OSError:
                continue
        for sub in subdirs:
            try:
                for entry in sub.iterdir():
                    budget -= 1
                    if budget <= 0:
                        return None
                    try:
                        if entry.is_file() and _identity(entry) == (dev, ino):
                            return entry
                    except OSError:
                        continue
            except (OSError, PermissionError):
                continue
    return None


def resolve(project_dir: Path, link: LinkedFile) -> ResolvedLink:
    """Where is this file now?

    Path first, identity second. That order matters: an editor that saves by
    writing a temporary file and renaming it over the original leaves the same
    path holding a NEW identity, and the author considers that the same
    document. Trusting identity first would call it missing.
    """
    p = Path(link.path)
    if (p.is_dir() if link.kind == "dir" else p.is_file()):
        return ResolvedLink(link=link, status="ok", resolved=p)

    found = _search_known_dirs(project_dir, _read(project_dir), link.dev, link.ino)
    if found:
        return ResolvedLink(link=link, status="moved", resolved=found)
    return ResolvedLink(link=link, status="missing", resolved=None)


def list_links(project_dir: Path) -> list[ResolvedLink]:
    """Every link, resolved, with any moves written back to the index."""
    links = _read(project_dir)
    out, changed = [], False
    for link in links:
        r = resolve(project_dir, link)
        if r.status == "ok" and r.resolved is not None:
            try:
                dev, ino = _identity(r.resolved)
                if (dev, ino) != (link.dev, link.ino):
                    link.dev, link.ino = dev, ino     # saved-over in place
                    changed = True
            except OSError:
                pass
        elif r.status == "moved" and r.resolved is not None:
            link.path, link.name = str(r.resolved), r.resolved.name
            changed = True
        out.append(r)
    if changed:
        _write(project_dir, links)
    return out


def get(project_dir: Path, link_id: str) -> LinkedFile:
    for link in _read(project_dir):
        if link.id == link_id:
            return link
    raise FileError("That linked file is not in this project.")


def relink(project_dir: Path, link_id: str, target: str | Path) -> LinkedFile:
    """Point an existing link at a file the user has found for us."""
    links = _read(project_dir)
    for i, link in enumerate(links):
        if link.id != link_id:
            continue
        fresh = add_link(project_dir, target)
        if fresh.id != link_id:
            # add_link made a new row; fold it back onto the original id so
            # anything already referring to this link keeps working
            links = [x for x in _read(project_dir) if x.id != fresh.id]
            link.path, link.name = fresh.path, fresh.name
            link.dev, link.ino = fresh.dev, fresh.ino
            link.size, link.mtime = fresh.size, fresh.mtime
            links[i] = link
            _write(project_dir, links)
        return link
    raise FileError("That linked file is not in this project.")


def remove(project_dir: Path, link_id: str) -> None:
    """Forget the link. The file itself is never touched -- it is not ours."""
    links = _read(project_dir)
    kept = [link for link in links if link.id != link_id]
    if len(kept) == len(links):
        raise FileError("That linked file is not in this project.")
    _write(project_dir, kept)


def copy_into_project(project_dir: Path, link_id: str, dest: str = "") -> str:
    """Take a copy, on purpose.

    The escape hatch from referencing: a project that must travel as a unit,
    or a file the user is about to reorganise and would rather freeze.
    """
    link = get(project_dir, link_id)
    r = resolve(project_dir, link)
    if r.resolved is None:
        raise FileError(f"{link.name} cannot be found, so it cannot be copied in.")
    rel = f"{dest.strip('/')}/{link.name}" if dest.strip("/") else link.name
    free = unique_name(project_dir, rel)

    if link.kind == "dir":
        # Copied through the same boundary as everything else: each member is
        # placed with write_bytes, so safe_path checks it and the per-project
        # size cap still applies. shutil.copytree would bypass both.
        root = r.resolved
        for item in sorted(root.rglob("*")):
            if not item.is_file():
                continue
            # Every member comes across, matching the rule for linking a file.
            # The per-project cap in write_bytes is what bounds this, so a
            # folder larger than the project may allow stops partway with the
            # cap's own error rather than being silently thinned to the files
            # LaTeX happens to understand.
            inner = item.relative_to(root).as_posix()
            write_bytes(project_dir, f"{free}/{inner}", item.read_bytes())
        return free

    write_bytes(project_dir, free, r.resolved.read_bytes())
    return free
