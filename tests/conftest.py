"""shared test fixtures and path setup.

ensures the project root is importable so ``import config`` / ``import
domain...`` resolve when pytest is run from anywhere.
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
