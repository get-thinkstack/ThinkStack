"""Text -> 384-dimension vectors, with all-MiniLM-L6-v2 on the CPU.

Used by the repository (ingest) and semantic search (queries). The model is
imported lazily and cached, so the backend starts without loading torch.
"""

from __future__ import annotations

import logging
import sys

from config import settings

logger = logging.getLogger(__name__)

# Deferred import (see get_model): importing sentence_transformers pulls in
# torch, and at module load that delays the backend socket, and so the loading
# screen, by seconds on every launch.
_model = None


def get_model():
    """Load the model once: the bundled copy if present, else by name (source
    checkouts resolve that from the HF cache or hub).

    Always CPU: it is small and fast there, and GPU memory belongs to the LLM.
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
    """One vector per text, as float lists."""
    model = get_model()
    embeddings = model.encode(texts, show_progress_bar=False)
    return embeddings.tolist()


def generate_embedding(text: str) -> list[float]:
    """One text's vector."""
    return generate_embeddings([text])[0]
