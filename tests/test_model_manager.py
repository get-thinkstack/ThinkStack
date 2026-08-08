"""unit tests for the model catalog and on-machine model discovery.

these decide whether the app prompts a user to download a gigabyte of weights,
so the important cases are the negative ones: never offer a model the machine
cannot run, and never offer one the user already has (via ThinkStack, Ollama, or
LM Studio). every probe must also degrade to "found nothing" rather than raise.
"""

import json

import pytest

from domain.model_manager import discovery
from domain.model_manager.catalog import (
    ANALYSIS_MODEL,
    CPU_COMFORTABLE_GB,
    BASE_MODEL,
    CATALOG,
    bundled_models,
    by_name,
    optional_models,
    runnable_on,
    suggested_upgrade,
)
from domain.model_manager.discovery import (
    model_key,
    DiscoveredModel,
    discover_all,
    find_lmstudio_models,
    find_ollama_on_disk,
    find_ollama_running,
    find_thinkstack_models,
    installed_names,
)


class TestCatalog:
    def test_exactly_one_model_is_bundled(self):
        # more than one and the installer carries weight nobody asked for;
        # none and a fresh offline install cannot do anything at all.
        assert len(bundled_models()) == 1

    def test_the_bundled_model_needs_no_particular_machine(self):
        # it ships to every user, so it cannot have a memory floor some of
        # them fail to clear.
        assert bundled_models()[0].min_ram_gb == 0.0

    def test_the_bundled_model_is_the_smallest_thing_we_offer(self):
        # it is chosen to run anywhere; anything we would suggest INSTEAD is
        # an upgrade, and an upgrade that is smaller is a contradiction.
        assert bundled_models()[0].size_gb == min(s.size_gb for s in CATALOG)

    def test_analysis_model_is_optional_not_shipped(self):
        assert ANALYSIS_MODEL.bundled is False
        assert ANALYSIS_MODEL in optional_models()

    def test_lookup_by_name(self):
        assert by_name(BASE_MODEL.name) is BASE_MODEL
        assert by_name("nope.gguf") is None

    def test_every_optional_model_has_a_download_url(self):
        assert all(s.url.startswith("https://") for s in optional_models())

    def test_baseline_has_no_ram_floor(self):
        # must be offerable on the weakest machine
        assert BASE_MODEL.min_ram_gb == 0.0


class TestRunnableOn:
    def test_roomy_machine_can_run_everything(self):
        assert set(runnable_on(16.0)) == set(CATALOG)

    def test_tight_machine_gets_only_the_baseline(self):
        assert runnable_on(1.0) == [BASE_MODEL]

    def test_unknown_budget_falls_back_to_the_lightest_only(self):
        # 0 == "could not measure"; never assume a big model is safe
        assert runnable_on(0.0) == [BASE_MODEL]

    def test_exact_boundary_is_inclusive(self):
        assert ANALYSIS_MODEL in runnable_on(ANALYSIS_MODEL.min_ram_gb)


class TestSuggestedUpgrade:
    """What to offer, given BOTH hardware constraints.

    `min_ram_gb` asks whether the weights fit; `good_on_tiers` asks whether
    running them here is a good experience. A 4B fits a 16 GB budget and is
    still a poor suggestion for a low-tier laptop, where it produces a summary
    every few minutes -- and a user who takes that suggestion concludes the app
    is broken.
    """

    def test_offers_a_structured_output_model_on_a_capable_machine(self):
        # the 0.5B cannot emit reliable json; anything offered must fix that
        got = suggested_upgrade(8.0, installed={BASE_MODEL.name}, tier="medium")
        assert got is not None and got is not BASE_MODEL

    def test_no_offer_when_machine_too_small(self):
        assert suggested_upgrade(1.0, installed={BASE_MODEL.name}) is None

    def test_no_offer_when_everything_runnable_is_installed(self):
        installed = {s.name for s in CATALOG}
        assert suggested_upgrade(16.0, installed=installed) is None

    def test_no_offer_when_the_budget_could_not_be_measured(self):
        # A machine already has the bundled model, so an unmeasurable one is
        # not stranded -- and suggesting a download we cannot size against its
        # memory is how someone ends up with weights that will not load.
        assert suggested_upgrade(0.0, installed=set()) is None

    def test_with_acceleration_the_most_capable_that_fits_wins(self):
        got = suggested_upgrade(16.0, installed=set(), gpu_gb=12.0)
        assert got is max(
            (s for s in CATALOG if not s.bundled and s.tasks),
            key=lambda s: (s.quality, s.size_gb),
        )

    def test_without_acceleration_size_is_capped_however_much_ram_there_is(self):
        """The bug this exists to prevent.

        A machine with no GPU the engine can use has plenty of room for a 4B
        and would take minutes per summary running it. Memory was the only
        thing consulted, so 20 GB of free RAM produced a 3B suggestion on a
        processor-only machine.
        """
        for budget in (8.0, 16.0, 64.0):
            got = suggested_upgrade(budget, installed=set(), gpu_gb=0.0)
            assert got is not None
            assert got.size_gb <= CPU_COMFORTABLE_GB, (
                f"{got.label} suggested on a CPU-only machine with {budget} GB free"
            )

    def test_acceleration_too_small_for_the_model_does_not_count(self):
        # a 2 GB card cannot hold a 2.33 GB model, so that model still runs on
        # the processor and is still a poor suggestion.
        got = suggested_upgrade(64.0, installed=set(), gpu_gb=2.0)
        assert got is not None and got.size_gb <= max(2.0, CPU_COMFORTABLE_GB)

    def test_tier_excludes_a_model_that_would_merely_FIT(self):
        # 16 GB of budget on a low-tier machine must not produce a 4B, even
        # with acceleration available.
        roomy = suggested_upgrade(16.0, installed=set(), gpu_gb=12.0)
        low = suggested_upgrade(16.0, installed=set(), tier="low", gpu_gb=12.0)
        assert low is not roomy
        assert low is None or low.runs_on_tier("low")

    def test_an_unknown_tier_applies_no_tier_constraint(self):
        # failing to classify the machine must not silence every suggestion
        assert suggested_upgrade(16.0, installed=set(), tier="") is not None

    def test_every_suggestion_respects_the_budget(self):
        for budget in (0.5, 2.0, 3.0, 5.0, 16.0):
            got = suggested_upgrade(budget, installed=set())
            assert got is None or got.min_ram_gb <= budget


class TestFindThinkstackModels:
    def test_finds_gguf_files(self, tmp_path):
        (tmp_path / "a.gguf").write_bytes(b"x" * 10)
        (tmp_path / "b.gguf").write_bytes(b"y" * 10)
        (tmp_path / "notes.txt").write_text("ignore me")
        found = find_thinkstack_models(tmp_path)
        assert {m.name for m in found} == {"a.gguf", "b.gguf"}
        assert all(m.source == "thinkstack" for m in found)
        assert all(m.usable_directly for m in found)

    def test_missing_dir_is_empty_not_error(self, tmp_path):
        assert find_thinkstack_models(tmp_path / "nope") == []


class TestFindOllamaRunning:
    def test_parses_running_server(self, monkeypatch):
        class _Resp:
            def raise_for_status(self): pass
            def json(self):
                return {"models": [{"name": "qwen2.5:1.5b", "size": 1_100_000_000}]}

        import httpx
        monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp())
        found = find_ollama_running("http://localhost:11434")
        assert len(found) == 1
        assert found[0].name == "qwen2.5:1.5b"
        assert found[0].source == "ollama"
        assert found[0].usable_directly is False  # served by ollama, not a file

    def test_server_down_returns_empty(self, monkeypatch):
        import httpx
        def boom(*a, **k):
            raise httpx.ConnectError("refused")
        monkeypatch.setattr(httpx, "get", boom)
        assert find_ollama_running("http://localhost:11434") == []

    def test_garbage_response_returns_empty(self, monkeypatch):
        class _Resp:
            def raise_for_status(self): pass
            def json(self): raise ValueError("not json")
        import httpx
        monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp())
        assert find_ollama_running("http://localhost:11434") == []

    def test_entries_without_a_name_are_skipped(self, monkeypatch):
        class _Resp:
            def raise_for_status(self): pass
            def json(self): return {"models": [{"size": 123}]}
        import httpx
        monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp())
        assert find_ollama_running("http://localhost:11434") == []


class TestFindOllamaOnDisk:
    def _make_manifest(self, root, name, tag, sizes):
        d = root / "manifests" / "registry.ollama.ai" / "library" / name
        d.mkdir(parents=True)
        (d / tag).write_text(json.dumps({"layers": [{"size": s} for s in sizes]}))

    def test_reads_pulled_models(self, tmp_path, monkeypatch):
        self._make_manifest(tmp_path, "qwen2.5", "1.5b", [1_000_000_000, 100_000_000])
        monkeypatch.setenv("OLLAMA_MODELS", str(tmp_path))
        found = find_ollama_on_disk()
        assert [m.name for m in found] == ["qwen2.5:1.5b"]
        assert found[0].source == "ollama-disk"
        assert found[0].size_gb > 0

    def test_unparseable_manifest_still_counts_as_present(self, tmp_path, monkeypatch):
        d = tmp_path / "manifests" / "r" / "l" / "mystery"
        d.mkdir(parents=True)
        (d / "latest").write_text("{ not json")
        monkeypatch.setenv("OLLAMA_MODELS", str(tmp_path))
        found = find_ollama_on_disk()
        assert [m.name for m in found] == ["mystery:latest"]

    def test_no_ollama_dir_is_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OLLAMA_MODELS", str(tmp_path / "absent"))
        assert find_ollama_on_disk() == []


class TestFindLmStudio:
    def test_finds_nested_ggufs(self, tmp_path, monkeypatch):
        root = tmp_path / "lmstudio"
        nested = root / "publisher" / "repo"
        nested.mkdir(parents=True)
        (nested / "model.gguf").write_bytes(b"z" * 10)
        monkeypatch.setattr(discovery, "_lmstudio_roots", lambda: [root])
        found = find_lmstudio_models()
        assert [m.name for m in found] == ["model.gguf"]
        assert found[0].usable_directly is True

    def test_absent_roots_are_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(discovery, "_lmstudio_roots", lambda: [tmp_path / "nope"])
        assert find_lmstudio_models() == []


class TestDiscoverAll:
    def test_combines_sources_and_dedupes(self, tmp_path, monkeypatch):
        (tmp_path / "base.gguf").write_bytes(b"x" * 10)
        monkeypatch.setattr(
            discovery, "find_ollama_running",
            lambda _u: [DiscoveredModel(name="qwen2.5:1.5b", source="ollama")],
        )
        monkeypatch.setattr(discovery, "find_lmstudio_models", lambda: [])
        found = discover_all(tmp_path, "http://localhost:11434")
        assert {m.name for m in found} == {"base.gguf", "qwen2.5:1.5b"}

    def test_disk_scan_skipped_when_server_answered(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            discovery, "find_ollama_running",
            lambda _u: [DiscoveredModel(name="a:1", source="ollama")],
        )
        monkeypatch.setattr(discovery, "find_lmstudio_models", lambda: [])
        called = {"disk": False}
        def _disk():
            called["disk"] = True
            return []
        monkeypatch.setattr(discovery, "find_ollama_on_disk", _disk)
        discover_all(tmp_path, "http://localhost:11434")
        assert called["disk"] is False  # no double-listing

    def test_disk_scan_used_when_server_silent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(discovery, "find_ollama_running", lambda _u: [])
        monkeypatch.setattr(discovery, "find_lmstudio_models", lambda: [])
        monkeypatch.setattr(
            discovery, "find_ollama_on_disk",
            lambda: [DiscoveredModel(name="a:1", source="ollama-disk")],
        )
        found = discover_all(tmp_path, "http://localhost:11434")
        assert [m.name for m in found] == ["a:1"]

    def test_all_sources_failing_yields_empty_not_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(discovery, "find_ollama_running", lambda _u: [])
        monkeypatch.setattr(discovery, "find_ollama_on_disk", lambda: [])
        monkeypatch.setattr(discovery, "find_lmstudio_models", lambda: [])
        assert discover_all(tmp_path / "missing", "http://localhost:11434") == []


class TestInstalledNames:
    def test_normalises_ollama_tags(self):
        names = installed_names([DiscoveredModel(name="qwen2.5:1.5b", source="ollama")])
        assert "qwen2.5:1.5b" in names
        assert "qwen2.5-1.5b" in names  # colon-normalised form

    def test_strips_gguf_suffix(self):
        names = installed_names([DiscoveredModel(name="Model_A.gguf", source="thinkstack")])
        assert "Model_A.gguf" in names
        assert "model-a" in names

    def test_empty_input(self):
        assert installed_names([]) == set()


class TestModelKey:
    """the same weights are named differently by each runtime.

    Comparing raw filenames misses a model the user already has, so we would
    prompt them to download a gigabyte they are already storing. These all have
    to reduce to the same family/size key.
    """

    def test_ollama_tag_and_our_gguf_match(self):
        assert model_key("qwen2.5:1.5b") == model_key("qwen2.5-1.5b-instruct-q4_k_m.gguf")

    def test_lm_studio_capitalised_name_matches(self):
        assert model_key("Qwen2.5-1.5B-Instruct-Q4_K_M.gguf") == model_key("qwen2.5:1.5b")

    def test_quantisation_is_ignored(self):
        # a q4 and a q8 of the same model are the same capability for our purposes
        assert model_key("qwen2.5:1.5b-instruct-q8_0") == model_key("qwen2.5:1.5b")

    def test_different_sizes_do_not_match(self):
        assert model_key("qwen2.5-0.5b-instruct-q4_k_m.gguf") != model_key("qwen2.5:1.5b")

    def test_different_families_do_not_match(self):
        assert model_key("llama3.2:3b") != model_key("qwen2.5:1.5b")

    def test_family_version_is_not_read_as_the_size(self):
        # "qwen2.5" must not be parsed as a 2.5B model
        assert model_key("qwen2.5:1.5b") == "qwen2.5/1.5b"

    def test_name_without_a_size_survives(self):
        assert model_key("mystery-model.gguf") == "mystery-model"


class TestOfferIsSuppressedByExistingModels:
    """the behaviour the user asked for: don't re-download what they already run."""

    def test_ollama_copy_suppresses_the_download_prompt(self, tmp_path, monkeypatch):
        # user already pulled the analysis model through ollama
        monkeypatch.setattr(
            discovery, "find_ollama_running",
            lambda _u: [DiscoveredModel(name=ANALYSIS_MODEL.name, source="ollama")],
        )
        monkeypatch.setattr(discovery, "find_lmstudio_models", lambda: [])
        found = discover_all(tmp_path, "http://localhost:11434")
        assert suggested_upgrade(16.0, installed_names(found)) is not ANALYSIS_MODEL

    @pytest.mark.parametrize("tag", [
        "qwen2.5:1.5b",                      # what ollama actually reports
        "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf", # what lm studio stores
        "qwen2.5:1.5b-instruct-q8_0",        # a different quantisation
    ])
    def test_equivalent_model_under_any_naming_suppresses_the_download(
        self, tag, tmp_path, monkeypatch
    ):
        """the real-world case: re-downloading 1.1 GB the user already has.

        Ollama names it "qwen2.5:1.5b" while our catalog calls it
        "qwen2.5-1.5b-instruct-q4_k_m.gguf"; matching on filename alone missed
        that and offered the download anyway.
        """
        monkeypatch.setattr(
            discovery, "find_ollama_running",
            lambda _u: [DiscoveredModel(name=tag, source="ollama")],
        )
        monkeypatch.setattr(discovery, "find_lmstudio_models", lambda: [])
        found = discover_all(tmp_path, "http://localhost:11434")
        assert suggested_upgrade(16.0, installed_names(found)) is not ANALYSIS_MODEL

    def test_an_unrelated_model_still_gets_the_offer(self, tmp_path, monkeypatch):
        # having llama3.2 says nothing about whether qwen2.5-1.5b is present
        monkeypatch.setattr(
            discovery, "find_ollama_running",
            lambda _u: [DiscoveredModel(name="llama3.2:3b", source="ollama")],
        )
        monkeypatch.setattr(discovery, "find_lmstudio_models", lambda: [])
        found = discover_all(tmp_path, "http://localhost:11434")
        # the point is that an unrelated model does not suppress the offer;
        # accelerated so the choice is not narrowed by the CPU cap.
        got = suggested_upgrade(16.0, installed_names(found), gpu_gb=12.0)
        assert got is not None

    def test_prompt_appears_when_nothing_comparable_is_installed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(discovery, "find_ollama_running", lambda _u: [])
        monkeypatch.setattr(discovery, "find_ollama_on_disk", lambda: [])
        monkeypatch.setattr(discovery, "find_lmstudio_models", lambda: [])
        found = discover_all(tmp_path, "http://localhost:11434")
        # the point is that an unrelated model does not suppress the offer;
        # accelerated so the choice is not narrowed by the CPU cap.
        got = suggested_upgrade(16.0, installed_names(found), gpu_gb=12.0)
        assert got is not None


class TestTheBaselineIsUsableNotJustValid:
    """Guards the Qwen3 trap.

    A reasoning model emits <think> before answering. ollama_client's GBNF
    grammar permits only JSON from the first token, leaving that block nowhere
    to go, so the model closes the object and returns `{}` -- which parses
    perfectly and contains nothing.

    Qwen3 0.6B passed every other check: verified URL, correct size, valid GGUF
    magic, valid JSON. It would have shipped broken on gap finding and Scribe.
    These tests cannot run a model, so they guard the property that IS
    checkable: that we never silently point the bundled slot at a known
    reasoning family.
    """

    # families whose small models emit a reasoning preamble by default
    REASONING_FAMILIES = ("qwen3", "deepseek-r1", "qwq", "marco-o1")

    def test_the_bundled_model_is_not_a_reasoning_model(self):
        for spec in bundled_models():
            low = spec.name.lower()
            for family in self.REASONING_FAMILIES:
                assert family not in low, (
                    f"{spec.name} looks like a {family} reasoning model. Those "
                    f"return empty JSON under the GBNF grammar that gap finding "
                    f"and Scribe rely on. See the note in catalog.py."
                )

    def test_release_config_does_not_bundle_a_reasoning_model(self):
        # the config is what the BUILD reads; catalog.py agreeing is not enough
        import json
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        cfg = json.loads((root / "release.config.json").read_text())
        for m in cfg["models"]:
            url = m if isinstance(m, str) else m.get("url", "")
            for family in self.REASONING_FAMILIES:
                assert family not in url.lower(), (
                    f"release.config.json bundles {url}, which looks like a "
                    f"{family} reasoning model."
                )
