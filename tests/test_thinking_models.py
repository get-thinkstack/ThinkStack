"""Thinking models (Qwen3) get their think block pre-filled, empty.

Under the JSON grammar a model that wants to open `<think>` first cannot, and
closes the object at once: Qwen3-4B returned `{}` for gap finding, measured on
2026-11-20, while the catalog offered it as the best model for that job.
`/no_think` alone does not help (the template still emits an empty block for
the grammar to forbid). Pre-filling `<think>\\n\\n</think>\\n\\n` does: the same
prompt then gave 5 gaps and 3 suggestions.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from infrastructure.ollama_client import OllamaClient, _strip_think

QWEN3_TEMPLATE = (
    "{%- for m in messages %}<|im_start|>{{ m.role }}\n{{ m.content }}<|im_end|>\n"
    "{%- endfor %}<|im_start|>assistant\n{%- if enable_thinking is false %}<think>\n\n"
    "</think>\n\n{%- endif %}"
)


class FakeLlama:
    def __init__(self, template):
        self.metadata = {"tokenizer.chat_template": template}
        self.calls = []

    def create_completion(self, prompt, **kw):
        self.calls.append(("completion", prompt, kw))
        return {"choices": [{"text": '{"ok": 1}'}]}

    def create_chat_completion(self, **kw):
        self.calls.append(("chat", kw["messages"], kw))
        return {"choices": [{"message": {"content": '{"ok": 1}'}}]}


@pytest.fixture
def client_with(monkeypatch):
    # A fake llama_cpp, as tests/test_acceleration.py does: this test is about
    # which call is made, and must not depend on the native library loading.
    import sys
    import types
    fake_mod = types.ModuleType("llama_cpp")
    fake_mod.LlamaGrammar = types.SimpleNamespace(from_string=lambda g: "GRAMMAR")
    monkeypatch.setitem(sys.modules, "llama_cpp", fake_mod)

    def make(template):
        fake = FakeLlama(template)
        c = OllamaClient()
        monkeypatch.setattr(c, "_get_llama", lambda task_type="general": fake)
        return c, fake
    return make


async def test_a_thinking_model_is_given_an_empty_think_block(client_with):
    c, fake = client_with(QWEN3_TEMPLATE)
    await c._generate_llama_cpp("find gaps", "be precise", 0.2, 50, json_mode=True,
                                task_type="gap_analysis")
    kind, prompt, kw = fake.calls[0]
    assert kind == "completion"
    assert prompt.startswith("<|im_start|>system\nbe precise<|im_end|>\n")
    assert prompt.endswith("<|im_start|>assistant\n<think>\n\n</think>\n\n")
    assert "grammar" in kw and "<|im_end|>" in kw["stop"]


async def test_an_ordinary_model_keeps_its_chat_template(client_with):
    c, fake = client_with("{{ messages }}")
    await c._generate_llama_cpp("find gaps", None, 0.2, 50, json_mode=True)
    assert fake.calls[0][0] == "chat"


def test_reasoning_left_in_plain_text_is_removed():
    assert _strip_think("<think>\nlet me see\n</think>\n\n\\section{A}") == "\\section{A}"
    assert _strip_think("\\section{A}") == "\\section{A}"


QWEN3_GGUF = os.environ.get("THINKSTACK_QWEN3_GGUF", "")


@pytest.mark.heavy
@pytest.mark.skipif(not Path(QWEN3_GGUF).is_file(), reason="set THINKSTACK_QWEN3_GGUF")
async def test_qwen3_returns_real_gaps(monkeypatch):
    from llama_cpp import Llama
    llm = Llama(model_path=QWEN3_GGUF, n_ctx=2048, n_threads=6, verbose=False)
    c = OllamaClient()
    monkeypatch.setattr(c, "_get_llama", lambda task_type="general": llm)
    raw = await c._generate_llama_cpp(
        'return {"gaps": [a list of two short research gaps in federated learning]}',
        "respond only with valid json.", 0.2, 300, json_mode=True, task_type="gap_analysis")
    assert json.loads(raw).get("gaps"), raw
