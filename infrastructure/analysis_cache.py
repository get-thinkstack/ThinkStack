"""per-document analysis cache.

the gap-finder's most expensive step is the per-paper summary+claims llm
call. because a document's chunk text is immutable for a given ``doc_id`` (a
fresh uuid is minted on every upload), that analysis only ever needs to run
once per paper. this module persists the result keyed by ``doc_id`` so a gap
scan of already-analyzed papers skips the per-paper calls entirely.

storage is a single json file (``doc_analysis.json``) written atomically, so a
crash mid-write never corrupts it. a corrupt or missing file is treated as an
empty cache -- a stale cache only costs a recompute, never correctness.
"""

import json
import logging
from pathlib import Path
from typing import Optional, Union

from config import settings
from infrastructure.atomic_io import atomic_write_json

logger = logging.getLogger(__name__)


class DocAnalysisCache:
    """file-backed cache of ``doc_id -> {summary, claims}``."""

    def __init__(self, path: Union[str, Path, None] = None):
        self._path = Path(path) if path is not None else settings.data_dir / "doc_analysis.json"
        self._entries: dict = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            self._entries = {}
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._entries = data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("could not load analysis cache, starting empty: %s", e)
            self._entries = {}

    def get(self, doc_id: str) -> Optional[dict]:
        """return the cached ``{summary, claims}`` for ``doc_id``, or None."""
        entry = self._entries.get(doc_id)
        return dict(entry) if isinstance(entry, dict) else None

    def put(self, doc_id: str, summary: str, claims: list) -> None:
        """store the analysis for ``doc_id`` and persist it atomically."""
        self._entries[doc_id] = {"summary": summary, "claims": claims}
        atomic_write_json(self._path, self._entries)

    def merge(
        self,
        doc_id: str,
        summary: Optional[str] = None,
        claims: Optional[list] = None,
    ) -> None:
        """store only the halves that were passed, keeping the rest.

        the analysis routes produce one half at a time -- ``/summarize`` has no
        claims and ``/claims`` has no summary -- so ``put`` would erase whatever
        the other one, or the ingest-time precompute, had already written.
        """
        entry = self._entries.setdefault(doc_id, {"summary": "", "claims": []})
        if summary is not None:
            entry["summary"] = summary
        if claims is not None:
            entry["claims"] = claims
        atomic_write_json(self._path, self._entries)

    def delete(self, doc_id: str) -> None:
        """remove the cached analysis for ``doc_id`` if present, and persist."""
        if doc_id in self._entries:
            del self._entries[doc_id]
            atomic_write_json(self._path, self._entries)


# app-wide singleton bound to the writable state dir.
doc_analysis_cache = DocAnalysisCache()
