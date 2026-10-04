"""A GitHub-style contribution heatmap for Tkinter.

The grid is built by :func:`habit_tracker.tracker.heatmap_grid`, which snaps to
Monday and emits one column per calendar week, so columns always line up with
weeks and rows always line up with weekdays.

Cells are clickable and report the day they represent back to the application.
"""

from __future__ import annotations

import tkinter as tk
from datetime import date
from tkinter import ttk

from . import tracker
from .theme import Palette, resolve_palette

WEEKS = 12
CELL = 14
GAP = 2

ROW_LABELS = {0: "Mon", 2: "Wed", 4: "Fri", 6: "Sun"}


def palette_for_status(palette: Palette, status: str) -> str:
    """Background colour for one cell status."""
    return {
        tracker.DONE: palette.success,
        tracker.MISS: palette.missed,
        tracker.FUTURE: palette.future,
    }.get(status, palette.missed)


class Heatmap(ttk.Frame):
    """Week-aligned heatmap with click and hover feedback."""

    def __init__(
        self,
        master,
        data: dict | None = None,
        on_select=None,
        weeks: int = WEEKS,
        palette: Palette | None = None,
        **kwargs,
    ):
        super().__init__(master, **kwargs)
        self.data = data if data is not None else {"sessions": {}}
        self.on_select = on_select
        self.weeks = weeks
        self.palette = palette or resolve_palette()
        self.cells: list[tk.Label] = []
        self.status_var = tk.StringVar(value="")
        self._build()

    def set_palette(self, palette: Palette) -> None:
        """Adopt a new palette and rebuild every widget."""
        self.palette = palette
        for child in self.winfo_children():
            child.destroy()
        self.cells.clear()
        self._build()

    def _build(self) -> None:
        palette = self.palette
        grid = tracker.heatmap_grid(self.data, weeks=self.weeks)
        labels = tracker.heatmap_month_labels(grid)

        for row, text in ROW_LABELS.items():
            tk.Label(
                self,
                text=text,
                background=palette.background,
                foreground=palette.text_muted,
                font=("Segoe UI", 7),
            ).grid(row=row + 1, column=0, sticky="w", padx=(0, 3))

        for col in range(self.weeks):
            tk.Label(
                self,
                text=labels.get(col, ""),
                background=palette.background,
                foreground=palette.text_muted,
                font=("Segoe UI", 7),
            ).grid(row=0, column=col + 1, sticky="w")

        for cell in grid:
            widget = tk.Label(
                self,
                text="",
                width=2,
                height=1,
                background=palette_for_status(palette, cell["status"]),
                relief="flat",
                borderwidth=0,
                highlightthickness=1,
                highlightbackground=palette.border,
                highlightcolor=palette.accent,
            )
            widget.grid(row=cell["row"] + 1, column=cell["col"] + 1, padx=GAP // 2, pady=GAP // 2)
            widget.bind("<Button-1>", lambda _event, day=cell["day"]: self._clicked(day))
            widget.bind("<Enter>", lambda _event, day=cell["day"]: self._hovered(day))
            widget.bind("<Leave>", lambda _event: self._left())
            self.cells.append(widget)

        ttk.Label(self, textvariable=self.status_var, anchor="w").grid(
            row=9, column=0, columnspan=self.weeks + 1, sticky="w", pady=(6, 0)
        )
        self._build_legend()

    def _build_legend(self) -> None:
        legend = ttk.Frame(self)
        legend.grid(row=10, column=0, columnspan=self.weeks + 1, sticky="w", pady=(4, 0))
        ttk.Label(legend, text="Less", style="Muted.TLabel").pack(side="left")
        for status in (tracker.FUTURE, tracker.MISS, tracker.DONE):
            swatch = tk.Label(
                legend,
                text=" ",
                background=palette_for_status(self.palette, status),
                width=2,
                height=1,
                borderwidth=0,
            )
            swatch.pack(side="left", padx=1)
        ttk.Label(legend, text="More", style="Muted.TLabel").pack(side="left")

    def _clicked(self, day: date) -> None:
        if self.on_select is not None:
            self.on_select(day)

    def _hovered(self, day: date) -> None:
        status = tracker.day_status(self.data, day)
        note = tracker.note_for(self.data, day)
        suffix = f" - {note}" if note else ""
        self.status_var.set(f"{day.isoformat()}  {status}{suffix}")

    def _left(self) -> None:
        self.status_var.set("")

    def refresh(self, data: dict) -> None:
        """Repaint every cell from new data, without rebuilding the widgets."""
        self.data = data
        grid = tracker.heatmap_grid(self.data, weeks=self.weeks)
        for widget, cell in zip(self.cells, grid, strict=False):
            widget.configure(background=palette_for_status(self.palette, cell["status"]))
