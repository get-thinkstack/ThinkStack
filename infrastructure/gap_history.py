"""gap-analysis run history.

A RunHistoryStore bound to ``gap_history.json``: past scans stay available to
reopen. LitGraph draws gaps from the newest one.
"""

from config import settings
from infrastructure.run_history import RunHistoryStore

# back-compat alias: existing imports/tests refer to GapHistoryStore.
GapHistoryStore = RunHistoryStore

# app-wide singleton bound to the writable state dir.
gap_history = RunHistoryStore(settings.data_dir / "gap_history.json")
