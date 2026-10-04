"""Habit tracker for coding sessions.

Three front-ends sit on one shared core:

* ``habit_tracker.cli``   -- argparse subcommands, scriptable, no TTY required
* ``habit_tracker.tui``   -- interactive full-screen terminal UI
* ``habit_tracker.gui``   -- native Tkinter desktop window

``tracker``, ``storage``, ``dates``, ``tags`` and ``config`` are pure and
depend only on the standard library, so they can be imported headlessly.
``gui`` and ``tui`` are never imported at package import time.
"""

from __future__ import annotations

__version__ = "1.0.0"
__all__ = ["__version__"]
