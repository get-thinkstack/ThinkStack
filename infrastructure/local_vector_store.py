"""The vector store: chunks persisted in SQLite, searched exactly in NumPy.

Persistence and search are separate on purpose (ADR 2026-08-22):

    persistence   SQLite (`vectors.db`, WAL): text, metadata as JSON, embedding
                  as a float32 blob. A write touches only its rows.
    search        every embedding held in one NumPy matrix; a query is
                  compared against all of them. Exact, no ANN index.

SQLite is in the standard library, so it adds nothing for PyInstaller to miss;
do not replace it with ChromaDB or FAISS (compiled extensions). An old
`vectors.json` is imported once on first open and renamed, never deleted.

Writes go through domain/knowledge_base/repository.py; semantic_search,
grounding and graph_builder read directly.
"""

import json
import logging
import sqlite3
from pathlib import Path
from typing import Optional

import numpy as np

from config import settings

logger = logging.getLogger(__name__)

_store_instance = None


class VectorStore:
    """SQLite-backed chunks, an in-memory embedding matrix, exact cosine search.

    The interface (`upsert`, `query`, `get`, `where` filters with equality and
    `$in`) mirrors a Chroma collection's, so the repository reads like one.
    """

    def __init__(self, persist_dir: str = None):
        self.persist_dir = Path(persist_dir or str(settings.chroma_dir))
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self._data_file = self.persist_dir / "vectors.json"   # legacy, migrated
        self._db_file = self.persist_dir / "vectors.db"
        self._entries = []
        self._embeddings = None
        self._connect()
        self._migrate_json_if_present()
        self._load()

    # ---------------------------------------------------------------- storage

    def _connect(self):
        """Open the database and make sure the schema is there.

        `check_same_thread=False` because the job queue writes from a worker
        while requests read on the event loop thread; access is serialised by
        the GIL around short statements, and WAL lets a reader proceed during a
        write rather than blocking on it.
        """
        self._con = sqlite3.connect(str(self._db_file), check_same_thread=False)
        self._con.execute("PRAGMA journal_mode=WAL")
        self._con.execute("PRAGMA synchronous=NORMAL")
        self._con.execute(
            """CREATE TABLE IF NOT EXISTS chunks (
                   id        TEXT PRIMARY KEY,
                   doc_id    TEXT,
                   document  TEXT NOT NULL,
                   embedding BLOB NOT NULL,
                   metadata  TEXT NOT NULL
               )"""
        )
        self._con.execute("CREATE INDEX IF NOT EXISTS ix_chunks_doc ON chunks(doc_id)")
        self._con.commit()

    def _migrate_json_if_present(self):
        """One-time import of the old vectors.json.

        This runs on a stranger's machine, once, with their entire library at
        stake, and it gets no second chance if it is wrong. Hence:

        * the source is never removed until the rows are committed AND counted
          back out of the database;
        * one malformed entry costs that entry, not the library. An upgrade
          that discards a corpus because a single row lost a key would be worse
          than the problem it is fixing;
        * a source that cannot be read at all is left exactly where it is and
          said out loud, rather than quietly starting empty -- a user whose
          papers vanish silently has no way to know anything went wrong;
        * the whole import is one transaction, so an interruption leaves an
          empty table and the untouched JSON, which is a state this function
          knows how to resume from.
        """
        if not self._data_file.exists():
            return
        if self._con.execute("SELECT 1 FROM chunks LIMIT 1").fetchone():
            return                      # already migrated; leave both alone

        try:
            entries = json.loads(self._data_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            logger.error(
                "vectors.json exists but could not be read, so it has NOT been "
                "migrated and has NOT been touched: %s. the library will appear "
                "empty until this is resolved; the file is still at %s",
                e, self._data_file,
            )
            return

        if not isinstance(entries, list) or not entries:
            return

        good, skipped = [], 0
        for e in entries:
            try:
                if (
                    isinstance(e, dict)
                    and isinstance(e.get("id"), str)
                    and e.get("embedding")
                    and e.get("document") is not None
                ):
                    good.append(e)
                else:
                    skipped += 1
            except Exception:            # noqa: BLE001 - a row must never abort the run
                skipped += 1

        if not good:
            logger.error(
                "vectors.json held %d entries and none were usable; leaving it "
                "in place rather than migrating an empty store", len(entries)
            )
            return

        try:
            with self._con:                      # one transaction; rolls back on error
                for i in range(0, len(good), 500):
                    self._write_rows(good[i:i + 500], commit=False)
        except (sqlite3.DatabaseError, ValueError, TypeError) as e:
            logger.error("migration failed and was rolled back, vectors.json kept: %s", e)
            return

        stored = self._con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        if stored < len(good):
            logger.error(
                "migration stored %d of %d entries; vectors.json kept", stored, len(good)
            )
            return

        # Only now is the source expendable, and it is renamed rather than
        # deleted: a downgrade should still find its data.
        try:
            self._data_file.rename(self._data_file.with_suffix(".json.migrated"))
        except OSError as e:
            # Windows will refuse this if anything else holds the file open. The
            # guard above is "does the table have rows", not "is the file gone",
            # so a failed rename costs disk space and nothing else.
            logger.warning("migrated %d vectors but could not rename the source: %s",
                           stored, e)

        if skipped:
            logger.warning("migration skipped %d malformed entr%s",
                           skipped, "y" if skipped == 1 else "ies")
        logger.info("migrated %d vectors from vectors.json into sqlite", stored)

    @staticmethod
    def _pack(embedding) -> bytes:
        return np.asarray(embedding, dtype=np.float32).tobytes()

    @staticmethod
    def _unpack(blob: bytes) -> list:
        return np.frombuffer(blob, dtype=np.float32).tolist()

    def _write_rows(self, entries: list[dict], commit: bool = True):
        """Insert or replace exactly these entries. Nothing else is touched."""
        self._con.executemany(
            "INSERT OR REPLACE INTO chunks VALUES (?,?,?,?,?)",
            [
                (
                    e["id"],
                    (e.get("metadata") or {}).get("doc_id"),
                    e["document"],
                    self._pack(e["embedding"]),
                    json.dumps(e.get("metadata") or {}),
                )
                for e in entries
            ],
        )
        if commit:
            self._con.commit()

    def _load(self):
        """Read every row into memory, once, at startup.

        The whole corpus is held resident because that is what the search
        needs: one matrix, compared in full. Reading it back is a scan of a
        b-tree and a memoryview per blob, which is roughly an order of
        magnitude cheaper than parsing the equivalent JSON.
        """
        self._entries = []
        try:
            rows = self._con.execute(
                "SELECT id, document, embedding, metadata FROM chunks"
            ).fetchall()
        except sqlite3.DatabaseError as e:
            logger.warning("failed to read vector store, starting fresh: %s", e)
            self._embeddings = None
            return

        mat = []
        for entry_id, document, blob, meta in rows:
            vec = np.frombuffer(blob, dtype=np.float32)
            self._entries.append(
                {
                    "id": entry_id,
                    "document": document,
                    "embedding": vec.tolist(),
                    "metadata": json.loads(meta),
                }
            )
            mat.append(vec)

        # Ragged widths cannot happen through this class, but a store written
        # by an older build or edited by hand can still contain them, and
        # vstack raises rather than returning something usable. Startup must
        # survive a bad row: the alternative is an application that will not
        # open at all, which is strictly worse than one missing a vector.
        widths = {v.shape[0] for v in mat}
        if len(widths) > 1:
            keep = max(widths, key=lambda w: sum(1 for v in mat if v.shape[0] == w))
            logger.error(
                "vector store holds mixed embedding widths %s; keeping the %d "
                "that are %d-dimensional and ignoring the rest",
                sorted(widths), sum(1 for v in mat if v.shape[0] == keep), keep,
            )
            paired = [(e, v) for e, v in zip(self._entries, mat) if v.shape[0] == keep]
            self._entries = [e for e, _ in paired]
            mat = [v for _, v in paired]

        self._embeddings = np.vstack(mat) if mat else None
        logger.info("loaded %d vectors from sqlite", len(self._entries))

    def _rebuild_matrix(self):
        """Rebuild the in-memory embedding matrix from the entries."""
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
        """Insert or replace entries (parallel lists). Returns how many."""
        existing_ids = {e["id"]: i for i, e in enumerate(self._entries)}
        touched = []

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
            touched.append(entry)

        self._rebuild_matrix()
        # Only these rows are written, so an ingest costs the same however large
        # the library is.
        self._write_rows(touched)
        return len(ids)

    def update(
        self,
        ids: list[str],
        metadatas: Optional[list[dict]] = None,
    ) -> int:
        """Replace metadata of existing entries; text and vectors untouched.
        Returns how many were updated."""
        existing_ids = {e["id"]: i for i, e in enumerate(self._entries)}
        updated = 0

        if metadatas:
            for entry_id, meta in zip(ids, metadatas):
                if entry_id in existing_ids:
                    self._entries[existing_ids[entry_id]]["metadata"] = meta
                    updated += 1

        if updated > 0:
            self._con.executemany(
                "UPDATE chunks SET metadata = ?, doc_id = ? WHERE id = ?",
                [
                    (
                        json.dumps(self._entries[existing_ids[i]]["metadata"]),
                        (self._entries[existing_ids[i]]["metadata"] or {}).get("doc_id"),
                        i,
                    )
                    for i in ids
                    if i in existing_ids
                ],
            )
            self._con.commit()

        return updated

    def set_documents(self, texts_by_id: dict[str, str]) -> int:
        """Replace the text of existing entries; metadata and vectors untouched.
        Returns how many were updated."""
        index = {e["id"]: i for i, e in enumerate(self._entries)}
        rows = [(text, cid) for cid, text in texts_by_id.items() if cid in index]
        for text, cid in rows:
            self._entries[index[cid]]["document"] = text
        if rows:
            self._con.executemany("UPDATE chunks SET document = ? WHERE id = ?", rows)
            self._con.commit()
        return len(rows)

    def query(
        self,
        query_embedding: list[float],
        n_results: int = 10,
        where: Optional[dict] = None,
    ) -> dict:
        """The `n_results` nearest entries by cosine, optionally filtered by
        `where`. Returns `{ids, documents, metadatas, distances}`."""
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
        """Entries by `where` filter or `ids`, without embeddings.
        Returns `{ids, documents, metadatas}`."""
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

    def get_embeddings(self, where: Optional[dict] = None) -> dict:
        """The stored vectors themselves, for centroids (LitGraph, themes).

        Returns `{ids, embeddings (n, d) array or None, metadatas}`. `get`
        omits embeddings on purpose: its callers want text.
        """
        indices = list(range(len(self._entries)))

        if where:
            indices = self._apply_filter(indices, where)

        if not indices:
            return {"ids": [], "embeddings": None, "metadatas": []}

        return {
            "ids": [self._entries[i]["id"] for i in indices],
            "embeddings": self._embeddings[indices],
            "metadatas": [self._entries[i]["metadata"] for i in indices],
        }

    def delete(self, ids: list[str]) -> int:
        """Delete entries by id. Returns how many were removed."""
        id_set = set(ids)
        original_count = len(self._entries)
        self._entries = [e for e in self._entries if e["id"] not in id_set]
        deleted = original_count - len(self._entries)

        if deleted > 0:
            self._rebuild_matrix()
            self._con.executemany(
                "DELETE FROM chunks WHERE id = ?", [(i,) for i in id_set]
            )
            self._con.commit()

        return deleted

    def count(self) -> int:
        """Total entries."""
        return len(self._entries)

    def _apply_filter(self, indices: list[int], where: dict) -> list[int]:
        """The indices whose metadata match `where` (equality, or `$in`)."""
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
    """The process-wide VectorStore, created on first use."""
    global _store_instance
    if _store_instance is None:
        _store_instance = VectorStore()
    return _store_instance
