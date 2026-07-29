"""unit tests for config.Settings.

verifies the offline-first defaults and the THINKSTACK_-prefixed env overrides.
a fresh Settings() is constructed per assertion so the process-wide singleton is
never mutated.
"""

from config import Settings


class TestDefaults:
    def test_offline_first_defaults(self):
        s = Settings()
        assert s.llm_provider == "llama_cpp"
        assert s.chunk_size == 512
        assert s.chunk_overlap == 50
        assert s.port == 8000

    def test_analysis_model_is_the_heavier_gguf(self):
        assert "1.5b" in Settings().llm_analysis_model

    def test_gpu_layers_default_is_auto(self):
        assert Settings().llm_gpu_layers == -1  # -1 = auto-detect


class TestEnvOverrides:
    def test_prefixed_env_overrides_int(self, monkeypatch):
        monkeypatch.setenv("THINKSTACK_CHUNK_SIZE", "256")
        assert Settings().chunk_size == 256

    def test_prefixed_env_overrides_gpu_layers(self, monkeypatch):
        monkeypatch.setenv("THINKSTACK_LLM_GPU_LAYERS", "0")
        assert Settings().llm_gpu_layers == 0

    def test_unprefixed_env_is_ignored(self, monkeypatch):
        # a bare CHUNK_SIZE (no THINKSTACK_ prefix) must not leak into settings
        monkeypatch.setenv("CHUNK_SIZE", "999")
        assert Settings().chunk_size == 512

    def test_unknown_env_is_ignored_not_error(self, monkeypatch):
        # extra=ignore: an unrelated prefixed var must not raise
        monkeypatch.setenv("THINKSTACK_TOTALLY_UNKNOWN", "x")
        assert Settings().chunk_size == 512
