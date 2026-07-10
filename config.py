"""
thinkstack configuration module.

centralizes all application settings including paths, model names,
chunking parameters, and server configuration. uses pydantic-settings
for environment variable overrides with the THINKSTACK_ prefix.
"""

from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """application-wide configuration with sensible defaults for offline use."""

    # paths
    base_dir: Path = Path(__file__).parent
    data_dir: Path = Path(__file__).parent / "data"
    papers_dir: Path = Path(__file__).parent / "data" / "papers"
    chroma_dir: Path = Path(__file__).parent / "data" / "vectorstore"
    models_dir: Path = Path(__file__).parent / "data" / "models"

    # llm runtime
    llm_provider: str = "llama_cpp"
    llm_model_path: Path = Path(__file__).parent / "data" / "models"
    llm_ctx_size: int = 4096
    # 0 = cpu-only (works everywhere). set to -1 to offload all layers
    # to gpu if you have cuda drivers installed and sufficient vram.
    # override with THINKSTACK_LLM_GPU_LAYERS=-1 for gpu acceleration.
    llm_gpu_layers: int = 0

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

    model_config = {"env_prefix": "THINKSTACK_"}


settings = Settings()
