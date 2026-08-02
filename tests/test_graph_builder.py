"""unit tests for the litgraph graph builder.

the builder reads four stores (vectors, analysis cache, analysis history, gap
history) and computes a layout. all four are patched to temp instances here,
so these tests touch neither the user's data directory nor the embedding
model -- vectors are supplied by hand.

the layout fallbacks matter more than the happy path: an empty library, a
single paper, and a library where every paper is a near-duplicate are the
cases that produce a blank screen or a division by zero if unhandled.
"""

import numpy as np
import pytest

from domain.litgraph import graph_builder as gb
from domain.litgraph.graph_builder import (
    MIN_SEP,
    PAD,
    build_graph,
    _edges,
    _project,
)
from infrastructure.local_vector_store import VectorStore
from infrastructure.run_history import RunHistoryStore


def _closest_pair(coords: np.ndarray) -> float:
    """smallest centre-to-centre distance in a layout."""
    d = np.hypot(
        coords[:, None, 0] - coords[None, :, 0],
        coords[:, None, 1] - coords[None, :, 1],
    )
    np.fill_diagonal(d, np.inf)
    return float(d.min())


@pytest.fixture
def wire(tmp_path, monkeypatch):
    """patch every store the builder reads, and return a seeding helper."""
    store = VectorStore(persist_dir=str(tmp_path / "vs"))
    analysis = RunHistoryStore(tmp_path / "analysis.json")
    gaps = RunHistoryStore(tmp_path / "gaps.json")

    class _Cache:
        def __init__(self):
            self.entries = {}

        def get(self, doc_id):
            return self.entries.get(doc_id)

    cache = _Cache()

    monkeypatch.setattr(gb, "get_vector_store", lambda: store)
    monkeypatch.setattr(gb, "analysis_history", analysis)
    monkeypatch.setattr(gb, "gap_history", gaps)
    monkeypatch.setattr(gb, "doc_analysis_cache", cache)
    monkeypatch.setattr(gb, "get_all_doc_ids", lambda: sorted(
        {(m or {}).get("doc_id") for m in store.get()["metadatas"]} - {None}
    ))

    def seed(doc_id, vectors, title=None, chunks_meta=None):
        n = len(vectors)
        store.upsert(
            ids=[f"{doc_id}_c{i}" for i in range(n)],
            documents=[f"text {i}" for i in range(n)],
            embeddings=[list(map(float, v)) for v in vectors],
            metadatas=[
                {"doc_id": doc_id, "chunk_index": i, "page_number": i + 1,
                 "title": title or doc_id, **(chunks_meta or {})}
                for i in range(n)
            ],
        )

    return type("Wire", (), {
        "seed": staticmethod(seed), "store": store,
        "analysis": analysis, "gaps": gaps, "cache": cache,
    })


class TestProject:
    def test_empty(self):
        assert _project(np.empty((0, 0))).shape == (0, 2)

    def test_single_doc_sits_at_centre(self):
        coords = _project(np.array([[1.0, 0.0, 0.0]]))
        assert coords.tolist() == [[0.5, 0.5]]

    def test_two_docs_use_circle_fallback(self):
        """PCA cannot define two axes from two points; both must still be placed."""
        coords = _project(np.array([[1.0, 0.0], [0.0, 1.0]]))
        assert coords.shape == (2, 2)
        assert np.all(np.isfinite(coords))
        assert not np.allclose(coords[0], coords[1])

    def test_positions_stay_inside_the_padded_unit_square(self):
        rng = np.random.default_rng(0)
        coords = _project(rng.normal(size=(9, 16)))
        assert coords.min() >= PAD - 1e-6
        assert coords.max() <= 1 - PAD + 1e-6

    def test_identical_documents_do_not_stack_or_blow_up(self):
        """A library of near-duplicates has no variance to project.

        Normalising by a ~zero span would scatter every node to infinity or
        NaN; the guard must instead place them somewhere finite. And finite is
        not enough -- all five used to land on exactly (0.5, 0.5), which this
        test's name claimed was not happening.
        """
        coords = _project(np.ones((5, 8)))
        assert np.all(np.isfinite(coords))
        assert _closest_pair(coords) >= MIN_SEP - 1e-6

    def test_near_duplicates_are_pushed_apart(self):
        """PCA places related papers tightly, which is the point -- but two
        papers on one pixel read as one paper."""
        matrix = np.array([
            [1.0, 0.0, 0.0],
            [1.0, 1e-7, 0.0],   # a hair from the first
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ])
        assert _closest_pair(_project(matrix)) >= MIN_SEP - 1e-6

    def test_separation_does_not_escape_the_padded_square(self):
        rng = np.random.default_rng(1)
        coords = _project(rng.normal(size=(20, 12)))
        assert coords.min() >= PAD - 1e-6
        assert coords.max() <= 1 - PAD + 1e-6

    def test_the_same_library_always_draws_the_same_map(self):
        """Separation is seeded by PCA and runs a fixed number of passes.

        A layout that converged on a tolerance instead would rearrange itself
        between two visits to the same library, and a map you cannot learn is
        not worth drawing.
        """
        rng = np.random.default_rng(2)
        matrix = rng.normal(size=(12, 9))
        assert np.array_equal(_project(matrix), _project(matrix.copy()))

    def test_one_dimensional_library_spreads_along_a_line(self):
        """All papers on a single axis: keep component 1, fan the second."""
        matrix = np.array([[float(i), 0.0, 0.0] for i in range(6)])
        coords = _project(matrix)
        assert np.all(np.isfinite(coords))
        assert len({round(float(c), 3) for c in coords[:, 0]}) > 1


class TestEdges:
    def test_no_edges_below_two_nodes(self):
        assert _edges(["a"], np.array([[1.0, 0.0]])) == []

    def test_similar_documents_are_linked(self):
        ids = ["a", "b"]
        m = np.array([[1.0, 0.0], [0.99, 0.14]])
        edges = _edges(ids, m)
        assert len(edges) == 1
        assert {edges[0]["source"], edges[0]["target"]} == {"a", "b"}
        assert edges[0]["weight"] > 0.9

    def test_dissimilar_documents_are_not_linked(self):
        assert _edges(["a", "b"], np.array([[1.0, 0.0], [0.0, 1.0]])) == []

    def test_never_links_a_document_to_itself(self):
        edges = _edges(["a", "b", "c"], np.array([[1.0, 0.0], [1.0, 0.0], [1.0, 0.0]]))
        assert all(e["source"] != e["target"] for e in edges)

    def test_each_pair_appears_once(self):
        m = np.array([[1.0, 0.0], [1.0, 0.01], [0.99, 0.02]])
        edges = _edges(["a", "b", "c"], m)
        pairs = [frozenset((e["source"], e["target"])) for e in edges]
        assert len(pairs) == len(set(pairs))

    def test_degree_is_capped_so_a_tight_library_is_not_a_hairball(self):
        """Ten near-identical papers clear the threshold pairwise (45 edges).

        The per-node cap is what keeps that legible.
        """
        n = 10
        rng = np.random.default_rng(1)
        m = np.ones((n, 6)) + rng.normal(scale=0.01, size=(n, 6))
        edges = _edges([f"d{i}" for i in range(n)], m)
        assert len(edges) < n * (n - 1) / 2
        assert len(edges) <= n * gb.MAX_EDGES_PER_NODE


class TestBuildGraph:
    def test_empty_library_returns_empty_collections(self, wire):
        g = build_graph()
        assert g["nodes"] == [] and g["edges"] == []
        assert g["themes"] == [] and g["gaps"] == []
        assert g["stats"]["documents"] == 0

    def test_single_paper_still_produces_a_node(self, wire):
        wire.seed("d1", [[1.0, 0.0]], title="Only Paper")
        g = build_graph()
        assert len(g["nodes"]) == 1
        assert g["nodes"][0]["title"] == "Only Paper"
        assert g["edges"] == []

    def test_node_carries_chunk_count_and_metadata(self, wire):
        wire.seed("d1", [[1.0, 0.0], [0.9, 0.1], [0.8, 0.2]], title="Three Chunks")
        node = build_graph()["nodes"][0]
        assert node["chunks"] == 3
        assert node["title"] == "Three Chunks"

    def test_centroid_is_the_mean_of_its_chunks(self, wire):
        """Two papers whose chunks interleave must still separate by centroid."""
        wire.seed("d1", [[1.0, 0.0], [1.0, 0.0]])
        wire.seed("d2", [[0.0, 1.0], [0.0, 1.0]])
        wire.seed("d3", [[1.0, 1.0], [1.0, 1.0]])
        nodes = {n["doc_id"]: (n["x"], n["y"]) for n in build_graph()["nodes"]}
        assert len(nodes) == 3
        assert len(set(nodes.values())) == 3       # no two papers stacked

    def test_summary_and_claims_come_from_the_cache(self, wire):
        wire.seed("d1", [[1.0, 0.0]])
        wire.cache.entries["d1"] = {
            "summary": "a summary", "claims": [{"text": "c", "type": "finding"}],
        }
        node = build_graph()["nodes"][0]
        assert node["summary"] == "a summary"
        assert node["claims"][0]["type"] == "finding"
        assert build_graph()["stats"]["analyzed"] == 1

    def test_unanalyzed_paper_has_empty_summary_not_missing_key(self, wire):
        wire.seed("d1", [[1.0, 0.0]])
        assert build_graph()["nodes"][0]["summary"] == ""

    def test_themes_come_from_the_newest_theme_run(self, wire):
        wire.seed("d1", [[1.0, 0.0]])
        wire.seed("d2", [[0.0, 1.0]])
        wire.analysis.add({"type": "themes", "doc_ids": ["d1"], "result": {
            "themes": [{"theme_id": "t0", "label": "Old", "doc_ids": ["d1"]}]}})
        wire.analysis.add({"type": "themes", "doc_ids": ["d1", "d2"], "result": {
            "themes": [{"theme_id": "t1", "label": "New", "doc_ids": ["d1", "d2"]}]}})
        themes = build_graph()["themes"]
        assert [t["label"] for t in themes] == ["New"]

    def test_non_theme_runs_are_ignored(self, wire):
        wire.seed("d1", [[1.0, 0.0]])
        wire.analysis.add({"type": "themes", "doc_ids": ["d1"], "result": {
            "themes": [{"theme_id": "t1", "label": "Themes", "doc_ids": ["d1"]}]}})
        wire.analysis.add({"type": "claims", "doc_ids": ["d1"], "result": {"claims": []}})
        assert [t["label"] for t in build_graph()["themes"]] == ["Themes"]

    def test_theme_referring_only_to_deleted_papers_is_dropped(self, wire):
        """A hull around a node that is not on the canvas cannot be drawn."""
        wire.seed("d1", [[1.0, 0.0]])
        wire.analysis.add({"type": "themes", "doc_ids": ["gone"], "result": {
            "themes": [{"theme_id": "t1", "label": "Ghost", "doc_ids": ["gone"]}]}})
        assert build_graph()["themes"] == []

    def test_gaps_come_from_the_newest_scan_with_suggestions_attached(self, wire):
        wire.seed("d1", [[1.0, 0.0]])
        wire.seed("d2", [[0.0, 1.0]])
        wire.gaps.add({
            "gaps": [{"gap_id": "g1", "gap_type": "missing_validation",
                      "severity": "high", "description": "no external cohort",
                      "evidence": ["e1"], "related_doc_ids": ["d1", "d2"]}],
            "suggestions": [
                {"title": "Replicate", "description": "multi-site", "related_gaps": ["g1"]},
                {"title": "Unrelated", "description": "x", "related_gaps": ["g9"]},
            ],
        })
        gap = build_graph()["gaps"][0]
        assert gap["severity"] == "high"
        assert gap["doc_ids"] == ["d1", "d2"]
        # linked by related_gaps, not by position -- the old UI matched by index
        assert [s["title"] for s in gap["suggestions"]] == ["Replicate"]

    def test_gap_doc_ids_are_filtered_to_live_papers(self, wire):
        wire.seed("d1", [[1.0, 0.0]])
        wire.gaps.add({"gaps": [{"gap_id": "g1", "related_doc_ids": ["d1", "deleted"]}],
                       "suggestions": []})
        assert build_graph()["gaps"][0]["doc_ids"] == ["d1"]

    def test_no_runs_yet_yields_empty_layers_not_an_error(self, wire):
        wire.seed("d1", [[1.0, 0.0]])
        g = build_graph()
        assert g["themes"] == [] and g["gaps"] == []
        assert g["nodes"]                      # the map still renders

    def test_positions_are_deterministic_across_calls(self, wire):
        for i in range(5):
            wire.seed(f"d{i}", [[float(i), float(i % 3), 1.0]])
        first = [(n["doc_id"], n["x"], n["y"]) for n in build_graph()["nodes"]]
        second = [(n["doc_id"], n["x"], n["y"]) for n in build_graph()["nodes"]]
        assert first == second
