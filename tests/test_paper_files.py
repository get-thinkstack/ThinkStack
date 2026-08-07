"""files inside a paper project, and the boundary that keeps them there.

The security tests come first and outnumber the rest, deliberately. This module
turns "a project is one file" into "a project is a directory the user writes
to", and the thing doing the writing is reachable from the webview -- which
Tauri treats as remote content. A filename is untrusted input here in exactly
the way a Hugging Face repo id is.

The rest covers the ordinary mistakes: dropping a file over one already there,
deleting the document itself, moving a folder into itself.
"""

from __future__ import annotations

import os

import pytest

from domain.paper_writer import files as F
from domain.paper_writer.files import FileError


@pytest.fixture
def project(tmp_path):
    """a project directory shaped like a real one."""
    p = tmp_path / "workspace" / "abc123"
    p.mkdir(parents=True)
    (p / "main.tex").write_text("\\documentclass{article}\\begin{document}x\\end{document}")
    (p / "meta.json").write_text('{"name": "test"}')
    (p / "main.log").write_text("build noise")
    (p / "main.aux").write_text("build noise")
    return p


# ─────────────────────────── the boundary ───────────────────────────

class TestNothingEscapesTheProject:
    @pytest.mark.parametrize("attack", [
        "../secret.tex",
        "../../secret.tex",
        "../../../../../../etc/passwd",
        "a/../../secret.tex",
        "./../../secret.tex",
        "sub/../../../secret.tex",
        "/etc/passwd",
        "/tmp/anywhere.tex",
        "..",
        "../",
    ])
    def test_traversal_is_refused(self, project, attack):
        with pytest.raises(FileError):
            F.safe_path(project, attack)

    @pytest.mark.parametrize("attack", ["\\..\\..\\secret.tex", "..\\secret.tex"])
    def test_backslash_traversal_is_refused(self, project, attack):
        # a windows-shaped path arriving at a linux server still means "escape"
        with pytest.raises(FileError):
            F.safe_path(project, attack)

    def test_a_symlink_out_of_the_project_is_refused(self, project, tmp_path):
        # the reason this resolves instead of checking the string for "..":
        # nothing about the NAME "notes.tex" says it points at /etc
        secret = tmp_path / "outside.txt"
        secret.write_text("private")
        try:
            os.symlink(secret, project / "notes.tex")
        except (OSError, NotImplementedError):
            pytest.skip("symlinks unavailable here")
        with pytest.raises(FileError):
            F.safe_path(project, "notes.tex")

    def test_a_symlinked_directory_out_of_the_project_is_refused(self, project, tmp_path):
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        try:
            os.symlink(outside, project / "figs", target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks unavailable here")
        with pytest.raises(FileError):
            F.safe_path(project, "figs/chart.png")

    def test_a_nul_byte_is_refused(self, project):
        # "a.tex\0.png" is written by the OS as "a.tex" while every check
        # upstream inspected the longer, harmless-looking string
        with pytest.raises(FileError):
            F.safe_path(project, "a.tex\0.png")

    @pytest.mark.parametrize("empty", ["", "   ", ".", "/", None])
    def test_an_empty_name_is_refused(self, project, empty):
        with pytest.raises(FileError):
            F.safe_path(project, empty)

    def test_the_project_root_itself_is_not_a_file(self, project):
        with pytest.raises(FileError):
            F.safe_path(project, "./")

    def test_an_ordinary_name_is_allowed(self, project):
        assert F.safe_path(project, "main.tex").name == "main.tex"

    def test_a_nested_name_is_allowed(self, project):
        got = F.safe_path(project, "figures/chart.png")
        assert got.name == "chart.png"
        assert got.parent.name == "figures"

    def test_traversal_that_stays_inside_is_allowed(self, project):
        # "figures/../main.tex" is legal: it resolves to somewhere legitimate
        assert F.safe_path(project, "figures/../main.tex").name == "main.tex"

    def test_every_write_path_enforces_the_boundary(self, project):
        # a boundary applied by only some callers is not a boundary
        for call in (
            lambda: F.write_file(project, "../escaped.tex", "x"),
            lambda: F.write_bytes(project, "../escaped.png", b"x"),
            lambda: F.read_file(project, "../../etc/passwd"),
            lambda: F.delete_path(project, "../secret.tex"),
            lambda: F.make_dir(project, "../escaped"),
            lambda: F.move_path(project, "main.tex", "../escaped.tex"),
            lambda: F.copy_path(project, "main.tex", "../escaped.tex"),
        ):
            with pytest.raises(FileError):
                call()

    def test_move_checks_the_SOURCE_too(self, project):
        with pytest.raises(FileError):
            F.move_path(project, "../../etc/passwd", "stolen.tex")


# ─────────────────────────── listing ───────────────────────────

class TestListing:
    def test_shows_the_document(self, project):
        assert "main.tex" in [e.path for e in F.list_files(project)]

    def test_hides_build_artefacts_and_internals(self, project):
        paths = [e.path for e in F.list_files(project)]
        for noise in ("meta.json", "main.log", "main.aux"):
            assert noise not in paths, f"{noise} should not be in the tree"

    def test_hides_synctex_which_has_two_suffixes(self, project):
        (project / "main.synctex.gz").write_text("x")
        assert "main.synctex.gz" not in [e.path for e in F.list_files(project)]

    def test_shows_the_pdf_because_the_author_wants_it(self, project):
        (project / "main.pdf").write_bytes(b"%PDF-1.4")
        assert "main.pdf" in [e.path for e in F.list_files(project)]

    def test_nested_files_are_listed_with_their_path(self, project):
        F.write_bytes(project, "figures/chart.png", b"\x89PNG")
        paths = [e.path for e in F.list_files(project)]
        assert "figures" in paths
        assert "figures/chart.png" in paths

    def test_does_not_descend_into_hidden_directories(self, project):
        (project / ".git").mkdir()
        (project / ".git" / "config").write_text("secret")
        assert not any(".git" in e.path for e in F.list_files(project))

    def test_order_is_stable(self, project):
        F.write_bytes(project, "b.png", b"x")
        F.write_bytes(project, "a.png", b"x")
        assert [e.path for e in F.list_files(project)] == [e.path for e in F.list_files(project)]

    def test_a_missing_project_lists_nothing_rather_than_raising(self, tmp_path):
        assert F.list_files(tmp_path / "nope") == []

    def test_sizes_are_reported(self, project):
        F.write_bytes(project, "chart.png", b"12345")
        entry = next(e for e in F.list_files(project) if e.name == "chart.png")
        assert entry.size == 5


# ─────────────────────────── writing ───────────────────────────

class TestWriting:
    def test_a_figure_lands_next_to_the_document(self, project):
        # the whole point: this is what \includegraphics{chart.png} needs
        F.write_bytes(project, "chart.png", b"\x89PNG\r\n")
        assert (project / "chart.png").read_bytes() == b"\x89PNG\r\n"

    def test_parent_folders_are_created(self, project):
        F.write_bytes(project, "figures/sub/chart.png", b"x")
        assert (project / "figures" / "sub" / "chart.png").is_file()

    def test_text_round_trips(self, project):
        F.write_file(project, "refs.bib", "@article{a}")
        assert F.read_file(project, "refs.bib") == "@article{a}"

    @pytest.mark.parametrize("bad", ["run.exe", "script.sh", "payload.so", "a.py"])
    def test_files_latex_cannot_use_are_refused(self, project, bad):
        with pytest.raises(FileError, match="not used by LaTeX"):
            F.write_bytes(project, bad, b"x")

    def test_a_file_with_no_extension_is_refused(self, project):
        with pytest.raises(FileError, match="extension"):
            F.write_bytes(project, "README", b"x")

    def test_an_oversized_file_is_refused(self, project):
        with pytest.raises(FileError, match="limit"):
            F.write_bytes(project, "huge.png", b"x" * (F.MAX_FILE_BYTES + 1))

    def test_the_project_cap_is_enforced(self, project, monkeypatch):
        monkeypatch.setattr(F, "MAX_PROJECT_BYTES", 1000)
        with pytest.raises(FileError, match="exceed"):
            F.write_bytes(project, "big.png", b"x" * 1001)

    def test_overwriting_does_not_double_count_against_the_cap(self, project, monkeypatch):
        F.write_bytes(project, "a.png", b"x" * 500)
        monkeypatch.setattr(F, "MAX_PROJECT_BYTES", 900)
        # replacing 500 bytes with 500 bytes is not 1000 bytes
        F.write_bytes(project, "a.png", b"y" * 500)
        assert (project / "a.png").read_bytes() == b"y" * 500

    def test_reading_a_binary_file_says_so(self, project):
        F.write_bytes(project, "chart.png", b"\x89PNG\x00\xff\xfe")
        with pytest.raises(FileError, match="not a text file"):
            F.read_file(project, "chart.png")

    def test_reading_something_absent_says_so(self, project):
        with pytest.raises(FileError, match="does not exist"):
            F.read_file(project, "nope.tex")


# ─────────────────────────── the ordinary mistakes ───────────────────────────

class TestNotLosingWork:
    def test_a_dropped_duplicate_gets_a_free_name(self, project):
        F.write_bytes(project, "chart.png", b"first")
        assert F.unique_name(project, "chart.png") == "chart (2).png"

    def test_and_keeps_counting(self, project):
        F.write_bytes(project, "chart.png", b"1")
        F.write_bytes(project, "chart (2).png", b"2")
        assert F.unique_name(project, "chart.png") == "chart (3).png"

    def test_a_free_name_is_returned_unchanged(self, project):
        assert F.unique_name(project, "fresh.png") == "fresh.png"

    def test_the_document_cannot_be_deleted(self, project):
        # it would leave a project that cannot compile and no way back in the ui
        with pytest.raises(FileError, match="cannot be deleted"):
            F.delete_path(project, "main.tex")

    def test_but_a_main_tex_in_a_subfolder_can_be(self, project):
        F.write_file(project, "parts/main.tex", "x")
        F.delete_path(project, "parts/main.tex")
        assert not (project / "parts" / "main.tex").exists()

    def test_deleting_a_folder_takes_its_contents(self, project):
        F.write_bytes(project, "figures/a.png", b"x")
        F.delete_path(project, "figures")
        assert not (project / "figures").exists()

    def test_a_folder_cannot_be_moved_into_itself(self, project):
        F.write_bytes(project, "figures/a.png", b"x")
        with pytest.raises(FileError, match="inside itself"):
            F.move_path(project, "figures", "figures/nested")

    def test_a_move_onto_an_existing_name_is_refused(self, project):
        F.write_bytes(project, "a.png", b"1")
        F.write_bytes(project, "b.png", b"2")
        with pytest.raises(FileError, match="already exists"):
            F.move_path(project, "a.png", "b.png")

    def test_renaming_works(self, project):
        F.write_bytes(project, "a.png", b"1")
        F.move_path(project, "a.png", "figures/renamed.png")
        assert (project / "figures" / "renamed.png").read_bytes() == b"1"
        assert not (project / "a.png").exists()

    def test_copy_leaves_the_original(self, project):
        F.write_bytes(project, "a.png", b"1")
        F.copy_path(project, "a.png", "b.png")
        assert (project / "a.png").exists() and (project / "b.png").exists()

    def test_making_a_folder_that_exists_is_refused(self, project):
        F.make_dir(project, "figures")
        with pytest.raises(FileError, match="already exists"):
            F.make_dir(project, "figures")


class TestErrorsAreFitToShow:
    def test_no_message_leaks_an_absolute_path(self, project, tmp_path):
        # the message goes to a webview; the user's home directory layout
        # is not something a filename error should disclose
        for call in (
            lambda: F.safe_path(project, "../../../etc/passwd"),
            lambda: F.read_file(project, "nope.tex"),
            lambda: F.write_bytes(project, "run.exe", b"x"),
            lambda: F.delete_path(project, "main.tex"),
        ):
            with pytest.raises(FileError) as e:
                call()
            msg = str(e.value)
            assert str(tmp_path) not in msg, f"leaked a real path: {msg}"
            assert "/home/" not in msg and "Traceback" not in msg
            # a sentence, not a repr. Leading lowercase is fine and often right:
            # "nope.tex does not exist." should start with the name the user typed.
            assert msg.endswith((".", "!")), f"not a sentence: {msg}"
