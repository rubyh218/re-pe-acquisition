"""Acquisitions skill scripts package.

Adds vendor/asset-management/scripts to sys.path so shared helpers (returns,
waterfall, debt_metrics, excel_style, docx_style) import as top-level modules.
"""

import sys
from pathlib import Path

_VENDOR_SCRIPTS = Path(__file__).resolve().parent.parent / "vendor" / "asset-management" / "scripts"
if _VENDOR_SCRIPTS.exists() and str(_VENDOR_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_VENDOR_SCRIPTS))
