"""The LLM client: every generation in the app goes through `ollama_client`.

    generate(prompt, task_type=...)        plain text (Scribe)
    generate_json(prompt, task_type=...)   JSON forced by a GBNF grammar
                                           (analysis, gaps, metadata fallback)

Per call: `_route` asks domain/model_manager/router.py which GGUF serves the
task on this machine now; `_get_llama` loads it (EXACTLY ONE model resident,
swapped on demand, under one lock because llama.cpp is not safe for
concurrent use); context and GPU layers come from infrastructure/capability.py.
If the task's model exists only in Ollama, Ollama serves it over HTTP instead.

Small models break JSON in two ways the grammar cannot prevent (cut off
mid-string, raw newlines); `_extract_json_text` and `_repair_json` recover
what they can. ALWAYS pass `task_type`: it defaults to "general" and a call
without it ignores the model the user assigned to that job.
"""

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

# gbnf grammar that constrains llama.cpp output to valid json only.
# this prevents conversational fluff like "Sure, here is the JSON:"
JSON_GBNF_GRAMMAR = r"""
root   ::= object
value  ::= object | array | string | number | ("true" | "false" | "null") ws

object ::=
  "{" ws (
    string ":" ws value
    ("," ws string ":" ws value)*
  )? "}" ws

array  ::=
  "[" ws (
    value
    ("," ws value)*
  )? "]" ws

string ::=
  "\"" (
    [^\\"\x7F\x00-\x1F] |
    "\\" (["\\/bfnrt] | "u" [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F])
  )* "\"" ws

number ::= ("-"? ([0-9] | [1-9] [0-9]*)) ("." [0-9]+)? ([eE] [-+]? [0-9]+)? ws

ws ::= ([ \t\n] ws)?
"""


_THINK_BLOCK = re.compile(r"^\s*<think>.*?</think>\s*", re.S)


def _strip_think(text: str) -> str:
    """Drop a leading <think>...</think> a reasoning model wrote anyway."""
    return _THINK_BLOCK.sub("", text, count=1)


def _thinks(llama) -> bool:
    """A ChatML model whose own template has a think block (Qwen3).

    Under the JSON grammar such a model cannot open <think> and closes the
    object at once, returning `{}`; see _chatml_without_thinking.
    """
    template = (getattr(llama, "metadata", None) or {}).get("tokenizer.chat_template", "")
    return "<think>" in template and "<|im_start|>" in template


def _chatml_without_thinking(messages: list[dict]) -> str:
    """The ChatML prompt with an EMPTY think block pre-filled, which is what the
    model's own template does with enable_thinking=False. The grammar then
    applies to the answer, not to the reasoning it would otherwise start."""
    turns = "".join(f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n" for m in messages)
    return turns + "<|im_start|>assistant\n<think>\n\n</think>\n\n"


def _extract_json_text(raw: str) -> str:
    """The JSON inside a raw reply: fences stripped, narrowed to the outermost
    object or array. Needed because Ollama, or a failed grammar load, can wrap
    or preface it."""
    s = (raw or "").strip()

    # Strip a fenced code block: ```json ... ``` or ``` ... ```
    #
    # The opening fence is removed even when the closing one is missing.
    # Truncated output has no closing fence, and leaving the opener in place
    # meant the text no longer began with "{", so the object detection below
    # gave up on something that was perfectly recoverable.
    if "```" in s:
        match = re.search(r"```(?:json)?\s*(.*?)```", s, re.DOTALL)
        if match:
            s = match.group(1).strip()
        else:
            s = re.sub(r"^\s*```(?:json)?\s*", "", s).strip()

    # Narrow to the outermost object or array.
    #
    # If the text STARTS with "{" it is an object, even when truncation left it
    # without a closing brace. Falling through to the array branch there
    # extracted a nested list and threw the object away, turning a recoverable
    # truncation into a result of the wrong shape entirely. _repair_json closes
    # what is left open, so an unterminated object is fine to return as-is.
    lead = s.lstrip()[:1]
    if lead == "{":
        end = s.rfind("}")
        return s[s.find("{"): end + 1] if end > s.find("{") else s[s.find("{"):]
    if lead == "[":
        end = s.rfind("]")
        return s[s.find("["): end + 1] if end > s.find("[") else s[s.find("["):]
    if "{" in s and "}" in s:
        return s[s.find("{"): s.rfind("}") + 1]
    if "[" in s and "]" in s:
        return s[s.find("["): s.rfind("]") + 1]

    return s


def _repair_json(s: str) -> str:
    """Parse JSON a small model did not finish writing. Unchanged if it parses.

    Repairs two failure modes, which account for nearly every parse error:

        raw newline in a string  -> escape it     ("Invalid control character")
        truncated mid-string     -> close what is open, drop the fragment
                                    ("Unterminated string")

    A summary missing its last bullet beats an error where the summary goes.
    """
    if not s:
        return s
    try:
        json.loads(s)
        return s
    except (ValueError, TypeError):
        pass

    out: list[str] = []
    stack: list[str] = []
    in_string = False
    escaped = False
    # where the currently open string begins, so a string the model never
    # finished can be judged on what it was: prose worth keeping, or a
    # fragment worth dropping.
    last_open_idx = -1

    for ch in s:
        if in_string:
            if escaped:
                out.append(ch)
                escaped = False
                continue
            if ch == "\\":
                out.append(ch)
                escaped = True
                continue
            if ch == '"':
                in_string = False
                out.append(ch)
                continue
            # escape the control characters JSON will not accept raw
            if ch == "\n":
                out.append("\\n")
            elif ch == "\r":
                out.append("\\r")
            elif ch == "\t":
                out.append("\\t")
            elif ord(ch) < 0x20:
                out.append(f"\\u{ord(ch):04x}")
            else:
                out.append(ch)
            continue

        if ch == '"':
            in_string = True
            last_open_idx = len(out)
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if stack and stack[-1] == ch:
                stack.pop()
        out.append(ch)

    if in_string:
        # The model was cut off mid-string. What to do with the fragment
        # depends on what the fragment IS, which is decided by what precedes
        # its opening quote:
        #
        #   {"summary": "the paper argu     <- a VALUE. Half a summary still
        #                                      reads, so it is kept.
        #   {"summary": "done", "key_po     <- a KEY. Cannot be completed into
        #   ["first point", "second poi     <- an ARRAY ELEMENT. Half a bullet
        #                                      is noise, so both are dropped.
        prefix = "".join(out[:last_open_idx]).rstrip() if last_open_idx >= 0 else ""
        if prefix.endswith(":"):
            out.append('"')
        else:
            del out[last_open_idx:]

    repaired = "".join(out).rstrip()

    # A dangling comma closes into nothing valid, so drop back to the last
    # point that does. This runs after the fragment removal above, which is
    # what leaves the comma exposed in the key/element cases.
    repaired = re.sub(r",\s*$", "", repaired)

    while stack:
        repaired += stack.pop()

    try:
        json.loads(repaired)
        logger.info("repaired truncated/invalid json from the model")
        return repaired
    except (ValueError, TypeError):
        # Last resort: keep only the complete leading entries of the object.
        m = re.match(r"\s*\{.*", repaired, re.S)
        if m:
            for cut in range(len(repaired) - 1, 0, -1):
                if repaired[cut] == ",":
                    candidate = repaired[:cut] + "}"
                    try:
                        json.loads(candidate)
                        logger.info("recovered a partial json object from the model")
                        return candidate
                    except (ValueError, TypeError):
                        continue
        return repaired


class OllamaClient:
    """async client for local llm runtimes (ollama or llama.cpp)."""

    def __init__(
        self,
        provider: str = settings.llm_provider,
        base_url: str = settings.ollama_base_url,
        model: str = settings.ollama_model,
        model_path: Path = settings.llm_model_path,
        ctx_size: int = settings.llm_ctx_size,
        gpu_layers: int = settings.llm_gpu_layers,
        timeout: int = settings.ollama_timeout,
    ):
        self.provider = provider.lower().strip()
        self.base_url = base_url
        self.model = model
        self.model_path = Path(model_path)
        self.ctx_size = ctx_size
        # The context the resident model was actually loaded with. The
        # configured value is only a ceiling: _compute_load_params lowers it
        # to match the machine, and the OOM path below lowers it again. Callers
        # that must size a prompt need the real number, not the wish.
        self._effective_ctx: int | None = None
        # Cached MachineCapability; see _capability().
        self._cap = None
        # which registry entry the router last chose, so a load failure can be
        # attributed to it and explained on the Bench card afterwards.
        self._last_resolution = None
        self.gpu_layers = gpu_layers
        self.timeout = timeout
        self._llama = None
        # path (str) of the model currently resident in self._llama, so
        # _get_llama can tell when a task needs a different model and swap.
        self._llama_path: Optional[str] = None
        # serializes access to the single local model instance. llama.cpp is
        # not safe for concurrent create_chat_completion calls on one model,
        # so all generations queue through this lock to avoid contention and
        # state corruption while keeping the event loop responsive.
        self._gen_lock: Optional[asyncio.Lock] = None
        # cached list of models a running ollama can serve. probed at most once
        # per process, and only when a task's model is missing from disk.
        self._ollama_models = None
        # apply any model the user selected in a previous session
        self._apply_persisted_model()

    def _get_gen_lock(self) -> asyncio.Lock:
        """lazily create the generation lock bound to the running loop."""
        if self._gen_lock is None:
            self._gen_lock = asyncio.Lock()
        return self._gen_lock

    def _state_file(self) -> Path:
        """path of the file that remembers the user's selected model."""
        return settings.data_dir / "active_model.txt"

    def _apply_persisted_model(self) -> None:
        """load the model selected in a previous session, if any.

        the selection is applied at startup (a fresh load is always safe),
        which is how a model switch takes effect without an in-process
        cuda reload.
        """
        try:
            state = self._state_file()
            if not state.is_file():
                return
            name = state.read_text(encoding="utf-8").strip()
            if not name:
                return
            if self.provider == "llama_cpp":
                candidate = Path(name)
                if not candidate.is_file():
                    candidate = self.model_path.parent / name
                if candidate.is_file():
                    self.model_path = candidate
            else:
                self.model = name
        except Exception as e:  # noqa: BLE001 - selection is best-effort
            logger.warning("could not apply persisted model: %s", e)

    def _resolve_llama_model_path(self) -> Path:
        """resolve the configured llama.cpp model path.

        if a directory is provided, selects the first gguf file by name.
        """
        path = self.model_path
        if path.is_file():
            return path
        if path.is_dir():
            candidates = sorted(path.glob("*.gguf"))
            if candidates:
                return candidates[0]
        raise FileNotFoundError(f"llama.cpp model not found at {path}")

    # ── legacy task map (deprecated) ──────────────────────────────────
    # Task -> GGUF filenames, tried in order, then the base model. Superseded
    # by the registry and router (ADR 2026-08-05); still the router's fourth
    # fallback (see router.py), so changes here still change routing.
    TASK_MODEL_MAP = {
        # The 1.5B FIRST for LaTeX: the 0.5B wrote \\includegraphics of files
        # that do not exist and prose instead of math. The fine-tuned writer
        # names below do not exist yet.
        "latex_writer": [
            settings.llm_analysis_model,
            "latex-writer.gguf",
            "latex_writer.gguf",
        ],
        "analysis": [settings.llm_analysis_model],
        "gap_analysis": [settings.llm_analysis_model, "gap-analysis.gguf", "gap_analysis.gguf"],
        "general": [],  # always uses the base model
    }

    def _hw_model_budget_gb(self) -> float:
        """the largest model (gb) that safely fits this machine right now.

        delegates to the hardware profiler, which reserves headroom for the os,
        the app, and — importantly — whatever else the user is running, using
        *available* ram rather than total. the profile itself is the native one
        the desktop shell measured at launch (THINKSTACK_HW_PROFILE) when present.
        returns 0.0 when the budget is unknown, which callers treat as "don't
        block" (better to attempt a load, with the loader's oom fallback, than to
        refuse outright).
        """
        try:
            from infrastructure.hardware import max_safe_model_size_gb
            return max_safe_model_size_gb()
        except Exception as e:  # noqa: BLE001 - budgeting is best-effort
            logger.warning("could not compute hw model budget: %s", e)
            return 0.0

    def _fits_budget(self, model_path: Path, budget_gb: float) -> bool:
        """whether a gguf fits the hardware budget (unknown budget => yes)."""
        if budget_gb <= 0:
            return True
        from infrastructure.hardware import model_file_size_gb
        return model_file_size_gb(model_path) <= budget_gb

    def _find_external_model(self, wanted: str) -> Optional[Path]:
        """a loadable gguf for ``wanted`` sitting outside our own models dir.

        Users often already have these weights via LM Studio or a previous
        download. Without this the app would degrade to the base model — or
        offer to download a gigabyte the machine already stores — purely because
        the file is in someone else's directory.

        Matching is on the canonical family/size key, since every runtime names
        the same weights differently. Only filesystem sources are consulted:
        Ollama serves its blobs over HTTP rather than as loadable .gguf files, so
        probing it here would add latency to a model load for a path llama.cpp
        cannot use anyway.
        """
        try:
            from domain.model_manager.discovery import (
                find_lmstudio_models,
                find_thinkstack_models,
                model_key,
            )

            target = model_key(wanted)
            found = find_thinkstack_models(self._models_dir()) + find_lmstudio_models()
            for m in found:
                if m.usable_directly and model_key(m.name) == target:
                    p = Path(m.path)
                    if p.is_file():
                        return p
        except Exception as e:  # noqa: BLE001 - a bonus lookup must never break loading
            logger.debug("external model lookup failed for %s: %s", wanted, e)
        return None

    def _ollama_served_model(self, task_type: str = "general") -> Optional[str]:
        """The Ollama tag serving the weights this task wants, or None.

        Ollama's blobs cannot be opened by llama.cpp, but Ollama can serve them
        over HTTP, so a model the user has only in Ollama is still used.
        Only consulted when the task's model is missing from disk, and the probe
        result is cached, so this costs nothing on the common path.
        """
        candidates = self.TASK_MODEL_MAP.get(task_type, [])
        if not candidates:
            return None
        try:
            from domain.model_manager.discovery import find_ollama_running, model_key

            if self._ollama_models is None:
                self._ollama_models = find_ollama_running(self.base_url)

            wanted = {model_key(c) for c in candidates}
            for m in self._ollama_models:
                if model_key(m.name) in wanted:
                    return m.name
        except Exception as e:  # noqa: BLE001 - a bonus route must never break generation
            logger.debug("ollama lookup failed for %s: %s", task_type, e)
        return None

    def _task_needs_ollama(self, task_type: str) -> Optional[str]:
        """the Ollama tag to use for this task, or None to load locally.

        Only when the task has a dedicated model, that model is not resolvable as
        a file, and Ollama can serve it.
        """
        if self.provider != "llama_cpp":
            return None
        candidates = self.TASK_MODEL_MAP.get(task_type, [])
        if not candidates:
            return None
        models_dir = self._models_dir()
        for name in candidates:
            if (models_dir / name).is_file() or self._find_external_model(name):
                return None  # we can load it ourselves; no need for ollama
        return self._ollama_served_model(task_type)

    def _resolve_task_model_path(self, task_type: str = "general") -> Path:
        """The GGUF for `task_type` (latex_writer, analysis, gap_analysis,
        general), via `_route`. A task model too large for free memory right
        now is skipped for a smaller one, so a big job degrades, not crashes."""
        base = self._resolve_llama_model_path()
        resolution = self._route(task_type, base)

        # Attribute a failure to the registry entry that caused it, so the
        # Bench card can explain itself later. Only the router knows which
        # entry won, which is why resolution carries the id at all.
        self._last_resolution = resolution
        return resolution.path or base

    def _record_load_error(self, exc: BaseException) -> None:
        """Remember, on the registry entry, why its model would not load.

        A load failure happens deep inside a generation; the Bench card that
        has to explain it renders much later, possibly after a restart. Nothing
        else survives that gap, which is why `last_error` is persisted rather
        than derived.

        Best-effort throughout: this runs on an error path, and failing to
        record why something failed must never replace the original failure.
        """
        res = self._last_resolution
        if res is None or not getattr(res, "entry_id", None):
            return
        try:
            from domain.model_manager.registry import Registry

            models_dir = self._models_dir()
            registry = Registry.load(models_dir)
            if registry.get(res.entry_id) is None:
                return
            registry.record_error(res.entry_id, f"{type(exc).__name__}: {exc}"[:300])
            registry.save(models_dir)
        except Exception as e:  # noqa: BLE001
            logger.debug("could not record the load error: %s", e)

    def _route(self, task_type: str, base: Optional[Path] = None):
        """Ask the router which model answers this task.

        The seam between the loader and routing policy: supplies the runtime
        facts the router cannot know -- model directory, memory budget,
        external-runtime naming, legacy TASK_MODEL_MAP.

        An EMPTY registry must route exactly as this class did before the
        extraction. Guarded by test_model_router.py.
        """
        from domain.model_manager.manifest import BundledManifest
        from domain.model_manager.registry import Registry
        from domain.model_manager.router import resolve

        models_dir = self._models_dir()
        # Read per call, not cached at import: TASK_MODEL_MAP is a class
        # attribute frozen at import time, and a model the user assigns in
        # Bench has to be visible without restarting the whole process.
        registry = Registry.load(models_dir)
        manifest = BundledManifest.load(settings.bundled_models_dir)
        cap = self._capability()

        return resolve(
            task_type,
            registry=registry,
            manifest=manifest,
            models_dir=models_dir,
            budget_gb=self._hw_model_budget_gb(),
            external_finder=self._find_external_model,
            legacy_defaults=self.TASK_MODEL_MAP.get(task_type, []),
            base_model=base if base is not None else self._resolve_llama_model_path(),
            plan_for_size=cap.plan_for_size if cap is not None else None,
        )

    def _capability(self):
        """This machine's capability, resolved once and cached.

        Cached because detection is not free and the machine does not change
        while the app is running. The Diagnose screen clears it deliberately
        when the user asks for a fresh look.
        """
        if self._cap is None:
            from infrastructure.capability import for_this_machine
            self._cap = for_this_machine()
        return self._cap

    def _compute_load_params(self, model_path: Path) -> tuple[int, int]:
        """(n_ctx, n_gpu_layers) for this model on this machine.

        Both come from infrastructure.capability. Derive neither here -- two
        places deciding this is what pinned every Apple Silicon Mac to CPU.

        Explicit settings still win: THINKSTACK_LLM_GPU_LAYERS=0 is the escape
        hatch when offload misbehaves.
        """
        from infrastructure.hardware import model_file_size_gb

        cap = self._capability()
        file_size = model_file_size_gb(model_path)
        plan = cap.plan_for_size(file_size)

        # llm_auto_ctx=False means "use exactly what I configured".
        ctx = plan.n_ctx if settings.llm_auto_ctx else self.ctx_size
        # gpu_layers=-1 means "decide for me"; anything else is a deliberate
        # override and is obeyed.
        layers = plan.n_gpu_layers if self.gpu_layers == -1 else self.gpu_layers

        p = cap.profile
        logger.info(
            "%s tier → ctx=%d, gpu_layers=%d (model %.2f gb, ram %.1f/%.1f gb, "
            "gpu=%s, engine offload=%s)",
            cap.tier, ctx, layers, file_size,
            p.available_ram_gb, p.total_ram_gb,
            p.gpu_name or "none", cap.engine_offload,
        )
        return ctx, layers

    def output_token_budget(
        self, task_type: str = "general", ceiling: int = 1024, floor: int = 256
    ) -> int:
        """How many tokens of REPLY to ask for on this machine.

        Delegates to infrastructure.capability. Kept as a method here because
        callers already hold the client, but the policy lives in one place.
        """
        return self._capability().output_tokens(self._effective_ctx)

    def input_char_budget(self, max_tokens: int, task_type: str = "general") -> int:
        """Prompt characters that fit alongside `max_tokens` of reply: the
        context window holds both, so size prompts with this, never a constant."""
        return self._capability().input_chars(self._effective_ctx, max_tokens)

    def _get_llama(self, task_type: str = "general"):
        """Load the model for `task_type`, lazily. EXACTLY ONE stays resident.

        A different model unloads the current one first, so peak memory is one
        model, not two. Same model reuses the instance.

        On OOM, retries with minimal settings rather than failing.
        """
        try:
            from llama_cpp import Llama
        except ImportError as e:
            raise RuntimeError(
                "llama-cpp-python is required for llm_provider=llama_cpp"
            ) from e

        model_path = self._resolve_task_model_path(task_type)
        requested = str(model_path)

        # right model already resident → reuse, no reload
        if self._llama is not None and self._llama_path == requested:
            return self._llama

        # a different model is resident → unload it first to cap memory at one
        # model. safe because all generation is serialized by _gen_lock, so no
        # call is in flight on the model being dropped.
        if self._llama is not None and self._llama_path != requested:
            import gc
            logger.info(
                "swapping resident model %s -> %s (single-resident, memory-safe)",
                Path(self._llama_path).name if self._llama_path else "none",
                model_path.name,
            )
            self._llama = None
            self._llama_path = None
            gc.collect()

        n_ctx, n_gpu_layers = self._compute_load_params(model_path)

        # attempt load with computed params; catch oom and retry with minimal
        if n_gpu_layers != 0:
            try:
                logger.info(
                    "loading llama.cpp model from %s (ctx=%d, gpu_layers=%d)",
                    model_path.name, n_ctx, n_gpu_layers,
                )
                self._llama = Llama(
                    model_path=str(model_path),
                    n_ctx=n_ctx,
                    n_gpu_layers=n_gpu_layers,
                    verbose=False,
                )
                self._effective_ctx = n_ctx
                self._llama_path = requested
                return self._llama
            except (MemoryError, RuntimeError, Exception) as e:
                err_str = str(e).lower()
                if "memory" in err_str or "alloc" in err_str or "oom" in err_str:
                    logger.warning(
                        "oom during gpu load (ctx=%d, layers=%d): %s. "
                        "retrying with ctx=2048, cpu-only",
                        n_ctx, n_gpu_layers, e,
                    )
                    n_ctx = 2048
                    n_gpu_layers = 0
                else:
                    logger.warning(
                        "gpu load failed (%s), falling back to cpu-only", e
                    )
                    n_gpu_layers = 0

        logger.info(
            "loading llama.cpp model from %s (cpu-only, ctx=%d)",
            model_path.name, n_ctx,
        )
        try:
            self._llama = Llama(
                model_path=str(model_path),
                n_ctx=n_ctx,
                n_gpu_layers=0,
                verbose=False,
            )
            self._effective_ctx = n_ctx
        except (MemoryError, RuntimeError) as e:
            self._record_load_error(e)
            # absolute last resort: minimal context
            logger.error(
                "cpu load failed with ctx=%d: %s. last resort ctx=2048", n_ctx, e,
            )
            self._llama = Llama(
                model_path=str(model_path),
                n_ctx=2048,
                n_gpu_layers=0,
                verbose=False,
            )
            self._effective_ctx = n_ctx
        self._llama_path = requested
        return self._llama

    async def _generate_ollama(
        self,
        prompt: str,
        system: Optional[str],
        temperature: float,
        max_tokens: int,
        json_mode: bool,
        model: Optional[str] = None,
    ) -> str:
        payload = {
            "model": model or self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if system:
            payload["system"] = system
        if json_mode:
            payload["format"] = "json"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/generate",
                json=payload,
            )
            response.raise_for_status()
            return response.json().get("response", "")

    async def _generate_llama_cpp(
        self,
        prompt: str,
        system: Optional[str],
        temperature: float,
        max_tokens: int,
        json_mode: bool = False,
        task_type: str = "general",
    ) -> str:
        # build the chat messages; create_chat_completion applies the model's
        # own chat template, so a dedicated system turn is handled correctly.
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        kwargs = {
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        # enforce structured json output via gbnf grammar when requested
        if json_mode:
            try:
                from llama_cpp import LlamaGrammar
                kwargs["grammar"] = LlamaGrammar.from_string(JSON_GBNF_GRAMMAR)
            except Exception as e:
                logger.warning("failed to load json grammar, proceeding without: %s", e)

        # serialize BOTH the lazy model load and generation through one lock.
        # llama.cpp is not safe for concurrent access on a single context, and a
        # concurrent first-request race would otherwise load the model twice on
        # the gpu (doubling vram -> segfault / shared-memory spill). loading
        # inside the lock guarantees exactly one load and one in-flight call.

        async with self._get_gen_lock():
            llama = self._get_llama(task_type=task_type)
            if _thinks(llama):
                messages = kwargs.pop("messages")
                result = await asyncio.to_thread(
                    llama.create_completion,
                    _chatml_without_thinking(messages),
                    stop=["<|im_end|>"],
                    **kwargs,
                )
                choices = result.get("choices", [])
                return _strip_think(choices[0].get("text", "")) if choices else ""
            result = await asyncio.to_thread(
                llama.create_chat_completion,
                **kwargs,
            )

        choices = result.get("choices", [])
        if not choices:
            return ""
        message = choices[0].get("message", {})
        return _strip_think(message.get("content", ""))

    async def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        task_type: str = "general",
    ) -> str:
        """Generate text. Runs on llama.cpp or Ollama, whichever is configured.

        `task_type` selects the model. It defaults to "general", so a caller
        that omits it silently ignores the user's choice for that job -- always
        pass it.
        """
        if self.provider == "llama_cpp":
            # the user already has this task's model in ollama and we cannot load
            # it as a file -> let ollama serve it rather than degrading.
            via_ollama = self._task_needs_ollama(task_type)
            if via_ollama:
                logger.info("task %s -> ollama:%s (already installed)", task_type, via_ollama)
                return await self._generate_ollama(
                    prompt=prompt, system=system, temperature=temperature,
                    max_tokens=max_tokens, json_mode=False, model=via_ollama,
                )
            return await self._generate_llama_cpp(
                prompt=prompt,
                system=system,
                temperature=temperature,
                max_tokens=max_tokens,
                task_type=task_type,
            )

        return await self._generate_ollama(
            prompt=prompt,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=False,
        )

    async def generate_json(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 2048,
        task_type: str = "general",
    ) -> str:
        """Generate with JSON output constrained by the grammar.

        Returns the raw string; the caller parses. See `_repair_json`.
        """
        if self.provider == "llama_cpp":
            via_ollama = self._task_needs_ollama(task_type)
            if via_ollama:
                logger.info("task %s -> ollama:%s (already installed)", task_type, via_ollama)
                raw = await self._generate_ollama(
                    prompt=prompt, system=system, temperature=temperature,
                    max_tokens=max_tokens, json_mode=True, model=via_ollama,
                )
                return _repair_json(_extract_json_text(raw))
            raw = await self._generate_llama_cpp(
                prompt=prompt,
                system=system,
                temperature=temperature,
                max_tokens=max_tokens,
                json_mode=True,
                task_type=task_type,
            )
            return _repair_json(_extract_json_text(raw))

        raw = await self._generate_ollama(
            prompt=prompt,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=True,
        )
        return _repair_json(_extract_json_text(raw))

    def _models_dir(self) -> Path:
        """the directory holding the gguf model files."""
        path = self.model_path
        return path if path.is_dir() else path.parent

    def available_gguf_models(self) -> list[Path]:
        """list all gguf model files available in the models directory."""
        return sorted(self._models_dir().glob("*.gguf"))

    def _persist_model(self, name: str) -> None:
        """remember the selected model for the next startup."""
        try:
            state = self._state_file()
            state.parent.mkdir(parents=True, exist_ok=True)
            state.write_text(name, encoding="utf-8")
        except Exception as e:  # noqa: BLE001 - persistence is best-effort
            logger.warning("could not persist model selection: %s", e)

    async def set_model(self, name: str) -> dict:
        """Select the active model. Persisted; applied live only when safe.

        llama.cpp cannot reinitialise a CUDA context in-process, so swapping a
        GGUF while one is resident on the GPU crashes the runtime. With a model
        already loaded this returns `restart_required` and keeps serving the
        current one.

        Raises FileNotFoundError if the model cannot be located.
        """
        if self.provider != "llama_cpp":
            # for ollama the model is just a tag name; ollama itself handles
            # loading/unloading, so this applies immediately.
            self.model = name
            self._persist_model(name)
            logger.info("active ollama model set to %s", name)
            return {"active_model": name, "restart_required": False}

        candidate = Path(name)
        if not candidate.is_file():
            candidate = self._models_dir() / name
        if not candidate.is_file():
            raise FileNotFoundError(f"model not found: {name}")

        self._persist_model(candidate.name)

        async with self._get_gen_lock():
            if self._llama is None:
                # nothing resident yet -> safe to apply now; the next
                # generation loads this model fresh.
                self.model_path = candidate
                logger.info("active llama.cpp model set to %s", candidate.name)
                return {"active_model": candidate.name, "restart_required": False}

            # a model is already on the gpu; defer to a restart to avoid a
            # cuda re-init crash. the selection is persisted above.
            logger.info(
                "model switch to %s deferred until restart", candidate.name
            )
            return {
                "active_model": self.model_path.name,
                "pending_model": candidate.name,
                "restart_required": True,
            }

    async def list_models(self) -> list[dict]:
        """Models the active runtime can see, as metadata dicts."""
        if self.provider == "llama_cpp":
            models = [
                {"name": p.name, "path": str(p)}
                for p in self.available_gguf_models()
            ]
            if not models:
                model_path = self._resolve_llama_model_path()
                models = [{"name": model_path.name, "path": str(model_path)}]
            return models

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            return response.json().get("models", [])

    async def check_health(self) -> dict:
        """Whether the configured runtime is available, and what it has."""
        if self.provider == "llama_cpp":
            try:
                model_path = self._resolve_llama_model_path()
                try:
                    import llama_cpp  # noqa: F401
                    dependency_ok = True
                except ImportError:
                    dependency_ok = False

                model_files = [p.name for p in self.available_gguf_models()]
                if not model_files:
                    model_files = [model_path.name]

                return {
                    "status": "connected" if dependency_ok else "disconnected",
                    "provider": "llama_cpp",
                    "models_available": len(model_files),
                    "target_model": model_path.name,
                    "target_available": True,
                    "model_list": model_files,
                    "model_path": str(model_path),
                    "dependency_installed": dependency_ok,
                    "model_loaded": self._llama is not None,
                    "error": (
                        "llama-cpp-python is not installed"
                        if not dependency_ok
                        else ""
                    ),
                }
            except Exception as e:
                logger.warning("llama.cpp health check failed: %s", e)
                return {
                    "status": "disconnected",
                    "provider": "llama_cpp",
                    "error": str(e),
                    "target_model": str(self.model_path),
                }

        try:
            models = await self.list_models()
            model_names = [m.get("name", "") for m in models]
            has_target = any(self.model in name for name in model_names)
            return {
                "status": "connected",
                "provider": "ollama",
                "models_available": len(models),
                "target_model": self.model,
                "target_available": has_target,
                "model_list": model_names,
            }
        except (httpx.ConnectError, httpx.HTTPStatusError) as e:
            logger.warning("ollama health check failed: %s", e)
            return {
                "status": "disconnected",
                "provider": "ollama",
                "error": str(e),
                "target_model": self.model,
            }


ollama_client = OllamaClient()
