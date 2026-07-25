"""gap-analysis run history.

a RunHistoryStore bound to ``gap_history.json`` so a new gap scan no longer
discards the previous result -- past runs stay available to reopen.
"""

from config import settings
from infrastructure.run_history import RunHistoryStore

# back-compat alias: existing imports/tests refer to GapHistoryStore.
GapHistoryStore = RunHistoryStore

# app-wide singleton bound to the writable state dir.
gap_history = RunHistoryStore(settings.data_dir / "gap_history.json")
