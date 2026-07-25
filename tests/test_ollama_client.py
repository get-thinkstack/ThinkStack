"""unit tests for infrastructure.ollama_client (no model loading).

covers the pure/deterministic logic: json extraction from noisy model output,
the hardware-budget fit check, and specification-based task->model routing with
graceful downgrade. no real gguf is loaded — _get_llama / generation are not
exercised here (they are the `heavy` tier).
"""

import pytest

from config import settings
from infrastructure import hardware
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
