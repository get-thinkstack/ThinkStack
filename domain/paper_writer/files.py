"""the files inside a paper project, and the boundary around them.

A project has always been a directory -- `main.tex` and `meta.json` sat in one
from the first version -- but nothing could reach anything except `main.tex`.
That is the whole reason `\\includegraphics{chart.png}` failed: the compiler
already runs with the project directory as its working directory, so a relative
path resolves correctly; there was simply no way to put a second file there.

This module is that way in, and the boundary that makes it safe.

── The boundary ──

Every function takes a path RELATIVE to the project and resolves it against the
project directory, then refuses anything that did not land inside. The webview
can reach the local API, so a filename arriving here is untrusted input in the
same sense a Hugging Face repo id is: `../../../.ssh/id_rsa` is a filename, and
`/etc/passwd` is a filename.

Resolution happens before the check, not after, because `a/../../b` only reveals
itself once resolved -- and symlinks only reveal themselves to `resolve()`. A
string check for ".." would pass a symlink pointing at the home directory.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

# Files ThinkStack writes and owns. They are regenerated on every compile and
# mean nothing to an author, so listing them turns a four-file project into a
# nine-file one where the two that matter are hard to find.
HIDDEN_NAMES = {"meta.json"}
HIDDEN_SUFFIXES = {
    ".aux", ".log", ".out", ".toc", ".synctex.gz", ".fls", ".fdb_latexmk",
    ".bbl", ".blg",
    # index intermediates. .idx is written by the engine and .ind is generated
    # from it (see indexing.py); neither is the author's to edit, and .idx in
    # particular is the file whose accidental \input produced the
    # "Undefined control sequence \indexentry" that started all this.
    ".idx", ".ind", ".ilg",
}

# What a LaTeX project can actually use. An arbitrary upload is a file the
# compiler will not read and the user cannot open -- it just consumes the disk.
ALLOWED_SUFFIXES = {
    ".tex", ".bib", ".cls", ".sty", ".bst",           # source
    ".png", ".jpg", ".jpeg", ".pdf", ".eps", ".svg",  # figures
    ".csv", ".dat", ".txt",                           # data for pgfplots
}

# A single figure is a few MB; 64 is generous. Without a cap the endpoint is a
# way to fill the user's disk through a page they did not know could write.
MAX_FILE_BYTES = 64 * 1024 * 1024
# The compile has to read all of this, and the whole directory is copied around
# during a salvage retry.
MAX_PROJECT_BYTES = 512 * 1024 * 1024


class FileError(Exception):
    """something the user should be told, in words they can act on."""


@dataclass(frozen=True)
class FileEntry:
    """one row in the tree."""
    path: str          # relative to the project, forward slashes
    name: str
    is_dir: bool
    size: int = 0

    @property
    def suffix(self) -> str:
        return Path(self.name).suffix.lower()


def _is_hidden(name: str) -> bool:
    lower = name.lower()
    if name in HIDDEN_NAMES or name.startswith("."):
        return True
    # ".synctex.gz" is two suffixes, so a plain Path.suffix check misses it
    return any(lower.endswith(s) for s in HIDDEN_SUFFIXES)


def safe_path(project_dir: Path, relpath: str) -> Path:
    """resolve ``relpath`` inside ``project_dir``, or refuse.

    THE security boundary of this module. Everything else calls it first.

    Refuses absolute paths, traversal, and anything that resolves outside the
    project -- including via a symlink, which is why this resolves rather than
    inspecting the string.
    """
    if relpath is None:
        raise FileError("No file was named.")

    text = str(relpath).strip().replace("\\", "/")
    if not text or text in (".", "/"):
        raise FileError("No file was named.")

    # A NUL truncates the path at the OS layer, so "a.tex\0.png" is written as
    # "a.tex" while every check above saw the harmless-looking full string.
    if "\0" in text:
        raise FileError("That file name is not valid.")

    if text.startswith("/") or (len(text) > 1 and text[1] == ":"):
        raise FileError("Use a path inside the project, not an absolute one.")

    root = Path(project_dir).resolve()
    try:
        candidate = (root / text).resolve()
    except (OSError, ValueError, RuntimeError) as e:
        # RuntimeError: a symlink loop. ValueError: embedded NUL on some platforms.
        raise FileError("That file name is not valid.") from e

    # `is_relative_to` compares resolved paths, so a symlink pointing outside
    # the project has already been followed and is caught here.
    if candidate != root and not candidate.is_relative_to(root):
        raise FileError("That path is outside the project.")
    if candidate == root:
        raise FileError("That is the project itself, not a file in it.")

    return candidate


def _rel(project_dir: Path, p: Path) -> str:
    return p.relative_to(Path(project_dir).resolve()).as_posix()


def project_bytes(project_dir: Path) -> int:
    """total size on disk, used to enforce the project cap."""
    root = Path(project_dir)
    if not root.is_dir():
        return 0
    return sum(f.stat().st_size for f in root.rglob("*") if f.is_file())


def list_files(project_dir: Path) -> list[FileEntry]:
    """every author-visible file in the project, directories first then a-z.

    Sorted rather than returned in directory order: the filesystem's order is
    arbitrary and would reshuffle the tree between two identical requests.
    """
    root = Path(project_dir).resolve()
    if not root.is_dir():
        return []

    out: list[FileEntry] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # pruning in place is what stops os.walk descending into hidden dirs
        dirnames[:] = sorted(d for d in dirnames if not _is_hidden(d))
        here = Path(dirpath)

        for d in dirnames:
            out.append(FileEntry(path=_rel(root, here / d), name=d, is_dir=True))

        for name in sorted(filenames):
            if _is_hidden(name):
                continue
            f = here / name
            try:
                size = f.stat().st_size
            except OSError:
                continue  # vanished between walking and stat-ing
            out.append(FileEntry(path=_rel(root, f), name=name, is_dir=False, size=size))

    out.sort(key=lambda e: (e.path.count("/"), not e.is_dir, e.path.lower()))
    return out


def read_file(project_dir: Path, relpath: str) -> str:
    """text contents, for the editor."""
    target = safe_path(project_dir, relpath)
    if not target.is_file():
        raise FileError(f"{relpath} does not exist.")
    try:
        return target.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise FileError(f"{relpath} is not a text file.") from e


def write_file(project_dir: Path, relpath: str, content: str) -> FileEntry:
    """create or overwrite a text file, making parent directories as needed."""
    target = safe_path(project_dir, relpath)
    if target.is_dir():
        raise FileError(f"{relpath} is a folder.")
    _check_suffix(target.name)

    data = (content or "").encode("utf-8")
    _check_room(project_dir, len(data), replacing=target)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return FileEntry(path=_rel(project_dir, target), name=target.name,
                     is_dir=False, size=len(data))


def write_bytes(project_dir: Path, relpath: str, data: bytes) -> FileEntry:
    """store an uploaded file -- a figure, a .bib, a data file."""
    target = safe_path(project_dir, relpath)
    if target.is_dir():
        raise FileError(f"{relpath} is a folder.")
    _check_suffix(target.name)

    if len(data) > MAX_FILE_BYTES:
        raise FileError(
            f"{target.name} is {len(data) // (1024 * 1024)} MB. "
            f"The limit is {MAX_FILE_BYTES // (1024 * 1024)} MB."
        )
    _check_room(project_dir, len(data), replacing=target)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return FileEntry(path=_rel(project_dir, target), name=target.name,
                     is_dir=False, size=len(data))


def make_dir(project_dir: Path, relpath: str) -> FileEntry:
    target = safe_path(project_dir, relpath)
    if target.exists():
        raise FileError(f"{relpath} already exists.")
    target.mkdir(parents=True)
    return FileEntry(path=_rel(project_dir, target), name=target.name, is_dir=True)


def delete_path(project_dir: Path, relpath: str) -> None:
    """remove a file or a folder and everything under it."""
    target = safe_path(project_dir, relpath)
    if not target.exists():
        raise FileError(f"{relpath} does not exist.")
    # Deleting main.tex leaves a project that cannot compile and offers no way
    # back through the interface, so it is refused rather than merely warned about.
    if target.name == "main.tex" and target.parent == Path(project_dir).resolve():
        raise FileError("main.tex is the document itself and cannot be deleted.")
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()


def move_path(project_dir: Path, src: str, dst: str) -> FileEntry:
    """rename, or move into a folder. Both ends are checked."""
    source = safe_path(project_dir, src)
    target = safe_path(project_dir, dst)
    if not source.exists():
        raise FileError(f"{src} does not exist.")
    if target.exists():
        raise FileError(f"{dst} already exists.")
    if not source.is_dir():
        _check_suffix(target.name)
    # Moving a folder into itself detaches the whole subtree with no error.
    if source.is_dir() and target.is_relative_to(source):
        raise FileError("A folder cannot be moved inside itself.")

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))
    return FileEntry(
        path=_rel(project_dir, target), name=target.name,
        is_dir=target.is_dir(),
        size=target.stat().st_size if target.is_file() else 0,
    )


def copy_path(project_dir: Path, src: str, dst: str) -> FileEntry:
    """duplicate a file or folder -- the paste half of copy/paste."""
    source = safe_path(project_dir, src)
    target = safe_path(project_dir, dst)
    if not source.exists():
        raise FileError(f"{src} does not exist.")
    if target.exists():
        raise FileError(f"{dst} already exists.")
    if source.is_dir() and target.is_relative_to(source):
        raise FileError("A folder cannot be copied inside itself.")

    size = project_bytes(source) if source.is_dir() else source.stat().st_size
    _check_room(project_dir, size)

    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, target)
    else:
        _check_suffix(target.name)
        shutil.copy2(source, target)
    return FileEntry(
        path=_rel(project_dir, target), name=target.name,
        is_dir=target.is_dir(),
        size=target.stat().st_size if target.is_file() else 0,
    )


def unique_name(project_dir: Path, relpath: str) -> str:
    """``chart.png`` -> ``chart (2).png`` when the first is taken.

    Dropping a file that silently replaces one already there loses work with no
    warning, so an upload never overwrites by accident; the caller asks for a
    free name instead.
    """
    target = safe_path(project_dir, relpath)
    if not target.exists():
        return _rel(project_dir, target)

    stem, suffix = target.stem, target.suffix
    for n in range(2, 1000):
        candidate = target.with_name(f"{stem} ({n}){suffix}")
        if not candidate.exists():
            return _rel(project_dir, candidate)
    raise FileError("Too many files with that name.")


def _check_suffix(name: str) -> None:
    suffix = Path(name).suffix.lower()
    if not suffix:
        raise FileError(f"{name} needs a file extension.")
    if suffix not in ALLOWED_SUFFIXES:
        allowed = ", ".join(sorted(ALLOWED_SUFFIXES))
        raise FileError(f"{suffix} files are not used by LaTeX. Allowed: {allowed}.")


def _check_room(project_dir: Path, incoming: int, replacing: Path | None = None) -> None:
    """refuse a write that would push the project past its cap."""
    current = project_bytes(project_dir)
    if replacing is not None and replacing.is_file():
        current -= replacing.stat().st_size
    if current + incoming > MAX_PROJECT_BYTES:
        raise FileError(
            f"This project would exceed {MAX_PROJECT_BYTES // (1024 * 1024)} MB. "
            "Remove something first."
        )
