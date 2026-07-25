"""cross-paper analysis run history (summaries / claims / themes).

a RunHistoryStore bound to ``analysis_history.json``. each saved run records
its analysis ``type`` so the ui can re-render the right view when a past run
is reopened.
"""

from config import settings
from infrastructure.run_history import RunHistoryStore

analysis_history = RunHistoryStore(settings.data_dir / "analysis_history.json")
