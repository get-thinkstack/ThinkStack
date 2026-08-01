"""the shapes a small model actually returns, and what we do with them.

the gbnf grammar guarantees valid json, not correct json. every case here is
valid json that a 0.5B model has plausibly produced, and every one of them
either crashed a caller or silently became an empty result before the coercion
layer existed.
"""

import numpy as np
import pytest

from domain.analysis.parsing import as_dict, as_items, as_str_list, one_of
from domain.analysis.theme_clusterer import _components
from domain.gap_finder.gap_pipeline import _parse_gaps, _parse_suggestions


class TestAsItems:
    def test_finds_the_asked_for_key(self):
        assert as_items({"claims": [1, 2]}, "claims") == [1, 2]

    def test_a_bare_list_is_the_list(self):
        # model dropped the wrapper object entirely
        assert as_items([1, 2], "claims") == [1, 2]

    def test_singular_key_is_accepted(self):
        assert as_items({"claim": ["a"]}, "claims") == ["a"]

    def test_a_single_object_becomes_one_item(self):
        assert as_items({"claims": {"claim_text": "x"}}, "claims") == [{"claim_text": "x"}]

    def test_an_unexpected_key_is_recovered_by_shape(self):
        # exactly one list-valued field, so there is no ambiguity about which
        # one the model meant.
        assert as_items({"findings": ["a", "b"]}, "claims") == ["a", "b"]

    def test_two_candidate_lists_are_not_guessed_between(self):
        assert as_items({"a": [1], "b": [2]}, "claims") == []

    def test_a_scalar_response_yields_nothing_rather_than_raising(self):
        assert as_items("not json at all", "claims") == []
        assert as_items(None, "claims") == []


class TestAsDict:
    def test_a_bare_string_becomes_the_text_field(self):
        # THE regression: item.get() on a str raised AttributeError, outside
        # the try block that was supposed to contain parse failures.
        assert as_dict("a claim", "claim_text") == {"claim_text": "a claim"}

    def test_a_dict_passes_through(self):
        assert as_dict({"claim_text": "x"}, "claim_text") == {"claim_text": "x"}

    def test_a_number_is_dropped_not_crashed_on(self):
        assert as_dict(42, "claim_text") == {}


class TestOneOf:
    def test_an_allowed_value_survives(self):
        assert one_of("finding", ("finding", "limitation"), "finding") == "finding"

    def test_case_and_separators_are_normalised(self):
        assert one_of("Future Work", ("future_work",), "finding") == "future_work"
        assert one_of("future-work", ("future_work",), "finding") == "future_work"

    def test_an_invented_category_falls_back(self):
        # otherwise it reaches the canvas as a node label
        assert one_of("vibes", ("finding",), "finding") == "finding"

    def test_a_non_string_falls_back(self):
        assert one_of(None, ("finding",), "finding") == "finding"
        assert one_of(7, ("finding",), "finding") == "finding"


class TestAsStrList:
    def test_a_lone_string_becomes_one_element(self):
        assert as_str_list("only one") == ["only one"]

    def test_empties_are_dropped(self):
        assert as_str_list(["a", "", None, "b"]) == ["a", "b"]

    def test_a_non_list_yields_empty(self):
        assert as_str_list({"a": 1}) == []


class TestGapParsingSurvivesBadShapes:
    def test_gaps_as_bare_strings_do_not_crash(self):
        gaps = _parse_gaps(["the field ignores X"], ["d1", "d2"])
        assert len(gaps) == 1
        assert gaps[0].description == "the field ignores X"
        assert gaps[0].gap_type == "under_explored"

    def test_an_invented_gap_type_falls_back(self):
        gaps = _parse_gaps([{"description": "d", "gap_type": "spicy"}], ["d1"])
        assert gaps[0].gap_type == "under_explored"

    def test_a_hallucinated_doc_id_is_dropped(self):
        gaps = _parse_gaps(
            [{"description": "d", "related_doc_ids": ["d1", "ghost"]}], ["d1", "d2"]
        )
        assert gaps[0].related_doc_ids == ["d1"]

    def test_no_real_doc_ids_falls_back_to_the_analysed_set(self):
        gaps = _parse_gaps([{"description": "d", "related_doc_ids": ["ghost"]}], ["d1"])
        assert gaps[0].related_doc_ids == ["d1"]

    def test_a_gap_with_no_description_is_dropped(self):
        assert _parse_gaps([{"gap_type": "temporal"}], ["d1"]) == []

    def test_true_is_not_treated_as_gap_index_one(self):
        gaps = _parse_gaps([{"description": "g1"}], ["d1"])
        s = _parse_suggestions(
            [{"title": "t", "related_gap_indexes": [True]}], gaps
        )
        assert s[0].related_gaps == []

    def test_an_out_of_range_gap_index_is_dropped(self):
        gaps = _parse_gaps([{"description": "g1"}], ["d1"])
        s = _parse_suggestions([{"title": "t", "related_gap_indexes": [9]}], gaps)
        assert s[0].related_gaps == []

    def test_a_valid_gap_index_is_remapped_to_its_id(self):
        gaps = _parse_gaps([{"description": "g1"}], ["d1"])
        s = _parse_suggestions([{"title": "t", "related_gap_indexes": [1]}], gaps)
        assert s[0].related_gaps == [gaps[0].gap_id]


def _unit(*rows) -> np.ndarray:
    m = np.array(rows, dtype=np.float32)
    return m / np.linalg.norm(m, axis=1, keepdims=True)


class TestComponents:
    """membership comes from embeddings, so it is testable without a model."""

    def test_two_similar_papers_form_one_theme(self):
        # THE regression: three closely-related papers came back as three
        # themes of one paper each, which is not a clustering.
        m = _unit([1.0, 0.0], [0.98, 0.2])
        assert _components(["a", "b"], m, 0.60) == [["a", "b"]]

    def test_two_unrelated_papers_stay_apart(self):
        m = _unit([1.0, 0.0], [0.0, 1.0])
        groups = _components(["a", "b"], m, 0.60)
        assert sorted(groups) == [["a"], ["b"]]

    def test_a_bridging_paper_joins_both_sides(self):
        # single linkage on purpose: a paper spanning two subtopics belongs
        # with both, and a territory is a region, not a tight ball.
        m = _unit([1.0, 0.0], [0.75, 0.66], [0.0, 1.0])
        groups = _components(["a", "bridge", "c"], m, 0.60)
        assert groups == [["a", "bridge", "c"]]

    def test_every_paper_appears_exactly_once(self):
        m = _unit([1.0, 0.0], [0.9, 0.4], [0.0, 1.0], [0.1, 0.99])
        groups = _components(["a", "b", "c", "d"], m, 0.60)
        flat = [d for g in groups for d in g]
        assert sorted(flat) == ["a", "b", "c", "d"]
        assert len(flat) == len(set(flat))

    def test_groups_come_back_largest_first(self):
        m = _unit([1.0, 0.0], [0.99, 0.1], [0.0, 1.0])
        groups = _components(["a", "b", "loner"], m, 0.60)
        assert [len(g) for g in groups] == [2, 1]

    def test_a_single_paper_is_its_own_theme(self):
        assert _components(["a"], _unit([1.0, 0.0]), 0.60) == [["a"]]

    def test_no_papers_yields_no_themes(self):
        assert _components([], np.empty((0, 2), dtype=np.float32), 0.60) == []
