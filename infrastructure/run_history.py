"""generic run-history store.

a capped, newest-first log of past feature runs (gap analysis, cross-paper
analysis) that a user may want to revisit instead of losing on the next run.
each feature binds one instance to its own json file, written atomically; a
corrupt or missing file is treated as empty history -- a stale log only costs
history, never correctness.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from infrastructure.atomic_io import atomic_write_json

logger = logging.getLogger(__name__)

DEFAULT_MAX_RUNS = 50


class RunHistoryStore:
    """file-backed, newest-first log of runs keyed by an assigned run_id."""

    def __init__(self, path: Union[str, Path], max_runs: int = DEFAULT_MAX_RUNS):
        self._path = Path(path)
        self._max_runs = max_runs
        self._runs: list = []
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            self._runs = []
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._runs = data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("could not load run history %s, starting empty: %s", self._path.name, e)
            self._runs = []

    def add(self, run: dict) -> dict:
        """save a run, assigning it an id and timestamp.

        the run is prepended (newest first) and the log is trimmed to the
        retention cap. returns the stored record (with run_id / created_at).
        """
        record = {
            "run_id": uuid.uuid4().hex[:8],
            "created_at": datetime.now(timezone.utc).isoformat(),
            **run,
        }
        self._runs.insert(0, record)
        del self._runs[self._max_runs:]
        atomic_write_json(self._path, self._runs)
        return dict(record)

    def list(self) -> list:
        """return all saved runs, newest first."""
        return [dict(r) for r in self._runs]

    def get(self, run_id: str) -> Optional[dict]:
        """return a single run by id, or None."""
        for r in self._runs:
            if r.get("run_id") == run_id:
                return dict(r)
        return None

    def delete(self, run_id: str) -> bool:
        """remove a run by id. returns True if one was removed."""
        for i, r in enumerate(self._runs):
            if r.get("run_id") == run_id:
                del self._runs[i]
                atomic_write_json(self._path, self._runs)
                return True
        return False
