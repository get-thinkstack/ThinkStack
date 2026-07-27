"""unit tests for the model catalog and on-machine model discovery.

these decide whether the app prompts a user to download a gigabyte of weights,
so the important cases are the negative ones: never offer a model the machine
cannot run, and never offer one the user already has (via ThinkStack, Ollama, or
LM Studio). every probe must also degrade to "found nothing" rather than raise.
"""

import json

from domain.model_manager import discovery
from domain.model_manager.catalog import (
    ANALYSIS_MODEL,
    BASE_MODEL,
    CATALOG,
    bundled_models,
    by_name,
    optional_models,
    runnable_on,
    suggested_upgrade,
)
from domain.model_manager.discovery import (
    DiscoveredModel,
    discover_all,
    find_lmstudio_models,
    find_ollama_on_disk,
    find_ollama_running,
    find_thinkstack_models,
    installed_names,
)


class TestCatalog:
    def test_baseline_is_bundled_so_app_works_offline(self):
        assert BASE_MODEL.bundled is True
        assert bundled_models() == [BASE_MODEL]

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

    def test_unknown_budget_falls_back_to_bundled_only(self):
        # 0 == "could not measure"; never assume a big model is safe
        assert runnable_on(0.0) == [BASE_MODEL]

    def test_exact_boundary_is_inclusive(self):
        assert ANALYSIS_MODEL in runnable_on(ANALYSIS_MODEL.min_ram_gb)


class TestSuggestedUpgrade:
    def test_offers_analysis_model_on_capable_machine(self):
        assert suggested_upgrade(8.0, installed={BASE_MODEL.name}) is ANALYSIS_MODEL

    def test_no_offer_when_machine_too_small(self):
        assert suggested_upgrade(1.0, installed={BASE_MODEL.name}) is None

    def test_no_offer_when_already_installed(self):
        installed = {BASE_MODEL.name, ANALYSIS_MODEL.name}
        assert suggested_upgrade(16.0, installed=installed) is None

    def test_no_offer_when_budget_unknown(self):
        assert suggested_upgrade(0.0, installed=set()) is None

    def test_picks_the_most_capable_that_fits(self):
        got = suggested_upgrade(16.0, installed=set())
        assert got is ANALYSIS_MODEL  # largest optional model that fits


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
        assert suggested_upgrade(16.0, installed_names(found)) is None

    def test_prompt_appears_when_nothing_comparable_is_installed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(discovery, "find_ollama_running", lambda _u: [])
        monkeypatch.setattr(discovery, "find_ollama_on_disk", lambda: [])
        monkeypatch.setattr(discovery, "find_lmstudio_models", lambda: [])
        found = discover_all(tmp_path, "http://localhost:11434")
        assert suggested_upgrade(16.0, installed_names(found)) is ANALYSIS_MODEL
