"""unit tests for the regex-based bibliographic extractors.

these are heuristic parsers over messy paper text, so the tests pin the behaviour
that matters (title stops at the abstract; author lines yield "First Last" names;
empty input yields empty results) rather than every heuristic branch. the SLM
fallback path is not exercised here (it needs the model).
"""

from domain.ingestion.metadata_extractor import _extract_authors, _extract_title


class TestExtractTitle:
    def test_title_is_first_block(self):
        text = "Deep Learning for Medical Imaging\n\nAbstract\nThis paper..."
        assert _extract_title(text) == "Deep Learning for Medical Imaging"

    def test_stops_at_abstract_keyword(self):
        text = "A Survey of Transformers\nAbstract: we review..."
        assert "Abstract" not in _extract_title(text)

    def test_skips_short_leading_lines(self):
        # lines <= 10 chars are skipped as noise (page numbers, etc.)
        text = "p. 1\nOptimization Methods for Neural Networks\n\nAbstract"
        assert _extract_title(text) == "Optimization Methods for Neural Networks"

    def test_empty_text(self):
        assert _extract_title("") == ""


class TestExtractAuthors:
    def test_extracts_first_last_names(self):
        text = "NEURAL NETWORKS: A SURVEY\nJohn Smith and Jane Doe\nAbstract"
        authors = _extract_authors(text)
        assert "John Smith" in authors and "Jane Doe" in authors

    def test_comma_separated_names(self):
        text = "DEEP MODELS\nAlice Wong, Bob Turner\nAbstract"
        authors = _extract_authors(text)
        assert "Alice Wong" in authors and "Bob Turner" in authors

    def test_skips_email_lines(self):
        text = "TITLE HERE\nj.smith@university.edu\nAbstract"
        assert _extract_authors(text) == []

    def test_empty_text(self):
        assert _extract_authors("") == []

    def test_caps_at_ten_authors(self):
        names = ", ".join(f"Firstname{i} Lastname" for i in range(20))
        text = f"BIG COLLABORATION\n{names}\nAbstract"
        assert len(_extract_authors(text)) <= 10
