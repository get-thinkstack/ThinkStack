"""Every setting, in one `settings` object (pydantic-settings).

Any field can be overridden by an environment variable `THINKSTACK_<FIELD>`
or a `.env` (see the bottom of this file for which `.env` wins). Paths are
split into BUNDLE_DIR (read-only payload) and STATE_DIR (writable user data),
which differ in a frozen build and coincide in a source checkout.
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
    # GGUFs shipped in the bundle, copied into models_dir on first run. None ship
    # today; in a source checkout this equals models_dir.
    bundled_models_dir: Path = BUNDLE_DIR / "data" / "models"

    # llm runtime
    llm_provider: str = "llama_cpp"
    llm_model_path: Path = STATE_DIR / "models"
    # Legacy default for the analysis tasks (feeds the deprecated task map; the
    # registry decides first). A filename inside models_dir; absent -> base.
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

    # Grounding budget (domain/search/grounding.py): bounded because the local
    # context window is small.
    grounding_context_chunks: int = 5
    grounding_char_budget: int = 3000

    # ollama (optional fallback runtime)
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"
    ollama_timeout: int = 120

    # embeddings
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dimension: int = 384
    # The bundled embedding model. MUST be under data/models: that is where the
    # build stages it, and a wrong path silently falls back to a download that
    # cannot succeed offline. From source, the HF cache is used instead.
    bundled_embedding_dir: Path = BUNDLE_DIR / "data" / "models" / "all-MiniLM-L6-v2"

    # Bundled Tectonic + warmed cache (scripts/fetch-tex.sh). Under data/ so one
    # path works in both modes: repo-root/data/tex from source,
    # _internal/data/tex frozen. A system engine is used only if this is absent.
    bundled_tex_dir: Path = BUNDLE_DIR / "data" / "tex"
    # Tectonic needs its cache writable, and the bundle is read-only, so the
    # shipped cache is seeded into here on first use -- same pattern as models.
    tex_cache_dir: Path = STATE_DIR / "texcache"

    # chunking
    chunk_size: int = 512
    chunk_overlap: int = 50

    # search
    search_top_k: int = 10
    similarity_threshold: float = 0.3

    # server
    #
    # Loopback by DEFAULT, not 0.0.0.0, so no launcher has to remember the flag.
    # The API is unauthenticated: bound wider, anyone on the network can read the
    # library. Widen deliberately with THINKSTACK_HOST.
    host: str = "127.0.0.1"
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
