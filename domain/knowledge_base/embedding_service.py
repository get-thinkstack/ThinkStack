"""
embedding service module.

provides local embedding generation using sentence-transformers.
the model is loaded once and cached in memory for efficient reuse
across embedding requests.
"""

from __future__ import annotations

import logging
import sys

from config import settings

logger = logging.getLogger(__name__)

# typed as Any-in-practice; the real import is deferred (see get_model). importing
# sentence_transformers pulls in torch + transformers (~4s warm, far worse in a
# frozen build), and doing it at module load is what made the backend socket — and
# therefore the tauri loading screen — wait seconds on every launch. keeping it
# lazy lets the server come up in ~1s; torch loads only on the first embed.
_model = None


def get_model():
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
        # lazy import: keep torch/transformers out of backend startup.
        from sentence_transformers import SentenceTransformer

        bundled = settings.bundled_embedding_dir
        if bundled.is_dir():
            source = str(bundled)
        else:
            # No bundled copy. From source this is fine -- the hub or the local
            # HF cache resolves it. In a frozen build it is a packaging fault,
            # and the symptom is the worst kind: sentence-transformers retries
            # the hub with long timeouts, so an offline app appears to hang for
            # minutes instead of reporting anything. Say so before we block.
            source = settings.embedding_model
            if getattr(sys, "frozen", False):
                logger.error(
                    "embedding model not bundled at %s -- falling back to a "
                    "network download of %r, which cannot succeed offline. "
                    "this is a packaging fault, not a user error.",
                    bundled,
                    source,
                )

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
