"""Acquisitions skill scripts package.

Adds vendor/asset-management/scripts to sys.path so shared helpers (returns,
waterfall, debt_metrics, excel_style, docx_style) import as top-level modules.

Also forces UTF-8 on stdout/stderr so deal names with em-dashes and other
unicode render correctly on Windows consoles (which default to cp1252).
"""

import sys
from pathlib import Path

_VENDOR_SCRIPTS = Path(__file__).resolve().parent.parent / "vendor" / "asset-management" / "scripts"
if _VENDOR_SCRIPTS.exists() and str(_VENDOR_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_VENDOR_SCRIPTS))

# Force UTF-8 console output. No-op on POSIX (already UTF-8), fixes em-dash
# mangling on Windows.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
