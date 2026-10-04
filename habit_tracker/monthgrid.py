"""A clickable month calendar for the desktop window.

Wraps :mod:`habit_tracker.calendar`, which owns the grid maths, so the GUI and
``ht month`` always agree. This module only draws the result and reports
clicks.

Like every other GUI module it is imported lazily, so a machine without
Tkinter can still use the CLI.
"""

from __future__ import annotations

import contextlib
import tkinter as tk
from collections.abc import Callable
from datetime import date
from tkinter import ttk

from . import calendar as month_calendar
from .theme import Palette, resolve_palette


class MonthGrid(ttk.Frame):
    """One month as a 7-column grid of buttons.

    Buttons rather than labels so every day is clickable, which is what makes
    any historical date reachable without typing.
    """

    def __init__(
        self,
        master: tk.Misc,
        view: dict,
        on_select: Callable[[date], None] | None = None,
        today: date | None = None,
        palette: Palette | None = None,
    ) -> None:
        super().__init__(master, padding=6)
        self.on_select = on_select
        self.view = view
        self.today = today or date.today()
        self.palette = palette or resolve_palette()
        self.anchor = self.today.replace(day=1)
        self.summary: month_calendar.MonthSummary | None = None
        self._buttons: dict[date, ttk.Button] = {}
        self._blanks: list[ttk.Label] = []
        self._ensure_styles()

        header = ttk.Frame(self)
        header.pack(fill="x")
        ttk.Button(header, text="<", width=3, command=self.previous_month).pack(side="left")
        self.title_var = tk.StringVar()
        ttk.Label(header, textvariable=self.title_var, anchor="center").pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(header, text=">", width=3, command=self.next_month).pack(side="right")

        grid = ttk.Frame(self)
        grid.pack(fill="both", expand=True, pady=(6, 0))
        for column, label in enumerate(month_calendar.MONTH_HEADER):
            ttk.Label(grid, text=label, anchor="center", width=5).grid(row=0, column=column)
        for column in range(7):
            grid.columnconfigure(column, weight=1, uniform="day")

        # The headers and the day cells must share one grid, otherwise the
        # columns they each line up in are unrelated.
        self.body = grid
        self.refresh()

    # -- navigation -------------------------------------------------------

    def previous_month(self) -> None:
        self.anchor = _shift_month(self.anchor, -1)
        self.refresh()

    def next_month(self) -> None:
        self.anchor = _shift_month(self.anchor, 1)
        self.refresh()

    def set_view(self, view: dict) -> month_calendar.MonthSummary:
        """Point the grid at a different habit and redraw. Returns the summary."""
        self.view = view
        return self.refresh()

    # -- rendering --------------------------------------------------------

    def refresh(self) -> None:
        weeks = month_calendar.month_grid(self.anchor, self.view, today=self.today)
        summary = month_calendar.month_summary(self.anchor, self.view, today=self.today)
        self.title_var.set(self.anchor.strftime("%B %Y"))

        for button in self._buttons.values():
            button.destroy()
        self._buttons.clear()
        for blank in self._blanks:
            blank.destroy()
        self._blanks.clear()

        for row_index, week in enumerate(weeks, start=1):
            for column, cell in enumerate(week):
                if cell.day is None:
                    blank = ttk.Label(self.body, text="", width=5)
                    blank.grid(row=row_index, column=column)
                    self._blanks.append(blank)
                    continue
                button = ttk.Button(
                    self.body, text=str(cell.day.day), width=4, command=self._make_handler(cell.day)
                )
                button.grid(row=row_index, column=column, padx=1, pady=1)
                self._style(button, cell)
                self._buttons[cell.day] = button

        self.summary = summary
        return summary

    def _ensure_styles(self) -> None:
        """Register the four cell styles from the active palette.

        This is the only place a day cell gets its colour: ``ttk::button`` has no
        ``-background`` option, so setting one directly raises a ``TclError``.

        The explicit ``layout`` call matters as much as the ``configure`` one.
        ``ttk`` does not give a brand-new style a layout on its own, so a button
        asked to use it fails with "Layout ... not found" and silently falls back
        to the default style. Without this, every day renders identically.
        """
        style = ttk.Style(self)
        palette = self.palette
        layout = style.layout("TButton")
        for name, background, foreground in (
            ("done", palette.success, palette.on_accent),
            ("today", palette.accent, palette.on_accent),
            ("plain", palette.missed, palette.text),
            ("future", palette.future, palette.text),
        ):
            style_name = f"Month.{name}"
            style.layout(style_name, layout)
            style.configure(style_name, background=background, foreground=foreground)
            style.map(
                style_name,
                background=[("pressed", background), ("active", background)],
                foreground=[("disabled", foreground)],
            )

    def set_palette(self, palette: Palette) -> None:
        """Adopt a new palette and repaint every cell."""
        self.palette = palette
        self._ensure_styles()
        self.refresh()

    def _style(self, button: ttk.Button, cell: month_calendar.MonthCell) -> None:
        """Apply the right named style to one day button."""
        with contextlib.suppress(tk.TclError):  # pragma: no cover - defensive
            button.configure(style=style_name_for(cell))

    def _make_handler(self, day: date) -> Callable[[], None]:
        def handler() -> None:
            if self.on_select is not None:
                self.on_select(day)

        return handler


def style_name_for(cell: month_calendar.MonthCell) -> str:
    """The named ttk style that colours one cell, given the palette styles above."""
    if cell.done:
        return "Month.done"
    if cell.today:
        return "Month.today"
    if cell.future:
        return "Month.future"
    return "Month.plain"


def _shift_month(anchor: date, delta: int) -> date:
    """Move a first-of-month date by ``delta`` months."""
    index = anchor.year * 12 + (anchor.month - 1) + delta
    return date(index // 12, index % 12 + 1, 1)
