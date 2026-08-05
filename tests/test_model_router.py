"""task -> model routing, with every dependency injected.

No hardware, no llama.cpp, no settings. The budget is a float we pass in and
the external finder is a lambda, which is the entire point of moving this out
of ``OllamaClient``: routing decisions are now cheap to state and cheap to
assert, so the precedence rules can be pinned down exhaustively instead of
inferred from log lines.

The most important test in this file is
``TestRegressionAgainstTodaysBehaviour`` -- an empty registry must route exactly
the way the app routed before any of this existed. That is what makes the
extraction safe to land while a beta is in testers' hands.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from domain.model_manager.manifest import BundledManifest, BundledModel
from domain.model_manager.registry import GGUF_MAGIC, ModelEntry, Registry
from domain.model_manager.router import collect_candidates, resolve


def gguf(path: Path, size_mb: float = 1.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(GGUF_MAGIC)
        f.write(b"\0" * max(0, int(size_mb * 1024 * 1024) - 4))
    return path


def reg(*entries: ModelEntry) -> Registry:
    return Registry(models=list(entries))


EMPTY_MANIFEST = BundledManifest()


def manifest(*models: BundledModel) -> BundledManifest:
    return BundledManifest(models=models)


class TestPrecedence:
    def test_user_assignment_beats_everything(self, tmp_path):
        mine = gguf(tmp_path / "mine.gguf")
        bundled = gguf(tmp_path / "bundled.gguf")
        r = reg(
            ModelEntry(id="mine", path=str(mine), label="Mine",
                       tasks=("analysis",), user_assigned=True),
        )
        m = manifest(BundledModel(id="b", file="bundled.gguf", tasks=("analysis",)))

        out = resolve("analysis", registry=r, manifest=m, models_dir=tmp_path,
                      base_model=bundled)
        assert out.path == mine
        assert out.source == "registry-user"

    def test_manifest_assignment_beats_bundled_and_legacy(self, tmp_path):
        via_manifest = gguf(tmp_path / "via-manifest.gguf")
        gguf(tmp_path / "legacy.gguf")
        r = reg(ModelEntry(id="vm", path=str(via_manifest), label="VM",
                           tasks=("analysis",), user_assigned=False))

        out = resolve("analysis", registry=r, manifest=EMPTY_MANIFEST,
                      models_dir=tmp_path, legacy_defaults=["legacy.gguf"])
        assert out.path == via_manifest
        assert out.source == "registry-manifest"

    def test_bundled_beats_legacy(self, tmp_path):
        gguf(tmp_path / "bundled.gguf")
        gguf(tmp_path / "legacy.gguf")
        m = manifest(BundledModel(id="b", file="bundled.gguf", tasks=("analysis",)))

        out = resolve("analysis", registry=reg(), manifest=m, models_dir=tmp_path,
                      legacy_defaults=["legacy.gguf"])
        assert out.path.name == "bundled.gguf"
        assert out.source == "bundled"

    def test_legacy_is_used_when_nothing_else_claims_the_task(self, tmp_path):
        gguf(tmp_path / "legacy.gguf")
        out = resolve("analysis", registry=reg(), manifest=EMPTY_MANIFEST,
                      models_dir=tmp_path, legacy_defaults=["legacy.gguf"])
        assert out.path.name == "legacy.gguf"
        assert out.source == "legacy"

    def test_base_model_is_the_floor(self, tmp_path):
        base = gguf(tmp_path / "base.gguf")
        out = resolve("analysis", registry=reg(), manifest=EMPTY_MANIFEST,
                      models_dir=tmp_path, base_model=base)
        assert out.path == base
        assert out.source == "base"

    def test_nothing_at_all_resolves_to_nothing_rather_than_raising(self, tmp_path):
        out = resolve("analysis", registry=reg(), manifest=EMPTY_MANIFEST,
                      models_dir=tmp_path)
        assert out.path is None
        assert out.resolved is False
        assert "no model" in out.reason


class TestExistence:
    def test_a_registered_model_whose_file_vanished_is_skipped(self, tmp_path):
        base = gguf(tmp_path / "base.gguf")
        r = reg(ModelEntry(id="gone", path=str(tmp_path / "gone.gguf"),
                           label="Gone", tasks=("analysis",), user_assigned=True))
        out = resolve("analysis", registry=r, manifest=EMPTY_MANIFEST,
                      models_dir=tmp_path, base_model=base)
        assert out.path == base, "a deleted model must not win the route"

    def test_a_manifest_entry_with_no_file_on_disk_is_skipped(self, tmp_path):
        base = gguf(tmp_path / "base.gguf")
        m = manifest(BundledModel(id="b", file="never-copied.gguf", tasks=("analysis",)))
        out = resolve("analysis", registry=reg(), manifest=m,
                      models_dir=tmp_path, base_model=base)
        assert out.path == base

    def test_the_same_file_claimed_twice_is_considered_once(self, tmp_path):
        p = gguf(tmp_path / "dup.gguf")
        r = reg(
            ModelEntry(id="a", path=str(p), label="A", tasks=("analysis",), user_assigned=True),
            ModelEntry(id="b", path=str(p), label="B", tasks=("analysis",), user_assigned=False),
        )
        cands = collect_candidates("analysis", registry=r, manifest=EMPTY_MANIFEST,
                                   models_dir=tmp_path)
        assert len(cands) == 1


class TestBudget:
    def test_a_model_too_large_is_skipped_for_the_base(self, tmp_path):
        base = gguf(tmp_path / "base.gguf", size_mb=1)
        big = gguf(tmp_path / "big.gguf", size_mb=64)      # 0.0625 GB, measured
        r = reg(ModelEntry(id="big", path=str(big), label="Big",
                           tasks=("analysis",), user_assigned=True))

        out = resolve("analysis", registry=r, manifest=EMPTY_MANIFEST,
                      models_dir=tmp_path, budget_gb=0.01, base_model=base)
        assert out.path == base
        assert out.source == "base"

    def test_the_downgrade_is_explained_not_silent(self, tmp_path):
        # the whole reason Resolution carries a reason: the user needs to know
        # WHY their summaries got worse.
        base = gguf(tmp_path / "base.gguf", size_mb=1)
        big = gguf(tmp_path / "big.gguf", size_mb=64)
        r = reg(ModelEntry(id="big", path=str(big), label="Big",
                           tasks=("analysis",), user_assigned=True))

        out = resolve("analysis", registry=r, manifest=EMPTY_MANIFEST,
                      models_dir=tmp_path, budget_gb=0.01, base_model=base)
        assert out.downgraded_from == "big.gguf"
        assert "big.gguf" in out.reason

    def test_an_unknown_budget_never_blocks_a_load(self, tmp_path):
        big = gguf(tmp_path / "big.gguf")
        r = reg(ModelEntry(id="big", path=str(big), label="Big", size_gb=99.0,
                           tasks=("analysis",), user_assigned=True))
        out = resolve("analysis", registry=r, manifest=EMPTY_MANIFEST,
                      models_dir=tmp_path, budget_gb=0.0)
        assert out.path == big, "budget 0 means unmeasured, not zero memory"

    def test_measured_size_wins_over_a_stale_declared_size(self, tmp_path):
        # the user swapped the file for a smaller quant without re-importing
        base = gguf(tmp_path / "base.gguf")
        small = gguf(tmp_path / "m.gguf", size_mb=2)
        r = reg(ModelEntry(id="m", path=str(small), label="M", size_gb=99.0,
                           tasks=("analysis",), user_assigned=True))
        out = resolve("analysis", registry=r, manifest=EMPTY_MANIFEST,
                      models_dir=tmp_path, budget_gb=0.5, base_model=base)
        assert out.path == small, "size must be measured, not trusted"

    def test_the_base_model_is_not_budget_checked(self, tmp_path):
        # if the floor does not fit there is nothing below it; refusing to try
        # guarantees failure where attempting might succeed.
        base = gguf(tmp_path / "base.gguf", size_mb=64)
        out = resolve("analysis", registry=reg(), manifest=EMPTY_MANIFEST,
                      models_dir=tmp_path, budget_gb=0.01, base_model=base)
        assert out.path == base


class TestExternalAndOllama:
    def test_legacy_names_resolve_through_the_external_finder(self, tmp_path):
        # the user has these weights via LM Studio under a different filename
        elsewhere = gguf(tmp_path / "lmstudio" / "Qwen2.5-1.5B-Q4.gguf")
        out = resolve("analysis", registry=reg(), manifest=EMPTY_MANIFEST,
                      models_dir=tmp_path / "models",
                      legacy_defaults=["qwen2.5-1.5b-instruct-q4_k_m.gguf"],
                      external_finder=lambda name: elsewhere)
        assert out.path == elsewhere

    def test_ollama_is_consulted_only_when_nothing_loads_from_disk(self, tmp_path):
        on_disk = gguf(tmp_path / "m.gguf")
        r = reg(ModelEntry(id="m", path=str(on_disk), label="M",
                           tasks=("analysis",), user_assigned=True))
        out = resolve("analysis", registry=r, manifest=EMPTY_MANIFEST,
                      models_dir=tmp_path,
                      ollama_lookup=lambda t: pytest.fail("must not ask Ollama"))
        assert out.path == on_disk

    def test_ollama_serves_when_disk_has_nothing(self, tmp_path):
        out = resolve("analysis", registry=reg(), manifest=EMPTY_MANIFEST,
                      models_dir=tmp_path, ollama_lookup=lambda t: "qwen2.5:1.5b")
        assert out.ollama_tag == "qwen2.5:1.5b"
        assert out.path is None
        assert out.resolved is True

    def test_the_base_model_beats_ollama_only_if_ollama_declines(self, tmp_path):
        base = gguf(tmp_path / "base.gguf")
        out = resolve("analysis", registry=reg(), manifest=EMPTY_MANIFEST,
                      models_dir=tmp_path, base_model=base,
                      ollama_lookup=lambda t: None)
        assert out.path == base


class TestRegressionAgainstTodaysBehaviour:
    """an empty registry must route exactly as the app routed before this existed.

    This is the guard that makes extracting routing out of OllamaClient safe to
    land with a beta in testers' hands. If any of these change, the refactor
    altered behaviour and that is a bug, not an improvement.
    """

    def test_analysis_uses_the_analysis_model_when_present_and_fitting(self, tmp_path):
        analysis = gguf(tmp_path / "qwen2.5-1.5b-instruct-q4_k_m.gguf")
        base = gguf(tmp_path / "qwen2.5-0.5b-instruct-q4_k_m.gguf")
        out = resolve("analysis", registry=reg(), manifest=EMPTY_MANIFEST,
                      models_dir=tmp_path, budget_gb=4.0, base_model=base,
                      legacy_defaults=["qwen2.5-1.5b-instruct-q4_k_m.gguf"])
        assert out.path == analysis

    def test_analysis_falls_back_to_base_when_the_analysis_model_is_absent(self, tmp_path):
        base = gguf(tmp_path / "qwen2.5-0.5b-instruct-q4_k_m.gguf")
        out = resolve("analysis", registry=reg(), manifest=EMPTY_MANIFEST,
                      models_dir=tmp_path, budget_gb=4.0, base_model=base,
                      legacy_defaults=["qwen2.5-1.5b-instruct-q4_k_m.gguf"])
        assert out.path == base

    def test_general_always_uses_the_base_model(self, tmp_path):
        base = gguf(tmp_path / "base.gguf")
        gguf(tmp_path / "qwen2.5-1.5b-instruct-q4_k_m.gguf")
        # TASK_MODEL_MAP["general"] is [] -- no candidates, straight to base
        out = resolve("general", registry=reg(), manifest=EMPTY_MANIFEST,
                      models_dir=tmp_path, budget_gb=4.0, base_model=base,
                      legacy_defaults=[])
        assert out.path == base

    def test_a_too_large_analysis_model_degrades_exactly_as_before(self, tmp_path):
        gguf(tmp_path / "qwen2.5-1.5b-instruct-q4_k_m.gguf", size_mb=64)
        base = gguf(tmp_path / "qwen2.5-0.5b-instruct-q4_k_m.gguf", size_mb=1)
        out = resolve("analysis", registry=reg(), manifest=EMPTY_MANIFEST,
                      models_dir=tmp_path, budget_gb=0.01, base_model=base,
                      legacy_defaults=["qwen2.5-1.5b-instruct-q4_k_m.gguf"])
        assert out.path == base
        assert out.downgraded_from == "qwen2.5-1.5b-instruct-q4_k_m.gguf"


class TestCandidateOrdering:
    def test_collect_reports_order_without_applying_the_budget(self, tmp_path):
        # existence is filtered here, budget is not -- so the caller can tell
        # "nothing is set up" apart from "what is set up does not fit".
        a = gguf(tmp_path / "a.gguf")
        b = gguf(tmp_path / "b.gguf")
        r = reg(
            ModelEntry(id="a", path=str(a), label="A", size_gb=99.0,
                       tasks=("analysis",), user_assigned=True),
            ModelEntry(id="b", path=str(b), label="B", size_gb=99.0,
                       tasks=("analysis",), user_assigned=False),
        )
        cands = collect_candidates("analysis", registry=r, manifest=EMPTY_MANIFEST,
                                   models_dir=tmp_path)
        assert [c.source for c in cands] == ["registry-user", "registry-manifest"]
