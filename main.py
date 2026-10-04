"""Backwards-compatible launcher.

Prefer ``ht`` (installed console script) or ``python -m habit_tracker``.
``python main.py --gui`` keeps working.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from habit_tracker.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
