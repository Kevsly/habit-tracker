"""Entry point for the frozen desktop build.

PyInstaller runs its entry script as top-level ``__main__``, so pointing it
straight at ``habit_tracker/gui.py`` breaks every relative import inside the
package. This launcher imports the package by absolute name instead, which is
what PyInstaller can analyse.

    python -m pip install -e ".[all,build]"
    pyinstaller habit_tracker.spec
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from habit_tracker.gui import main

if __name__ == "__main__":
    main()
