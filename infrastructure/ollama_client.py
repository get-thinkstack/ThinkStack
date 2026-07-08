"""
llm client module.

provides a unified async client for local language model inference,
supporting both ollama and llama.cpp runtimes.
"""

import asyncio
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


def _extract_json_text(raw: str) -> str:
    """pull the json payload out of a raw model response.

    even with the gbnf grammar, ollama or a grammar-load fallback can return
    json wrapped in markdown fences or with a short preamble, which breaks
    ``json.loads``. this strips ```...``` fences and narrows the string to the
    outermost json object or array so downstream parsing succeeds.

    args:
        raw: the raw text returned by the model.

    returns:
        the best-effort json substring (unchanged if nothing to strip).
    """
    s = (raw or "").strip()

    # strip a fenced code block: ```json ... ``` or ``` ... ```
    if "```" in s:
        match = re.search(r"```(?:json)?\s*(.*?)```", s, re.DOTALL)
        if match:
            s = match.group(1).strip()

    # narrow to the outermost object/array
    if "{" in s and "}" in s:
        s = s[s.find("{"): s.rfind("}") + 1]
    elif "[" in s and "]" in s:
        s = s[s.find("["): s.rfind("]") + 1]

    return s


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
        self.gpu_layers = gpu_layers
        self.timeout = timeout
        self._llama = None
        # serializes access to the single local model instance. llama.cpp is
        # not safe for concurrent create_chat_completion calls on one model,
        # so all generations queue through this lock to avoid contention and
        # state corruption while keeping the event loop responsive.
        self._gen_lock: Optional[asyncio.Lock] = None
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

    def _get_llama(self):
        """lazily initialize llama.cpp model instance with gpu fallback."""
        if self._llama is not None:
            return self._llama

        try:
            from llama_cpp import Llama
        except ImportError as e:
            raise RuntimeError(
                "llama-cpp-python is required for llm_provider=llama_cpp"
            ) from e

        model_path = self._resolve_llama_model_path()

        # attempt gpu-accelerated load first, fallback to cpu on failure
        if self.gpu_layers != 0:
            try:
                logger.info(
                    "loading llama.cpp model from %s with %d gpu layers",
                    model_path, self.gpu_layers,
                )
                self._llama = Llama(
                    model_path=str(model_path),
                    n_ctx=self.ctx_size,
                    n_gpu_layers=self.gpu_layers,
                    verbose=False,
                )
                return self._llama
            except Exception as e:
                logger.warning(
                    "gpu load failed (%s), falling back to cpu-only", e
                )

        logger.info("loading llama.cpp model from %s (cpu-only)", model_path)
        self._llama = Llama(
            model_path=str(model_path),
            n_ctx=self.ctx_size,
            n_gpu_layers=0,
            verbose=False,
        )
        return self._llama

    async def _generate_ollama(
        self,
        prompt: str,
        system: Optional[str],
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> str:
        payload = {
            "model": self.model,
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
            llama = self._get_llama()
            result = await asyncio.to_thread(
                llama.create_chat_completion,
                **kwargs,
            )

        choices = result.get("choices", [])
        if not choices:
            return ""
        message = choices[0].get("message", {})
        return message.get("content", "")

    async def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> str:
        """generate text from the configured local llm runtime.

        args:
            prompt: the user prompt to send to the model.
            system: optional system prompt for context setting.
            temperature: sampling temperature, lower is more deterministic.
            max_tokens: maximum number of tokens in the response.

        returns:
            the generated text response from the model.

        supports:
            - ollama via /api/generate
            - llama.cpp via llama-cpp-python and a local gguf file
        """
        if self.provider == "llama_cpp":
            return await self._generate_llama_cpp(
                prompt=prompt,
                system=system,
                temperature=temperature,
                max_tokens=max_tokens,
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
    ) -> str:
        """generate a response intended for json parsing.

        wraps the standard generate call with ollama's json format option
        to produce structured output suitable for parsing.

        args:
            prompt: the user prompt, should instruct json output.
            system: optional system prompt.
            temperature: sampling temperature.

        returns:
            raw json string from the model.
        """
        if self.provider == "llama_cpp":
            raw = await self._generate_llama_cpp(
                prompt=prompt,
                system=system,
                temperature=temperature,
                max_tokens=max_tokens,
                json_mode=True,
            )
            return _extract_json_text(raw)

        raw = await self._generate_ollama(
            prompt=prompt,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=True,
        )
        return _extract_json_text(raw)

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
        """select the active model, the global, crash-safe way.

        llama.cpp cannot reinitialise a cuda context in-process, so reloading
        a different gguf while one is already resident on the gpu crashes the
        runtime. to stay stable we therefore:

        * persist the selection so it is applied on the next startup;
        * apply it live only when no model is loaded yet (a fresh load is
          safe), otherwise report ``restart_required`` and keep serving the
          currently loaded model.

        args:
            name: a gguf filename in the models directory, or a full path.

        returns:
            dict with the active model and whether a restart is needed.

        raises:
            FileNotFoundError: if the requested model cannot be located.
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
        """retrieve available model metadata for the active runtime.

        returns:
            list of model metadata dictionaries.
        """
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
        """check whether configured llm runtime is available.

        returns:
            dictionary with status and available model information.
        """
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
