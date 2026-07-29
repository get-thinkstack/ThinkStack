"""robustness tests for domain.paper_writer.compiler (the paper writer).

the paper writer's value is that a paper still compiles even when the AI emits a
bare fragment, forgets a \\usepackage, or produces a broken figure. these tests
exercise that auto-healing + salvage logic directly (no pdflatex needed) plus the
project CRUD, covering both the happy path and the degenerate inputs that must
degrade gracefully rather than crash.

the actual pdflatex invocation (compile_pdf) is an integration concern and is not
run here; every pure function it relies on is covered below.
"""

import pytest

from domain.paper_writer import compiler
from domain.paper_writer.compiler import (
    _default_template,
    _detect_missing_packages,
    _ensure_compilable,
    _ensure_packages,
    _extract_errors,
    _find_env_spans,
    _first_error_line,
    _has_package,
    _neutralize_all_figures,
    _salvage_one,
    create_project,
    delete_project,
    get_source,
    list_projects,
    save_source,
)


# ─────────────────────────── package detection ───────────────────────────
class TestHasPackage:
    def test_simple_import(self):
        assert _has_package(r"\usepackage{tikz}", "tikz")

    def test_grouped_import(self):
        assert _has_package(r"\usepackage{amsmath,amssymb}", "amssymb")

    def test_import_with_options(self):
        assert _has_package(r"\usepackage[utf8]{inputenc}", "inputenc")

    def test_absent_package(self):
        assert not _has_package(r"\usepackage{tikz}", "pgfplots")

    def test_word_boundary_prevents_substring_match(self):
        # "graph" must not match inside "graphicx"
        assert not _has_package(r"\usepackage{graphicx}", "graph")


# ─────────────────────────── package auto-injection ──────────────────────
class TestEnsurePackages:
    def _doc(self, body: str, preamble: str = r"\documentclass{article}") -> str:
        return f"{preamble}\n\\begin{{document}}\n{body}\n\\end{{document}}"

    def test_injects_missing_tikz(self):
        out = _ensure_packages(self._doc(r"\begin{tikzpicture}\end{tikzpicture}"))
        assert r"\usepackage{tikz}" in out

    def test_injects_after_documentclass(self):
        out = _ensure_packages(self._doc(r"\begin{tikzpicture}\end{tikzpicture}"))
        assert out.index(r"\documentclass") < out.index(r"\usepackage{tikz}")
        assert out.index(r"\usepackage{tikz}") < out.index(r"\begin{document}")

    def test_pgfplots_pulls_in_tikz_and_compat(self):
        out = _ensure_packages(self._doc(r"\begin{axis}\addplot{x};\end{axis}"))
        assert r"\usepackage{pgfplots}" in out
        assert r"\usepackage{tikz}" in out          # dependency auto-added
        assert r"\pgfplotsset{compat=1.18}" in out  # required setup line

    def test_does_not_duplicate_existing_package(self):
        src = self._doc(
            r"\begin{tikzpicture}\end{tikzpicture}",
            preamble=r"\documentclass{article}" + "\n" + r"\usepackage{tikz}",
        )
        # already present -> nothing to inject -> returned unchanged
        assert _ensure_packages(src) == src

    def test_booktabs_added_for_rules(self):
        out = _ensure_packages(self._doc(r"\toprule a \\ \bottomrule"))
        assert r"\usepackage{booktabs}" in out

    def test_no_begin_document_is_left_untouched(self):
        frag = r"\begin{tikzpicture}\end{tikzpicture}"
        assert _ensure_packages(frag) == frag


# ─────────────────────────── fragment wrapping ───────────────────────────
class TestEnsureCompilable:
    def test_full_document_passes_through(self):
        src = "\\documentclass{article}\n\\begin{document}\nhi\n\\end{document}"
        assert _ensure_compilable(src) == src  # nothing to heal

    def test_bare_fragment_gets_wrapped(self):
        out = _ensure_compilable(r"\section{intro} some text")
        assert r"\documentclass" in out
        assert r"\begin{document}" in out and r"\end{document}" in out
        assert "some text" in out

    def test_document_tags_without_class_are_wrapped(self):
        out = _ensure_compilable(r"\begin{document}body only\end{document}")
        assert r"\documentclass" in out
        assert "body only" in out

    def test_empty_input_yields_compilable_skeleton(self):
        out = _ensure_compilable("")
        assert r"\documentclass" in out and r"\begin{document}" in out

    def test_none_input_does_not_crash(self):
        out = _ensure_compilable(None)
        assert r"\begin{document}" in out

    def test_fragment_using_tikz_also_gets_the_package(self):
        out = _ensure_compilable(r"\begin{tikzpicture}\end{tikzpicture}")
        assert r"\usepackage{tikz}" in out


# ─────────────────────────── log parsing ─────────────────────────────────
class TestLogParsing:
    def test_extract_errors_captures_bang_blocks(self):
        log = "ok line\n! Undefined control sequence.\nl.5 \\foo\nmore\n"
        errs = _extract_errors(log)
        assert any("Undefined control sequence" in e for e in errs)

    def test_extract_errors_deduplicates(self):
        # identical error blocks (same 5-line context window) collapse to one.
        # 4 context lines after each "!" so both windows are byte-identical.
        block = "! Undefined control sequence.\nl.5 \\foo\na\nb\nc"
        log = block + "\n" + block
        assert len(_extract_errors(log)) == 1

    def test_extract_errors_caps_at_four(self):
        log = "\n".join(f"! Error number {i}." for i in range(10))
        assert len(_extract_errors(log)) == 4

    def test_extract_errors_no_errors(self):
        assert _extract_errors("all good, no bangs here") == []

    def test_detect_missing_packages(self):
        log = "! LaTeX Error: File `pgfplots.sty' not found."
        hints = _detect_missing_packages(log)
        assert len(hints) == 1 and "pgfplots" in hints[0]

    def test_detect_missing_packages_deduplicates(self):
        log = "File `multirow.sty' not found\nFile `multirow.sty' not found"
        assert len(_detect_missing_packages(log)) == 1

    def test_detect_missing_packages_none(self):
        assert _detect_missing_packages("no missing files") == []

    def test_first_error_line_found(self):
        assert _first_error_line("blah\nl.42 \\command\nmore") == 42

    def test_first_error_line_absent(self):
        assert _first_error_line("no line markers here") is None


# ─────────────────────────── environment spans ───────────────────────────
class TestFindEnvSpans:
    def test_single_environment(self):
        spans = _find_env_spans(r"\begin{figure}x\end{figure}")
        assert len(spans) == 1 and spans[0][0] == "figure"

    def test_nested_environments(self):
        spans = _find_env_spans(r"\begin{a}\begin{b}x\end{b}\end{a}")
        names = [s[0] for s in spans]
        assert "a" in names and "b" in names

    def test_unclosed_environment_is_ignored(self):
        assert _find_env_spans(r"\begin{figure}x") == []

    def test_mismatched_tags_are_ignored(self):
        assert _find_env_spans(r"\begin{a}x\end{b}") == []


# ─────────────────────────── salvage / degrade ───────────────────────────
class TestSalvageOne:
    SRC = (
        "\\documentclass{article}\n"          # 1
        "\\begin{document}\n"                  # 2
        "before text\n"                        # 3
        "\\begin{figure}\n"                    # 4
        "\\includegraphics{bad}\n"             # 5  <- error line
        "\\end{figure}\n"                      # 6
        "after text\n"                         # 7
        "\\end{document}\n"                    # 8
    )

    def test_replaces_enclosing_figure(self):
        new, note = _salvage_one(self.SRC, "l.5 \\includegraphics")
        assert note is not None
        assert r"\begin{figure}" not in new
        assert "could not be rendered" in new
        assert "after text" in new  # rest of the document is preserved

    def test_no_error_line_gives_up(self):
        new, note = _salvage_one(self.SRC, "no line marker")
        assert note is None and new == self.SRC

    def test_error_line_out_of_range(self):
        new, note = _salvage_one(self.SRC, "l.9999 x")
        assert note is None and new == self.SRC

    def test_error_outside_salvage_env_is_left_alone(self):
        # error on line 3 ("before text") is inside `document`, not a salvage env
        new, note = _salvage_one(self.SRC, "l.3 something")
        assert note is None and new == self.SRC


class TestNeutralizeAllFigures:
    def test_replaces_tikz_and_axis(self):
        src = (
            r"\begin{tikzpicture}\draw;\end{tikzpicture}"
            r"text"
            r"\begin{axis}\addplot;\end{axis}"
        )
        new, note = _neutralize_all_figures(src)
        assert note is not None and "2 figure" in note
        assert r"\begin{tikzpicture}" not in new and r"\begin{axis}" not in new
        assert "text" in new

    def test_nothing_to_neutralize(self):
        src = r"\section{plain text only}"
        new, note = _neutralize_all_figures(src)
        assert note is None and new == src


# ─────────────────────────── template ────────────────────────────────────
class TestDefaultTemplate:
    def test_is_a_complete_document(self):
        t = _default_template("My Paper")
        assert r"\documentclass" in t
        assert r"\begin{document}" in t and r"\end{document}" in t
        assert r"\section{introduction}" in t

    def test_escapes_special_characters_in_title(self):
        t = _default_template("deep_learning & AI")
        assert r"deep\_learning" in t and r"\& AI" in t


# ─────────────────────────── project CRUD ────────────────────────────────
@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """isolate the on-disk project workspace to a tmp dir."""
    monkeypatch.setattr(compiler, "PAPERS_DIR", tmp_path / "papers_ws")
    return tmp_path


class TestProjectCrud:
    def test_create_project(self, workspace):
        proj = create_project("Thesis")
        assert len(proj["project_id"]) == 12
        assert proj["name"] == "Thesis"
        assert r"\documentclass" in proj["source"]
        # round-trips from disk
        assert get_source(proj["project_id"]) == proj["source"]

    def test_save_and_get_source(self, workspace):
        proj = create_project("p")
        save_source(proj["project_id"], r"\documentclass{article}\begin{document}x\end{document}")
        assert "x" in get_source(proj["project_id"])

    def test_save_missing_project_raises(self, workspace):
        with pytest.raises(FileNotFoundError):
            save_source("does-not-exist", "whatever")

    def test_get_missing_project_raises(self, workspace):
        with pytest.raises(FileNotFoundError):
            get_source("does-not-exist")

    def test_delete_existing_project(self, workspace):
        proj = create_project("p")
        assert delete_project(proj["project_id"]) is True
        with pytest.raises(FileNotFoundError):
            get_source(proj["project_id"])

    def test_delete_missing_project_returns_false(self, workspace):
        assert delete_project("does-not-exist") is False

    def test_list_projects(self, workspace):
        a = create_project("alpha")
        b = create_project("beta")
        listed = {p["project_id"] for p in list_projects()}
        assert a["project_id"] in listed and b["project_id"] in listed

    def test_list_projects_reports_pdf_absence(self, workspace):
        create_project("p")
        assert all(p["has_pdf"] is False for p in list_projects())

    def test_list_projects_empty_workspace(self, workspace):
        assert list_projects() == []
