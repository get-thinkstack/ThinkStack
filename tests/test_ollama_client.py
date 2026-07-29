"""unit tests for infrastructure.ollama_client (no model loading).

covers the pure/deterministic logic: json extraction from noisy model output,
the hardware-budget fit check, and specification-based task->model routing with
graceful downgrade. no real gguf is loaded — _get_llama / generation are not
exercised here (they are the `heavy` tier).
"""

import pytest

from config import settings
from infrastructure import hardware
from domain.model_manager import discovery
from infrastructure.ollama_client import OllamaClient, _extract_json_text

ANALYSIS = settings.llm_analysis_model  # e.g. qwen2.5-1.5b-instruct-q4_k_m.gguf
BASE = "qwen2.5-0.5b-instruct-q4_k_m.gguf"


class TestExtractJsonText:
    def test_plain_object_untouched(self):
        assert _extract_json_text('{"a": 1}') == '{"a": 1}'

    def test_strips_json_code_fence(self):
        assert _extract_json_text('```json\n{"a": 1}\n```') == '{"a": 1}'

    def test_strips_bare_code_fence(self):
        assert _extract_json_text('```\n{"a": 1}\n```') == '{"a": 1}'

    def test_drops_conversational_preamble(self):
        raw = 'Sure, here is the JSON:\n{"a": 1}'
        assert _extract_json_text(raw) == '{"a": 1}'

    def test_narrows_to_outermost_object(self):
        assert _extract_json_text('noise {"a": {"b": 2}} trailing') == '{"a": {"b": 2}}'

    def test_handles_array_payload(self):
        assert _extract_json_text('prefix [1, 2, 3] suffix') == '[1, 2, 3]'

    # ── edge cases ──
    def test_empty_string(self):
        assert _extract_json_text("") == ""

    def test_none_is_treated_as_empty(self):
        assert _extract_json_text(None) == ""

    def test_no_json_returns_stripped_text(self):
        assert _extract_json_text("  just words  ") == "just words"


@pytest.fixture
def client(gguf_dir, monkeypatch):
    """an OllamaClient pointed at a temp models dir with a base + analysis gguf.

    base is 0.4 GB, analysis is 1.1 GB. the hardware budget is monkeypatched per
    test so routing decisions are deterministic and machine-independent.
    """
    d, make = gguf_dir
    make(BASE, 400)        # 0.4 GB base model
    make(ANALYSIS, 1100)   # 1.1 GB analysis model
    c = OllamaClient(provider="llama_cpp", model_path=d)
    # make deterministic regardless of any persisted active_model.txt on the box
    c.model_path = d
    return c


def _set_budget(monkeypatch, gb: float):
    monkeypatch.setattr(hardware, "max_safe_model_size_gb", lambda *a, **k: gb)


class TestFitsBudget:
    def test_unknown_budget_always_fits(self, client, gguf_dir):
        d, _ = gguf_dir
        assert client._fits_budget(d / ANALYSIS, 0.0) is True

    def test_within_budget(self, client, gguf_dir):
        d, _ = gguf_dir
        assert client._fits_budget(d / ANALYSIS, 2.0) is True

    def test_over_budget(self, client, gguf_dir):
        d, _ = gguf_dir
        assert client._fits_budget(d / ANALYSIS, 0.5) is False


class TestSpecBasedRouting:
    def test_analysis_model_used_when_it_fits(self, client, monkeypatch):
        _set_budget(monkeypatch, 10.0)  # roomy machine
        path = client._resolve_task_model_path("analysis")
        assert path.name == ANALYSIS

    def test_downgrades_to_base_when_analysis_too_big(self, client, monkeypatch):
        _set_budget(monkeypatch, 0.5)  # only ~0.5 GB free budget
        path = client._resolve_task_model_path("analysis")
        assert path.name == BASE  # gracefully downgraded, no oom attempt on 1.5b

    def test_general_task_uses_base(self, client, monkeypatch):
        _set_budget(monkeypatch, 10.0)
        path = client._resolve_task_model_path("general")
        assert path.name == BASE

    def test_unknown_budget_does_not_block_task_model(self, client, monkeypatch):
        _set_budget(monkeypatch, 0.0)  # budget unknown -> attempt the good model
        path = client._resolve_task_model_path("analysis")
        assert path.name == ANALYSIS


class TestTaskModelMap:
    def test_has_expected_task_keys(self):
        assert set(OllamaClient.TASK_MODEL_MAP) >= {
            "latex_writer", "analysis", "gap_analysis", "general",
        }

    def test_general_has_no_dedicated_model(self):
        assert OllamaClient.TASK_MODEL_MAP["general"] == []


class TestReusesModelsAlreadyOnTheMachine:
    """the loader must use weights the user already has, not re-acquire them.

    Bug found by Aditya: discovery knew about models installed via LM Studio (or
    a previous download) but the loader only ever looked in ThinkStack's own
    directory, so an analysis task silently degraded to the base model - or
    offered a 1.1 GB download - while the identical weights sat on disk under
    another runtime's naming convention.
    """

    def _client_with_only_base(self, tmp_path):
        our = tmp_path / "models"
        our.mkdir()
        (our / BASE).write_bytes(b"x" * 1000)
        c = OllamaClient(provider="llama_cpp", model_path=our)
        c.model_path = our
        return c, our

    def test_uses_lm_studio_copy_instead_of_degrading(self, tmp_path, monkeypatch):
        c, _ = self._client_with_only_base(tmp_path)
        lms = tmp_path / "lmstudio"
        lms.mkdir()
        # LM Studio's naming for the same weights our catalog calls
        # qwen2.5-1.5b-instruct-q4_k_m.gguf
        external = lms / "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf"
        external.write_bytes(b"y" * 1000)
        monkeypatch.setattr(discovery, "_lmstudio_roots", lambda: [lms])

        got = c._resolve_task_model_path("analysis")
        assert got == external, "should load the copy the user already has"

    def test_falls_back_to_base_when_nothing_external_matches(self, tmp_path, monkeypatch):
        c, _ = self._client_with_only_base(tmp_path)
        lms = tmp_path / "lmstudio"
        lms.mkdir()
        (lms / "llama3.2-3b-instruct-q4_k_m.gguf").write_bytes(b"z" * 1000)  # unrelated
        monkeypatch.setattr(discovery, "_lmstudio_roots", lambda: [lms])

        got = c._resolve_task_model_path("analysis")
        assert got.name == BASE, "an unrelated external model must not be used"

    def test_missing_external_lookup_never_breaks_loading(self, tmp_path, monkeypatch):
        c, _ = self._client_with_only_base(tmp_path)
        def boom():
            raise OSError("permission denied")
        monkeypatch.setattr(discovery, "_lmstudio_roots", boom)
        # a failing bonus lookup must degrade to the base model, not raise
        assert c._resolve_task_model_path("analysis").name == BASE
