"""
vector store module.

provides a file-backed vector store using numpy for cosine similarity
search. stores embeddings and metadata as json files on disk, avoiding
the need for compiled c++ dependencies like hnswlib.

this is a lightweight alternative to chromadb suitable for offline
academic use with collections of up to a few thousand documents.
"""

import json
import logging
from pathlib import Path
from typing import Optional

import numpy as np

from config import settings
from infrastructure.atomic_io import atomic_write_json

logger = logging.getLogger(__name__)

_store_instance = None


class VectorStore:
    """file-backed vector store with numpy cosine similarity search."""

    def __init__(self, persist_dir: str = None):
        self.persist_dir = Path(persist_dir or str(settings.chroma_dir))
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self._data_file = self.persist_dir / "vectors.json"
        self._entries = []
        self._embeddings = None
        self._load()

    def _load(self):
        """load stored vectors from disk."""
        if self._data_file.exists():
            try:
                with open(self._data_file, "r", encoding="utf-8") as f:
                    self._entries = json.load(f)
                if self._entries:
                    self._embeddings = np.array(
                        [e["embedding"] for e in self._entries],
                        dtype=np.float32,
                    )
                else:
                    self._embeddings = None
                logger.info("loaded %d vectors from disk", len(self._entries))
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("failed to load vector store, starting fresh: %s", e)
                self._entries = []
                self._embeddings = None
        else:
            self._entries = []
            self._embeddings = None

    def _save(self):
        """persist vectors to disk atomically.

        writes to a temp file and renames it over ``vectors.json`` so a crash
        or power loss mid-write can never truncate the existing store. if the
        data is not serializable the write raises and the old file is kept.
        """
        atomic_write_json(self._data_file, self._entries)

    def _rebuild_matrix(self):
        """rebuild the numpy embedding matrix from entries."""
        if self._entries:
            self._embeddings = np.array(
                [e["embedding"] for e in self._entries],
                dtype=np.float32,
            )
        else:
            self._embeddings = None

    def upsert(
        self,
        ids: list[str],
        documents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
    ) -> int:
        """insert or update entries in the vector store.

        args:
            ids: unique identifiers for each entry.
            documents: text content for each entry.
            embeddings: embedding vectors for each entry.
            metadatas: metadata dictionaries for each entry.

        returns:
            number of entries upserted.
        """
        existing_ids = {e["id"]: i for i, e in enumerate(self._entries)}

        for entry_id, doc, emb, meta in zip(ids, documents, embeddings, metadatas):
            entry = {
                "id": entry_id,
                "document": doc,
                "embedding": emb if isinstance(emb, list) else emb.tolist(),
                "metadata": meta,
            }
            if entry_id in existing_ids:
                self._entries[existing_ids[entry_id]] = entry
            else:
                self._entries.append(entry)

        self._rebuild_matrix()
        self._save()
        return len(ids)

    def update(
        self,
        ids: list[str],
        metadatas: Optional[list[dict]] = None,
    ) -> int:
        """update metadata for existing entries without changing documents/embeddings.

        args:
            ids: list of entry ids to update.
            metadatas: list of metadata dicts corresponding to the ids.

        returns:
            number of entries updated.
        """
        existing_ids = {e["id"]: i for i, e in enumerate(self._entries)}
        updated = 0

        if metadatas:
            for entry_id, meta in zip(ids, metadatas):
                if entry_id in existing_ids:
                    self._entries[existing_ids[entry_id]]["metadata"] = meta
                    updated += 1

        if updated > 0:
            self._save()
            
        return updated

    def query(
        self,
        query_embedding: list[float],
        n_results: int = 10,
        where: Optional[dict] = None,
    ) -> dict:
        """find the most similar entries using cosine similarity.

        args:
            query_embedding: the query vector to compare against.
            n_results: maximum number of results to return.
            where: optional metadata filter dict (supports simple equality
                   and $in operator).

        returns:
            dict with ids, documents, metadatas, and distances lists.
        """
        if not self._entries or self._embeddings is None:
            return {"ids": [], "documents": [], "metadatas": [], "distances": []}

        indices = list(range(len(self._entries)))
        if where:
            indices = self._apply_filter(indices, where)

        if not indices:
            return {"ids": [], "documents": [], "metadatas": [], "distances": []}

        filtered_embeddings = self._embeddings[indices]
        query_vec = np.array(query_embedding, dtype=np.float32)

        query_norm = np.linalg.norm(query_vec)
        if query_norm == 0:
            return {"ids": [], "documents": [], "metadatas": [], "distances": []}

        embed_norms = np.linalg.norm(filtered_embeddings, axis=1)
        valid = embed_norms > 0
        similarities = np.zeros(len(filtered_embeddings))
        similarities[valid] = (
            filtered_embeddings[valid] @ query_vec
        ) / (embed_norms[valid] * query_norm)

        distances = 1.0 - similarities

        top_k = min(n_results, len(indices))
        top_indices = np.argsort(distances)[:top_k]

        result_ids = []
        result_docs = []
        result_metas = []
        result_dists = []

        for idx in top_indices:
            original_idx = indices[idx]
            entry = self._entries[original_idx]
            result_ids.append(entry["id"])
            result_docs.append(entry["document"])
            result_metas.append(entry["metadata"])
            result_dists.append(float(distances[idx]))

        return {
            "ids": result_ids,
            "documents": result_docs,
            "metadatas": result_metas,
            "distances": result_dists,
        }

    def get(
        self,
        where: Optional[dict] = None,
        ids: Optional[list[str]] = None,
    ) -> dict:
        """retrieve entries by filter or ids.

        args:
            where: optional metadata filter.
            ids: optional list of specific ids to retrieve.

        returns:
            dict with ids, documents, and metadatas lists.
        """
        indices = list(range(len(self._entries)))

        if ids:
            id_set = set(ids)
            indices = [i for i in indices if self._entries[i]["id"] in id_set]

        if where:
            indices = self._apply_filter(indices, where)

        result_ids = []
        result_docs = []
        result_metas = []

        for idx in indices:
            entry = self._entries[idx]
            result_ids.append(entry["id"])
            result_docs.append(entry["document"])
            result_metas.append(entry["metadata"])

        return {
            "ids": result_ids,
            "documents": result_docs,
            "metadatas": result_metas,
        }

    def delete(self, ids: list[str]) -> int:
        """delete entries by their ids.

        args:
            ids: list of entry ids to remove.

        returns:
            number of entries deleted.
        """
        id_set = set(ids)
        original_count = len(self._entries)
        self._entries = [e for e in self._entries if e["id"] not in id_set]
        deleted = original_count - len(self._entries)

        if deleted > 0:
            self._rebuild_matrix()
            self._save()

        return deleted

    def count(self) -> int:
        """return the total number of entries in the store."""
        return len(self._entries)

    def _apply_filter(self, indices: list[int], where: dict) -> list[int]:
        """apply metadata filters to a list of indices.

        supports simple equality checks and the $in operator for
        matching against a list of values.

        args:
            indices: list of entry indices to filter.
            where: filter dictionary.

        returns:
            filtered list of indices.
        """
        result = []
        for idx in indices:
            meta = self._entries[idx]["metadata"]
            match = True
            for key, value in where.items():
                if isinstance(value, dict) and "$in" in value:
                    if meta.get(key) not in value["$in"]:
                        match = False
                        break
                else:
                    if meta.get(key) != value:
                        match = False
                        break
            if match:
                result.append(idx)
        return result


def get_vector_store() -> VectorStore:
    """return the singleton vector store instance.

    returns:
        the shared VectorStore instance.
    """
    global _store_instance
    if _store_instance is None:
        _store_instance = VectorStore()
    return _store_instance
