"""
thinkstack configuration module.

centralizes all application settings including paths, model names,
chunking parameters, and server configuration. uses pydantic-settings
for environment variable overrides with the THINKSTACK_ prefix.
"""

import os
import sys
from pathlib import Path
from pydantic_settings import BaseSettings

# ── frozen-build path resolution ─────────────────────────────────────────
# under pyinstaller, __file__ points inside the bundle (a read-only install
# dir, or a temp extraction dir for onefile). writing user data there means
# it is either denied or silently discarded on the next launch, so the two
# roots are resolved separately:
#
#   BUNDLE_DIR -- read-only payload we ship (frontend, embedding model)
#   STATE_DIR  -- writable, persistent user data (papers, vector store)

_FROZEN = getattr(sys, "frozen", False)

if _FROZEN:
    # onedir: sys.executable sits in the folder holding the payload.
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    STATE_DIR = (
        Path(os.getenv("LOCALAPPDATA") or Path.home() / ".local" / "share")
        / "ThinkStack"
    )
else:
    BUNDLE_DIR = Path(__file__).parent
    STATE_DIR = Path(__file__).parent / "data"


class Settings(BaseSettings):
    """application-wide configuration with sensible defaults for offline use."""

    # paths
    base_dir: Path = BUNDLE_DIR
    data_dir: Path = STATE_DIR
    papers_dir: Path = STATE_DIR / "papers"
    chroma_dir: Path = STATE_DIR / "vectorstore"
    models_dir: Path = STATE_DIR / "models"
    # gguf models we ship inside the frozen bundle (via pyinstaller --add-data
    # data/models). on first run these are copied into the writable models_dir
    # so the installed app has a working model offline. empty/absent in a source
    # checkout (BUNDLE_DIR == project root, so this equals models_dir).
    bundled_models_dir: Path = BUNDLE_DIR / "data" / "models"

    # llm runtime
    llm_provider: str = "llama_cpp"
    llm_model_path: Path = STATE_DIR / "models"
    # heavier model used only for structured-json analysis tasks (summarize,
    # claims, themes, gap analysis). the lightweight 0.5b base model rambles
    # past the token limit and produces unparseable json on these tasks; a
    # slightly larger model is far more reliable. this is a filename resolved
    # inside the models dir. if the file is absent, these tasks gracefully fall
    # back to the base model. only one model is resident at a time (the runtime
    # swaps between base and analysis models on demand to cap memory use).
    llm_analysis_model: str = "qwen2.5-1.5b-instruct-q4_k_m.gguf"
    llm_ctx_size: int = 4096
    # -1 = auto-detect (hardware profiler picks the safe offload count).
    # set to 0 to force cpu-only, or a positive integer for manual control.
    # override with THINKSTACK_LLM_GPU_LAYERS=0 to force cpu-only.
    llm_gpu_layers: int = -1
    # when true, the hardware profiler overrides llm_ctx_size at runtime
    # to match the machine's available memory. set false to use the static
    # value above.
    llm_auto_ctx: bool = True

    # generation defaults for interactive chat (kept small for low latency)
    chat_max_tokens: int = 512
    chat_context_chunks: int = 5
    chat_context_char_budget: int = 3000

    # ollama (optional fallback runtime)
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"
    ollama_timeout: int = 120

    # embeddings
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dimension: int = 384
    # the copy of the embedding model shipped inside the bundle. present only
    # in packaged builds; from source we fall back to the hub/hf cache.
    bundled_embedding_dir: Path = BUNDLE_DIR / "models" / "all-MiniLM-L6-v2"

    # chunking
    chunk_size: int = 512
    chunk_overlap: int = 50

    # search
    search_top_k: int = 10
    similarity_threshold: float = 0.3

    # server
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = True

    model_config = {
        "env_prefix": "THINKSTACK_",
        # machine-specific overrides (model path, gpu layers) live in a
        # gitignored .env so they never get committed into the shared repo.
        #
        # a relative ".env" resolves against the cwd, which is whatever
        # directory the desktop shell happened to launch us from -- so a
        # packaged build would silently miss it and fall back to the
        # cpu-only defaults. the candidates below are tried in order, with
        # later entries winning, so an .env dropped next to the installed
        # exe overrides the one baked into the bundle.
        "env_file": (
            BUNDLE_DIR / ".env",
            Path(sys.executable).parent / ".env" if _FROZEN else ".env",
        ),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()
