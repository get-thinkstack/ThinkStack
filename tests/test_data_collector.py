"""unit tests for domain.fine_tuning.data_collector (training-pair capture).

writes to an isolated tmp training dir. covers the jsonl append format, export
round-trip, per-task stats, and that a corrupt line is skipped rather than
crashing the export.
"""


import pytest

from domain.fine_tuning import data_collector


@pytest.fixture
def training_dir(tmp_path, monkeypatch):
    d = tmp_path / "training"
    monkeypatch.setattr(data_collector, "TRAINING_DIR", d)
    return d


class TestSaveAndExport:
    def test_save_writes_jsonl_line(self, training_dir):
        data_collector.save_latex_pair(
            prompt="write intro", system="sys", generated_latex="\\section{Intro}",
        )
        rows = data_collector.export_training_data("latex_generation")
        assert len(rows) == 1
        msgs = rows[0]["messages"]
        assert [m["role"] for m in msgs] == ["system", "user", "assistant"]
        assert msgs[2]["content"] == "\\section{Intro}"

    def test_metadata_lengths_recorded(self, training_dir):
        data_collector.save_latex_pair(
            prompt="p", system="s", generated_latex="out",
            current_source="12345", grounding_context="ctx",
        )
        meta = data_collector.export_training_data("latex_generation")[0]["metadata"]
        assert meta["source_length"] == 5
        assert meta["grounding_length"] == 3
        assert meta["output_length"] == 3

    def test_appends_multiple(self, training_dir):
        for i in range(3):
            data_collector.save_latex_pair(prompt=f"p{i}", system="s", generated_latex=f"o{i}")
        assert len(data_collector.export_training_data("latex_generation")) == 3

    def test_gap_analysis_goes_to_own_dataset(self, training_dir):
        data_collector.save_gap_analysis_pair("paper text", "sys", '{"gaps": []}')
        assert data_collector.export_training_data("gap_analysis")
        assert data_collector.export_training_data("latex_generation") == []

    def test_export_missing_dataset_is_empty(self, training_dir):
        assert data_collector.export_training_data("nonexistent") == []

    def test_corrupt_line_is_skipped(self, training_dir):
        data_collector.save_latex_pair(prompt="p", system="s", generated_latex="o")
        # append a broken line directly
        with open(training_dir / "latex_generation.jsonl", "a") as f:
            f.write("{ not valid json\n")
        rows = data_collector.export_training_data("latex_generation")
        assert len(rows) == 1  # the good row survives; the broken one is dropped


class TestTrainingStats:
    def test_counts_per_task(self, training_dir):
        data_collector.save_latex_pair(prompt="p", system="s", generated_latex="o")
        data_collector.save_latex_pair(prompt="p2", system="s", generated_latex="o2")
        data_collector.save_gap_analysis_pair("x", "s", "{}")
        stats = data_collector.training_stats()
        assert stats["latex_generation"] == 2
        assert stats["gap_analysis"] == 1

    def test_empty_stats(self, training_dir):
        assert data_collector.training_stats() == {}
