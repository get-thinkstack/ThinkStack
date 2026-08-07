r"""building the .ind a document asked for, without makeindex.

The bug: `\index{term}` writes `main.idx`, and nothing turned it into
`main.ind`. Tectonic runs BibTeX on its own but not makeindex, so a paper with
an index compiled into

    ! Undefined control sequence.
    l.26 \indexentry{federated learning|hyperpage}{1}

which is `imakeidx` giving up and `\input`-ing the raw `.idx` -- a file made
entirely of a command LaTeX does not define.

Shelling out to makeindex was the obvious fix and the wrong one: it is not in
the installer, and the point of bundling a TeX engine is that a user installs
nothing. So the file is generated, and these tests are what say it is generated
correctly.
"""

from __future__ import annotations

from domain.paper_writer.indexing import build_ind, parse_idx, write_index

# the entries from the report that started this
REAL = r"""\indexentry{federated learning|hyperpage}{1}
\indexentry{probability space|hyperpage}{3}
\indexentry{expectation|hyperpage}{3}
\indexentry{covariance|hyperpage}{4}
"""


class TestParsing:
    def test_reads_every_entry(self):
        assert len(parse_idx(REAL)) == 4

    def test_keeps_term_and_page_together(self):
        assert parse_idx(REAL)[0] == ("federated learning|hyperpage", "1")

    def test_braces_inside_a_term_do_not_end_it(self):
        # \emph{x} in a sort key would stop a non-greedy match at the wrong brace
        got = parse_idx(r"\indexentry{sort@\emph{shown}|hyperpage}{5}")
        assert got == [(r"sort@\emph{shown}|hyperpage", "5")]

    def test_junk_between_entries_is_ignored(self):
        raw = "% a comment\n" + REAL + "\nnot an entry\n"
        assert len(parse_idx(raw)) == 4

    def test_an_empty_file_yields_nothing(self):
        assert parse_idx("") == []


class TestTheIndexItself:
    def test_it_is_a_valid_environment(self):
        out = build_ind(REAL)
        assert out.startswith("\\begin{theindex}")
        assert out.rstrip().endswith("\\end{theindex}")

    def test_an_empty_index_is_still_valid(self):
        # \printindex must have something to read; an absent .ind is the bug
        out = build_ind("")
        assert "\\begin{theindex}" in out and "\\end{theindex}" in out

    def test_entries_are_alphabetical(self):
        items = [l for l in build_ind(REAL).splitlines() if l.strip().startswith("\\item")]
        assert items == sorted(items)

    def test_the_encapsulator_wraps_the_page(self):
        assert "\\hyperpage{4}" in build_ind(REAL)

    def test_a_term_with_no_encapsulator_prints_a_bare_page(self):
        out = build_ind(r"\indexentry{plain}{9}")
        assert "\\item plain, 9" in out

    def test_one_term_on_several_pages_is_merged(self):
        out = build_ind(
            r"\indexentry{gradients}{1}" "\n" r"\indexentry{gradients}{7}"
        )
        assert out.count("\\item gradients") == 1
        assert "\\item gradients, 1, 7" in out

    def test_the_same_page_twice_is_listed_once(self):
        out = build_ind(r"\indexentry{x}{3}" "\n" r"\indexentry{x}{3}")
        assert "\\item x, 3" in out

    def test_pages_sort_numerically_not_as_text(self):
        raw = "\n".join(rf"\indexentry{{t}}{{{n}}}" for n in (10, 2, 33, 4))
        assert "\\item t, 2, 4, 10, 33" in build_ind(raw)


class TestStructure:
    def test_a_subentry_is_nested(self):
        out = build_ind(r"\indexentry{privacy!differential|hyperpage}{9}")
        assert "\\item privacy" in out
        assert "\\subitem differential" in out

    def test_a_parent_with_no_entries_of_its_own_is_still_printed(self):
        # otherwise the subentry is printed with nothing to sit under
        out = build_ind(
            r"\indexentry{privacy!differential}{9}" "\n"
            r"\indexentry{privacy!local}{9}"
        )
        assert out.count("\\item privacy") == 1
        assert "\\subitem differential" in out and "\\subitem local" in out

    def test_three_levels(self):
        out = build_ind(r"\indexentry{a!b!c}{1}")
        assert "\\subsubitem c" in out

    def test_sort_key_orders_but_the_other_half_prints(self):
        out = build_ind(r"\indexentry{gradient descent@\emph{gradient descent}}{12}")
        assert "\\emph{gradient descent}" in out
        assert "@" not in out, "the sort key must not reach the page"


class TestPageRanges:
    def test_open_and_close_become_a_range(self):
        out = build_ind(
            r"\indexentry{convergence|(}{14}" "\n" r"\indexentry{convergence|)}{18}"
        )
        assert "14--18" in out

    def test_a_range_that_opens_and_closes_on_one_page_is_one_number(self):
        out = build_ind(
            r"\indexentry{x|(}{5}" "\n" r"\indexentry{x|)}{5}"
        )
        assert "--" not in out
        assert "\\item x, 5" in out

    def test_a_range_never_closed_still_lists_its_opening_page(self):
        # a truncated document should not make an entry disappear entirely
        out = build_ind(r"\indexentry{dangling|(}{3}")
        assert "dangling" in out and "3" in out

    def test_a_range_keeps_its_encapsulator(self):
        out = build_ind(
            r"\indexentry{c|(hyperpage}{2}" "\n" r"\indexentry{c|)hyperpage}{6}"
        )
        assert "\\hyperpage{2--6}" in out


class TestWritingTheFile:
    def test_writes_ind_next_to_idx(self, tmp_path):
        (tmp_path / "main.idx").write_text(REAL)
        assert write_index(tmp_path) is True
        assert (tmp_path / "main.ind").is_file()
        assert "\\begin{theindex}" in (tmp_path / "main.ind").read_text()

    def test_no_idx_means_nothing_to_do(self, tmp_path):
        assert write_index(tmp_path) is False
        assert not (tmp_path / "main.ind").exists()

    def test_an_idx_with_no_entries_is_left_alone(self, tmp_path):
        (tmp_path / "main.idx").write_text("% nothing here\n")
        assert write_index(tmp_path) is False

    def test_a_broken_idx_does_not_raise(self, tmp_path):
        # losing the PDF over a malformed index would be the worse failure
        (tmp_path / "main.idx").write_text(r"\indexentry{unclosed")
        write_index(tmp_path)

    def test_it_follows_the_document_stem(self, tmp_path):
        (tmp_path / "paper.idx").write_text(REAL)
        assert write_index(tmp_path, "paper") is True
        assert (tmp_path / "paper.ind").is_file()
