"""Tkinter desktop front-end.

Constructed by ``ht gui`` (or ``python -m habit_tracker gui``). This module is
never imported on the CLI code path, so the terminal interface keeps working on
machines with no Tkinter installed.

All state access goes through :class:`habit_tracker.session.Session`, the same
object the CLI and Textual front-ends use, so habit switching and undo behave
identically everywhere.
"""

from __future__ import annotations

import logging
import tkinter as tk
from datetime import date
from tkinter import messagebox, ttk

from . import backup, picker, storage, tags, tracker, ui
from .config import APP_TITLE, Settings, resolve_settings
from .heatmap import Heatmap
from .monthgrid import MonthGrid
from .session import Session, SessionError, UnknownHabit
from .theme import Palette, resolve_palette

log = logging.getLogger(__name__)

THEME_ORDER = ("system", "light", "dark")


class HabitTrackerApp:
    """Stats header, progress bar, and a Week/Heatmap/Month/Tags notebook."""

    def __init__(
        self,
        root: tk.Tk,
        *,
        settings: Settings | None = None,
        session: Session | None = None,
        theme: str | None = None,
    ):
        self.root = root
        self.settings = settings or resolve_settings()
        self.session = session or Session(self.settings)
        self.theme_mode = theme or self.settings.theme
        self.palette = resolve_palette(self.theme_mode)

        root.title(APP_TITLE)
        root.geometry("820x600")
        root.minsize(700, 520)
        ui.apply_theme(self.palette)
        _paint_root(root, self.palette)

        self.main_frame = ttk.Frame(root, padding=10)
        self.main_frame.grid(row=0, column=0, sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)

        self._build()

    # -- theming ----------------------------------------------------------

    def cycle_theme(self) -> None:
        """Move to the next appearance mode and repaint the window."""
        index = THEME_ORDER.index(self.theme_mode)
        self.set_theme(THEME_ORDER[(index + 1) % len(THEME_ORDER)])

    def set_theme(self, mode: str) -> None:
        """Switch between ``system``, ``light`` and ``dark``."""
        self.theme_mode = mode
        self.palette = resolve_palette(mode)
        ui.apply_theme(self.palette)
        _paint_root(self.root, self.palette)
        self.heatmap.set_palette(self.palette)
        self.month.set_palette(self.palette)
        self._sync_theme_button()

    def _sync_theme_button(self) -> None:
        if hasattr(self, "theme_button"):
            self.theme_button.configure(text=f"Theme: {self.palette.name}")

    # -- construction -----------------------------------------------------

    def _build(self) -> None:
        self._build_actions()

        self.stats_var = tk.StringVar()
        ttk.Label(self.main_frame, textvariable=self.stats_var).grid(
            row=1, column=0, columnspan=6, sticky="w", pady=(8, 2)
        )

        self.goal_var = tk.StringVar()
        self.progress = ttk.Progressbar(
            self.main_frame, orient="horizontal", mode="determinate", length=260
        )
        self.progress.grid(row=2, column=0, sticky="w", pady=(2, 8))
        ttk.Label(self.main_frame, textvariable=self.goal_var).grid(
            row=2, column=3, columnspan=3, sticky="e", pady=(2, 8)
        )

        self.notebook = ttk.Notebook(self.main_frame)
        self.notebook.grid(row=3, column=0, columnspan=6, sticky="nsew")
        self.main_frame.rowconfigure(3, weight=1)
        self.main_frame.columnconfigure(0, weight=1)

        self._build_week_tab()
        self._build_heatmap_tab()
        self._build_month_tab()
        self._build_tags_tab()

        self.refresh()

    def _build_actions(self) -> None:
        bar = ttk.Frame(self.main_frame)
        bar.grid(row=0, column=0, columnspan=6, sticky="w")

        ttk.Label(bar, text="Habit:").grid(row=0, column=0, padx=(0, 4))
        self.habit_var = tk.StringVar()
        self.habit_box = ttk.Combobox(bar, textvariable=self.habit_var, state="readonly", width=16)
        self.habit_box.grid(row=0, column=1, padx=(0, 8))
        self.habit_box.bind("<<ComboboxSelected>>", self._on_habit_selected)

        buttons = (
            ("Mark today", self.mark_today),
            ("Pick date", self.mark_picked_date),
            ("Clear day", self.clear_selected),
            ("Set goal", self.set_goal),
            ("Undo", self.undo_last),
            ("New habit", self.new_habit),
            ("Export", self.export),
            ("Import", self.import_data),
        )
        for offset, (text, command) in enumerate(buttons, start=2):
            ttk.Button(bar, text=text, command=command).grid(row=0, column=offset, padx=2)

        self.theme_button = ttk.Button(
            bar, text=f"Theme: {self.palette.name}", command=self.cycle_theme
        )
        self.theme_button.grid(row=0, column=2 + len(buttons), padx=(12, 2))

    def _build_week_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(tab, text="Week")

        columns = ("day", "date", "status", "note")
        self.tree = ttk.Treeview(
            tab, columns=columns, show="headings", height=8, selectmode="browse"
        )
        headings = {"day": "Day", "date": "Date", "status": "Status", "note": "Note"}
        widths = {"day": 60, "date": 110, "status": 80, "note": 360}
        for name in columns:
            self.tree.heading(name, text=headings[name])
            self.tree.column(name, width=widths[name], anchor="w")

        scrollbar = ttk.Scrollbar(tab, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        tab.rowconfigure(0, weight=1)
        tab.columnconfigure(0, weight=1)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        ttk.Label(
            tab,
            text="Tip: click a day in the Month tab, or a square in Heatmap, to edit it.",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))

    def _build_heatmap_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Heatmap")
        self.heatmap = Heatmap(
            tab, self.session.view, on_select=self.mark_day, palette=self.palette
        )
        self.heatmap.pack(anchor="w")

    def _build_month_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(tab, text="Month")
        self.month = MonthGrid(
            tab,
            self.session.view,
            on_select=self.mark_day,
            today=self.session.today(),
            palette=self.palette,
        )
        self.month.pack(anchor="n")
        self.month_summary_var = tk.StringVar()
        ttk.Label(tab, textvariable=self.month_summary_var).pack(anchor="w", pady=(8, 0))

    def _build_tags_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(tab, text="Tags")

        columns = ("tag", "count")
        self.tags_tree = ttk.Treeview(tab, columns=columns, show="headings", height=8)
        self.tags_tree.heading("tag", text="Tag")
        self.tags_tree.heading("count", text="Count")
        self.tags_tree.column("tag", width=200, anchor="w")
        self.tags_tree.column("count", width=100, anchor="e")

        scrollbar = ttk.Scrollbar(tab, orient="vertical", command=self.tags_tree.yview)
        self.tags_tree.configure(yscroll=scrollbar.set)
        tab.rowconfigure(1, weight=1)
        tab.columnconfigure(0, weight=1)
        self.tags_tree.grid(row=1, column=0, sticky="nsew")
        scrollbar.grid(row=1, column=1, sticky="ns")

        form = ttk.Frame(tab)
        form.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        ttk.Label(form, text="Add tags to selected day:").grid(row=0, column=0, padx=(0, 6))
        self.tag_entry = ttk.Entry(form, width=30)
        self.tag_entry.grid(row=0, column=1, padx=(0, 6))
        self.tag_entry.bind("<Return>", lambda _event: self.add_tags_to_selected())
        ttk.Button(form, text="Add", command=self.add_tags_to_selected).grid(row=0, column=2)

    # -- rendering --------------------------------------------------------

    def _sync_habit_box(self) -> None:
        names = [row["name"] for row in self.session.habits()]
        self.habit_box.configure(values=names)
        self.habit_var.set(self.session.habit_label)

    def refresh(self) -> None:
        """Rebuild every view from the current session."""
        session = self.session
        view = session.view
        today = session.today()
        start = tracker.week_start(today)

        done, goal = tracker.week_progress(view, start, today)
        streak = tracker.current_streak(view, today)
        longest = tracker.longest_streak(view)
        total = tracker.total_sessions(view)
        top, top_count = tracker.busiest_weekday(view)

        busiest = f"{top} ({top_count})" if top else "no data yet"
        self.stats_var.set(
            f"{session.habit_label}   Streak {streak}  |  Longest {longest}  |  "
            f"Total {total}  |  Most active {busiest}"
        )
        self.progress.configure(value=progress_value(done, goal))
        self.goal_var.set(
            "weekly goal off" if goal <= 0 else f"{progress_value(done, goal)}% of {goal}"
        )

        self.tree.delete(*self.tree.get_children())
        for row in tracker.week_rows(view, start, today):
            status = "DONE" if row["done"] else ("FUTURE" if row["future"] else "TODO")
            self.tree.insert(
                "",
                tk.END,
                iid=row["day"].isoformat(),
                values=(row["label"], row["day"].isoformat(), status, row["note"]),
            )

        self.tags_tree.delete(*self.tags_tree.get_children())
        for tag, count in tags.ranked_tag_counts(tracker.session_notes(view)):
            self.tags_tree.insert("", tk.END, values=(f"#{tag}", count))

        self.heatmap.refresh(view)
        summary = self.month.set_view(view)
        if summary is not None:
            self.month_summary_var.set(
                f"{summary.done}/{summary.possible} days done ({summary.percent}%)"
                + (f"   best run {summary.best_day} days" if summary.best_day else "")
            )

        self._sync_habit_box()

    # -- actions ----------------------------------------------------------

    def _on_habit_selected(self, _event: object = None) -> None:
        chosen = self.habit_var.get()
        if not chosen:
            return
        try:
            self.session.use(chosen)
        except UnknownHabit:
            self._sync_habit_box()
            return
        self.refresh()

    def mark_today(self) -> None:
        self.mark_day(self.session.today())

    def mark_picked_date(self) -> None:
        chosen = picker.pick_date(self.root, initial=self.session.today())
        if chosen is not None:
            self.mark_day(chosen)

    def mark_day(self, day: date) -> None:
        """Prompt for a note and mark ``day``."""
        today = self.session.today()
        if day > today and not messagebox.askyesno(
            "Future date", f"{day.isoformat()} has not happened yet. Mark it anyway?"
        ):
            return
        previous = self.session.note(day)
        note = picker.ask_note(
            self.root,
            initial=previous,
            title="Session note",
            prompt=f"What did you work on {day.isoformat()}?",
        )
        if note is None:
            return
        self.session.mark(day, note.strip())
        self._save()
        if previous:
            self._info("Note replaced", f"Previous note on {day.isoformat()}: {previous}")

    def add_tags_to_selected(self) -> None:
        """Append tags from the Tags tab entry box to the selected day's note."""
        selection = self.tree.selection()
        raw = self.tag_entry.get()
        if not selection:
            self._warn("No day selected", "Select a day in the Week tab first.")
            return
        if not raw.strip():
            return
        day = date.fromisoformat(selection[0])
        note = self.session.note(day)
        for tag in tags.parse_tag_input(raw):
            note = tags.add_tag_to_note(note, tag)
        self.tag_entry.delete(0, tk.END)
        self.session.mark(day, note)
        self._save()

    def clear_selected(self) -> None:
        selection = self.tree.selection()
        if not selection:
            self._warn("No day selected", "Select a day in the Week tab first.")
            return
        day = date.fromisoformat(selection[0])
        if messagebox.askyesno("Confirm", f"Clear the session on {day.isoformat()}?"):
            self.session.clear(day)
            self._save()

    def undo_last(self) -> None:
        restored = self.session.undo()
        if restored is None:
            self._info("Nothing to undo", "There are no recorded changes to roll back.")
            return
        self._save()
        self._info("Undone", f"Restored the previous state ({restored}).")

    def set_goal(self) -> None:
        from tkinter import simpledialog

        raw = simpledialog.askinteger(
            "Weekly goal",
            f"Sessions per week for {self.session.habit_label} (0 turns it off):",
            parent=self.root,
            minvalue=0,
            initialvalue=self.session.goal(),
        )
        if raw is None:
            return
        self.session.set_goal(int(raw))
        self._save()

    def new_habit(self) -> None:
        from tkinter import simpledialog

        name = simpledialog.askstring("New habit", "Name:", parent=self.root)
        if not name or not name.strip():
            return
        try:
            self.session.add_habit(name.strip(), goal=self.session.goal(), activate=True)
        except (ValueError, SessionError) as exc:
            self._error("Could not add habit", str(exc))
            return
        self.refresh()

    def export(self) -> None:
        try:
            written = backup.export_dialog(self.root)
        except backup.BackupError as exc:
            self._error("Export failed", str(exc))
            return
        if written is not None:
            self._info("Exported", f"Data written to {written}")

    def import_data(self) -> None:
        try:
            imported = backup.import_dialog(self.root)
        except backup.BackupError as exc:
            self._error("Import failed", str(exc))
            return
        if imported is not None:
            self.session.document = imported
            self._save()

    # -- helpers ----------------------------------------------------------

    def _save(self) -> None:
        """Persist the session, reporting failures instead of raising."""
        try:
            self.session.save()
        except storage.StorageError as exc:
            self._error("Could not save", str(exc))
            return
        self.refresh()

    def _info(self, title: str, body: str) -> None:
        messagebox.showinfo(title, body, parent=self.root)

    def _warn(self, title: str, body: str) -> None:
        messagebox.showwarning(title, body, parent=self.root)

    def _error(self, title: str, body: str) -> None:
        messagebox.showerror(title, body, parent=self.root)


def _paint_root(root: tk.Misc, palette: Palette) -> None:
    """Apply the palette to the window itself.

    ttk themes do not reach the toplevel background, so a dark window otherwise
    keeps a white frame around the themed content.
    """
    for option, value in (
        ("background", palette.background),
        ("highlightbackground", palette.background),
    ):
        try:
            root.configure(**{option: value})
        except tk.TclError:  # pragma: no cover - not every window manager allows it
            log.debug("Could not set %s on the root window", option, exc_info=True)


def progress_value(done: int, goal: int) -> int:
    """Progress percentage, or 0 when the goal is switched off."""
    if goal <= 0:
        return 0
    return min(max(round(done / goal * 100), 0), 100)


def main(settings: Settings | None = None, theme: str | None = None) -> None:
    """Open the desktop window. Blocks until the window is closed."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        raise SystemExit(f"Tkinter is unavailable on this machine: {exc}") from exc
    HabitTrackerApp(root, settings=settings, theme=theme)
    root.mainloop()


if __name__ == "__main__":
    main()
