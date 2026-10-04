"""Date and note input for the GUI.

Uses ``tkcalendar``'s :class:`DateEntry` when it is installed and falls back to
a plain text prompt otherwise, so the GUI works with no extra packages.
"""

from __future__ import annotations

from datetime import date
from tkinter import simpledialog

try:
    from tkcalendar import DateEntry

    HAS_TKCALENDAR = True
except ImportError:
    DateEntry = None
    HAS_TKCALENDAR = False


def pick_date(parent=None, initial: date | None = None, title: str = "Select date") -> date | None:
    """Ask the user for a date. ``None`` if cancelled."""
    if HAS_TKCALENDAR:
        return _calendar_pick(parent, initial or date.today(), title)
    return _text_pick(parent, title)


def _calendar_pick(parent, initial: date, title: str) -> date | None:
    from tkinter import Toplevel, ttk

    dialog = Toplevel(parent)
    dialog.title(title)
    dialog.transient(parent)
    dialog.resizable(False, False)
    dialog.grab_set()

    chosen: list[date] = []

    def accept() -> None:
        chosen.append(entry.get_date())
        dialog.destroy()

    frame = ttk.Frame(dialog, padding=10)
    frame.grid(row=0, column=0, sticky="nsew")
    entry = DateEntry(frame, date_pattern="yyyy-mm-dd", year=initial.year, month=initial.month)
    entry.grid(row=0, column=0, padx=4, pady=4)
    ttk.Button(frame, text="Select", command=accept).grid(row=0, column=1, padx=4, pady=4)

    dialog.bind("<Return>", lambda _event: accept())
    dialog.bind("<Escape>", lambda _event: dialog.destroy())
    parent.wait_window(dialog)
    return chosen[0] if chosen else None


def _text_pick(parent, title: str) -> date | None:
    from .dates import DateParseError, accepted_formats, parse_date

    raw = simpledialog.askstring(title, f"Date ({accepted_formats()}):", parent=parent)
    if not raw:
        return None
    try:
        return parse_date(raw)
    except DateParseError:
        return None


def ask_note(
    parent=None,
    initial: str = "",
    title: str = "Note",
    prompt: str = "Note",
) -> str | None:
    """Ask for free text. ``None`` if cancelled."""
    return simpledialog.askstring(title, prompt, initialvalue=initial, parent=parent)
