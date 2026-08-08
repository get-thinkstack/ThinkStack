"""unit tests for infrastructure.ollama_client (no model loading).

covers the pure/deterministic logic: json extraction from noisy model output,
the hardware-budget fit check, and specification-based task->model routing with
graceful downgrade. no real gguf is loaded — _get_llama / generation are not
exercised here (they are the `heavy` tier).
"""

import json

import pytest

from config import settings
from infrastructure import hardware
from domain.model_manager import discovery
from infrastructure.ollama_client import (
    OllamaClient,
    _extract_json_text,
    _repair_json,
)

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


def _parsed(raw: str) -> dict:
    """Run the real recovery path an LLM response goes through, then parse."""
    return json.loads(_repair_json(_extract_json_text(raw)))


class TestRepairsTruncatedModelOutput:
    """A small local model hitting max_tokens stops mid-token, not at a
    sensible boundary. That shipped to users as a summary reading
    'summarization failed: Unterminated string starting at: line 9 column 5'.
    Partial output is worth more than an error message, so it is closed off
    and parsed rather than discarded."""

    def test_truncated_mid_string_keeps_the_completed_entries(self):
        raw = (
            '{"summary": "Hybrid retrieval improves recall.", '
            '"key_points": ["BM25 and dense vectors are complementary", '
            '"Quantised models stay accur'
        )
        data = _parsed(raw)
        assert data["summary"] == "Hybrid retrieval improves recall."
        assert "BM25 and dense vectors are complementary" in data["key_points"]

    def test_truncated_after_a_comma_does_not_become_a_bare_list(self):
        # Regression: narrowing to the outermost {...} needed a closing brace,
        # so a truncated object fell through to the array branch and returned
        # key_points as the whole result, losing the summary entirely.
        raw = '{"summary": "A summary.", "key_points": ["one", "two"],'
        data = _parsed(raw)
        assert isinstance(data, dict)
        assert data["summary"] == "A summary."
        assert data["key_points"] == ["one", "two"]

    def test_truncated_mid_key_drops_the_half_written_key(self):
        data = _parsed('{"summary": "A summary.", "key_po')
        assert data["summary"] == "A summary."

    def test_unclosed_array_and_object_are_both_closed(self):
        data = _parsed('{"summary": "x", "key_points": ["a", "b"')
        assert data["key_points"] == ["a", "b"]

    def test_a_truncated_summary_value_is_kept_not_discarded(self):
        # Half a summary still reads as a summary. Throwing it away to return
        # a strictly-valid empty result serves nobody.
        data = _parsed('{"summary": "The authors argue that retrieval qual')
        assert data["summary"].startswith("The authors argue")

    def test_a_truncated_bullet_is_dropped_but_its_siblings_survive(self):
        raw = '{"summary": "ok", "key_points": ["complete point", "half a poi'
        data = _parsed(raw)
        assert data["key_points"] == ["complete point"]

    def test_unclosed_code_fence_is_still_stripped(self):
        # Truncation cuts the closing ``` too, so the fence regex never matched
        # and the payload no longer started with "{".
        data = _parsed('```json\n{"summary": "fenced", "key_points": ["a"]}')
        assert data["summary"] == "fenced"


class TestRepairsControlCharacters:
    def test_raw_newline_inside_a_string_is_escaped(self):
        # json.loads rejects a literal newline inside a string with
        # "Invalid control character". Models emit them constantly.
        data = _parsed('{"summary": "Line one\nline two.", "key_points": []}')
        assert data["summary"] == "Line one\nline two."

    def test_tab_and_carriage_return_are_escaped(self):
        data = _parsed('{"summary": "a\tb\rc", "key_points": []}')
        assert data["summary"] == "a\tb\rc"

    def test_valid_json_is_returned_unchanged(self):
        raw = '{"summary": "fine", "key_points": ["a"]}'
        assert _parsed(raw) == json.loads(raw)

    def test_escaped_quote_does_not_end_the_string_early(self):
        data = _parsed('{"summary": "he said \\"hi\\" loudly", "key_points": []}')
        assert data["summary"] == 'he said "hi" loudly'


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


class TestUsesOllamaCopyInsteadOfDegrading:
    """if the user already has the better model, use it - do not fall back.

    Ollama stores models as content-addressed blobs, so llama.cpp cannot open
    them. Discovery correctly saw them as installed and suppressed the download
    prompt, but the loader could not use them - so the user got no prompt AND no
    benefit, with analysis silently running on the base model. Routing that task
    to Ollama's API is what makes "already installed" actually mean something.
    """

    def _client(self, tmp_path):
        our = tmp_path / "models"
        our.mkdir()
        (our / BASE).write_bytes(b"x" * 1000)  # baseline only
        c = OllamaClient(provider="llama_cpp", model_path=our)
        c.model_path = our
        return c

    def _with_ollama(self, monkeypatch, *names):
        from domain.model_manager.discovery import DiscoveredModel
        monkeypatch.setattr(
            discovery, "find_ollama_running",
            lambda _u: [DiscoveredModel(name=n, source="ollama") for n in names],
        )
        monkeypatch.setattr(discovery, "find_lmstudio_models", lambda: [])

    def test_analysis_routes_to_ollama_when_only_ollama_has_it(self, tmp_path, monkeypatch):
        c = self._client(tmp_path)
        self._with_ollama(monkeypatch, "qwen2.5:1.5b")
        assert c._task_needs_ollama("analysis") == "qwen2.5:1.5b"

    def test_general_stays_local_on_the_fast_baseline(self, tmp_path, monkeypatch):
        # general/chat deliberately uses the small model for latency; it has no
        # dedicated entry, so it must never be routed away.
        c = self._client(tmp_path)
        self._with_ollama(monkeypatch, "qwen2.5:1.5b")
        assert c._task_needs_ollama("general") is None

    def test_local_file_wins_over_ollama(self, tmp_path, monkeypatch):
        # loading a local gguf avoids an HTTP hop, so prefer it when we have one
        c = self._client(tmp_path)
        (tmp_path / "models" / ANALYSIS).write_bytes(b"y" * 1000)
        self._with_ollama(monkeypatch, "qwen2.5:1.5b")
        assert c._task_needs_ollama("analysis") is None

    def test_no_ollama_means_no_routing(self, tmp_path, monkeypatch):
        c = self._client(tmp_path)
        self._with_ollama(monkeypatch)  # ollama has nothing
        assert c._task_needs_ollama("analysis") is None

    def test_unrelated_ollama_model_is_not_used(self, tmp_path, monkeypatch):
        c = self._client(tmp_path)
        self._with_ollama(monkeypatch, "llama3.2:3b")
        assert c._task_needs_ollama("analysis") is None

    def test_probe_is_cached(self, tmp_path, monkeypatch):
        """the probe is HTTP; doing it on every generate would add latency."""
        c = self._client(tmp_path)
        calls = {"n": 0}
        from domain.model_manager.discovery import DiscoveredModel
        def probe(_u):
            calls["n"] += 1
            return [DiscoveredModel(name="qwen2.5:1.5b", source="ollama")]
        monkeypatch.setattr(discovery, "find_ollama_running", probe)
        monkeypatch.setattr(discovery, "find_lmstudio_models", lambda: [])
        for _ in range(5):
            c._task_needs_ollama("analysis")
        assert calls["n"] == 1
