"""Test configuration: ensures the repo root is on sys.path so `scripts.*`
imports cleanly when tests are run from any directory.

Tests use plain unittest — no pytest fixtures required — but conftest.py is a
conventional place for path setup and runs at collection time for both
unittest discovery (`python -m unittest discover -s tests`) and pytest.
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Importing the scripts package also adds the vendored asset-management
# scripts/ to sys.path (returns, debt_metrics, etc.).
import scripts  # noqa: E402, F401
