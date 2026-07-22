"""
embedding service module.

provides local embedding generation using sentence-transformers.
the model is loaded once and cached in memory for efficient reuse
across embedding requests.
"""

import logging

from sentence_transformers import SentenceTransformer

from config import settings

logger = logging.getLogger(__name__)

_model: SentenceTransformer | None = None


def get_model() -> SentenceTransformer:
    """load and cache the sentence-transformer embedding model.

    prefers the copy shipped inside the bundle so a packaged build never
    reaches out to huggingface on first use -- an offline-first app must not
    need the network to embed its first document. falls back to the model
    name (hub download / local hf cache) when running from source.

    the model always runs on the cpu: it is a 22M-parameter MiniLM and
    embedding a 64-chunk batch takes ~0.2s there, so spending vram on it
    would only steal headroom from the gguf that actually needs the gpu.

    returns:
        the loaded SentenceTransformer model.
    """
    global _model
    if _model is None:
        bundled = settings.bundled_embedding_dir
        source = str(bundled) if bundled.is_dir() else settings.embedding_model
        logger.info("loading embedding model: %s (cpu)", source)
        _model = SentenceTransformer(source, device="cpu")
        logger.info("embedding model loaded")
    return _model


def generate_embeddings(texts: list[str]) -> list[list[float]]:
    """generate embeddings for a batch of text strings.

    args:
        texts: list of text strings to embed.

    returns:
        list of embedding vectors as float lists.
    """
    model = get_model()
    embeddings = model.encode(texts, show_progress_bar=False)
    return embeddings.tolist()


def generate_embedding(text: str) -> list[float]:
    """generate an embedding for a single text string.

    args:
        text: the text string to embed.

    returns:
        embedding vector as a float list.
    """
    return generate_embeddings([text])[0]
