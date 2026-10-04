"""Interactive terminal front-end.

Used by ``ht`` with no subcommand, and by ``ht tui``.

Two front-ends share one model:

* :class:`InteractiveApp` is the numbered menu. Standard library only, and the
  fallback whenever Textual is missing or the terminal is unsuitable.
* :class:`TextualApp` is the full-screen interface, built lazily so importing
  this module never requires ``textual``.

Both drive a :class:`habit_tracker.session.Session`, so habit switching, undo
recording, and persistence behave identically in each.
"""

from __future__ import annotations

import contextlib
import logging
import sys
from datetime import date
from typing import ClassVar

from . import calendar, tags, tracker
from .config import APP_TITLE, Settings
from .console import Console
from .dates import DateParseError, accepted_formats, parse_date
from .session import Session, SessionError, UnknownHabit

try:
    import textual  # noqa: F401

    HAS_TEXTUAL = True
except ImportError:
    HAS_TEXTUAL = False

log = logging.getLogger(__name__)

TEXTUAL_HINT = 'pip install "habit-tracker[tui]"'

MENU = f"""
  {APP_TITLE}
  --------------------
  1) Mark a session
  2) Unmark a day
  3) This week
  4) Stats
  5) Tags
  6) Set weekly goal
  7) Switch habit
  8) Undo last change
  9) This month
  0) Quit
"""


def textual_available() -> bool:
    """True when Textual is importable *and* the terminal suits a full screen app."""
    return HAS_TEXTUAL and sys.stdin.isatty() and sys.stdout.isatty()


class InteractiveApp:
    """The numbered menu: no dependencies, always works."""

    def __init__(self, settings: Settings, console: Console, habit: str | None = None) -> None:
        self.settings = settings
        self.console = console
        self.session = Session(settings, habit=habit)

    # -- loop -------------------------------------------------------------

    def today(self) -> date:
        return self.session.today()

    def run(self) -> int:
        while True:
            self.console.clear()
            self.console.line(f"  Habit: {self.session.habit_label}")
            self.console.line(MENU)
            choice = input("  Pick an option: ").strip()
            if choice in ("0", "q", "quit", "exit"):
                self.console.success("Saved. See you tomorrow.")
                return 0
            try:
                self.dispatch(choice)
            except (DateParseError, SessionError, UnknownHabit) as exc:
                self.console.error(str(exc))
            except Exception as exc:  # keep the menu alive on unexpected errors
                log.debug("menu action failed", exc_info=True)
                self.console.error(str(exc))
            self._pause()

    def dispatch(self, choice: str) -> None:
        handlers = {
            "1": self.do_mark,
            "2": self.do_unmark,
            "3": self.show_week,
            "4": self.show_stats,
            "5": self.show_tags,
            "6": self.set_goal,
            "7": self.choose_habit,
            "8": self.do_undo,
            "9": self.show_month,
        }
        handler = handlers.get(choice)
        if handler is None:
            self.console.warn("Unknown option.")
            return
        handler()

    # -- actions ----------------------------------------------------------

    def do_mark(self) -> None:
        day = self._ask_day()
        if day is None:
            return
        note = input("  Note (optional, #tags allowed): ").strip()
        previous = self.session.note(day)
        self.session.mark(day, note)
        self.session.save()
        self.console.success(f"Marked {day.isoformat()}.")
        if previous:
            self.console.line(f"  Replaced previous note: {previous}")
        self.console.line("  Undo with option 8.")

    def do_unmark(self) -> None:
        day = self._ask_day()
        if day is None:
            return
        if input(f"  Clear {day.isoformat()}? (y/N): ").strip().lower() not in ("y", "yes"):
            self.console.warn("Cancelled.")
            return
        cleared = self.session.clear(day)
        self.session.save()
        if cleared:
            self.console.success(f"Cleared {day.isoformat()}.")
            self.console.line("  Undo with option 8.")
        else:
            self.console.line(f"  Nothing was marked on {day.isoformat()}.")

    def do_undo(self) -> None:
        restored = self.session.undo()
        if restored is None:
            self.console.warn("Nothing to undo.")
            return
        self.session.save()
        self.console.success(f"Undone. {restored}.")

    def show_week(self) -> None:
        view = self.session.view
        today = self.today()
        start = tracker.week_start(today)
        done, goal = tracker.week_progress(view, start, today)
        self.console.heading(f"Week of {start.isoformat()} - {self.session.habit_label}")
        for row in tracker.week_rows(view, start, today):
            marker = "." if row["future"] else ("x" if row["done"] else " ")
            note = f"  {row['note']}" if row["note"] else ""
            self.console.line(f"  [{marker}] {row['label']}  {row['day'].isoformat()}{note}")
        self.console.progress(done, goal)
        if goal and done >= goal:
            self.console.success("Goal reached.")

    def show_month(self) -> None:
        anchor = calendar.parse_month(input("  Month (YYYY-MM, blank for now): ") or "x")
        self.render_month(anchor)

    def render_month(self, anchor: date) -> None:
        view = self.session.view
        today = self.today()
        summary = calendar.month_summary(anchor, view, today=today)
        self.console.heading(f"{anchor.strftime('%B %Y')} - {self.session.habit_label}")
        self.console.line("  " + "  ".join(calendar.MONTH_HEADER))
        for week in calendar.month_grid(anchor, view, today=today):
            self.console.line("  " + "  ".join(cell.render() for cell in week))
        self.console.progress(summary.done, summary.possible)
        self.console.line(f"  {summary.done}/{summary.possible} days ({summary.rate:.0%})")

    def show_stats(self) -> None:
        view = self.session.view
        today = self.today()
        done, goal = tracker.week_progress(view, today)
        top, top_count = tracker.busiest_weekday(view)
        self.console.heading(f"Stats - {self.session.habit_label}")
        self.console.detail("Current streak", f"{tracker.current_streak(view, today)} day(s)")
        self.console.detail("Longest streak", f"{tracker.longest_streak(view)} day(s)")
        self.console.detail("Total sessions", tracker.total_sessions(view))
        self.console.detail("Weekly goal", goal or "off")
        self.console.detail("This week", f"{done}/{goal}" if goal else "no goal set")
        self.console.detail("Most active day", f"{top} ({top_count})" if top else "no data yet")
        self.console.detail("All habits", f"{self.session.total_sessions()} session(s)")
        self.console.detail("Undo available", f"{self.session.undo_depth()} step(s)")

    def show_tags(self) -> None:
        ranked = tags.ranked_tag_counts(self.session.sessions())
        self.console.heading(f"Tags - {self.session.habit_label}")
        if not ranked:
            self.console.line("  No tags yet. Add #hashtags to a session note.")
            return
        self.console.table(["Tag", "Count"], [(f"#{tag}", count) for tag, count in ranked])

    def set_goal(self) -> None:
        raw = input(f"  Sessions per week for {self.session.habit_label} (0 = off): ").strip()
        try:
            goal = max(int(raw), 0)
        except ValueError:
            self.console.error("That is not a number.")
            return
        self.session.set_goal(goal)
        self.session.save()
        self.console.success(f"Weekly goal for {self.session.habit_label} set to {goal}.")

    def choose_habit(self) -> None:
        rows = self.session.habits()
        self.console.heading("Habits")
        self.console.table(
            ["", "Name", "Id", "Goal", "Sessions"],
            [
                (
                    "*" if row["active"] else " ",
                    row["name"],
                    row["id"],
                    row["goal"] or "off",
                    row["sessions"],
                )
                for row in rows
            ],
        )
        if len(rows) < 2:
            self.console.line("  Add more with: ht habit add <name>")
        raw = input("  Switch to (blank to cancel, 'new <name>' to create): ").strip()
        if not raw:
            return
        if raw.lower().startswith("new "):
            name = raw[4:].strip()
            if not name:
                self.console.warn("A habit needs a name.")
                return
            self.session.add_habit(name, activate=True)
            self.console.success(f"Now tracking {self.session.habit_label!r}.")
            return
        habit_id = self.session.use_habit(raw)
        self.console.success(f"Now tracking {self.session.habit_label!r} ({habit_id}).")

    # -- helpers ----------------------------------------------------------

    def _ask_day(self) -> date | None:
        raw = input(f"  Which day? ({accepted_formats()}): ")
        if not raw.strip():
            return self.today()
        try:
            return parse_date(raw, today=self.today())
        except DateParseError as exc:
            self.console.error(str(exc))
            return None

    def _pause(self) -> None:
        with contextlib.suppress(EOFError):
            input("\n  Press Enter to continue...")


# --------------------------------------------------------------------------
# Textual
# --------------------------------------------------------------------------


def build_textual_app(settings: Settings, habit: str | None = None):
    """Construct the Textual app class lazily, returning ``None`` if unavailable.

    Kept as a factory rather than a module-level subclass so that a missing or
    broken ``textual`` install degrades to the plain menu instead of raising at
    import time.
    """
    if not HAS_TEXTUAL:
        return None

    from textual.app import App
    from textual.widgets import DataTable, Footer, Header, Static

    class HabitApp(App):
        """Full-screen habit tracker."""

        CSS = """
        Screen { layout: vertical; }
        #summary { padding: 1 2; height: auto; }
        #hint { padding: 0 2; color: $text-muted; }
        DataTable { height: 1fr; }
        """

        BINDINGS: ClassVar[list] = [
            ("m", "mark_today", "Mark today"),
            ("u", "undo", "Undo"),
            ("w", "switch_habit", "Habit"),
            ("r", "reload", "Reload"),
            ("q", "quit", "Quit"),
        ]

        def __init__(self) -> None:
            super().__init__()
            self.session = Session(settings, habit=habit)

        def compose(self):
            yield Header()
            yield Static(id="summary")
            yield Static(id="hint")
            yield DataTable(id="week")
            yield Footer()

        def on_mount(self) -> None:
            table = self.query_one("#week", DataTable)
            table.add_columns("Day", "Date", "Done", "Note")
            self.refresh_data()

        def refresh_data(self) -> None:
            today = self.session.today()
            start = tracker.week_start(today)
            view = self.session.view
            done, goal = tracker.week_progress(view, start, today)

            summary = self.query_one("#summary", Static)
            summary.update(
                f"{self.session.habit_label}   {done}/{goal or '-'} this week   "
                f"streak {tracker.current_streak(view, today)}   "
                f"total {tracker.total_sessions(view)}   "
                f"undo {self.session.undo_depth()}"
            )
            self.query_one("#hint", Static).update(
                "m mark today   u undo   w switch habit   r reload   q quit"
            )

            table = self.query_one("#week", DataTable)
            table.clear()
            for row in tracker.week_rows(view, start, today):
                table.add_row(
                    row["label"],
                    row["day"].isoformat(),
                    "." if row["future"] else ("x" if row["done"] else "-"),
                    row["note"] or "",
                )

        def action_mark_today(self) -> None:
            today = self.session.today()
            # Re-marking keeps any existing note: the shortcut toggles the day,
            # it should not silently destroy prose.
            self.session.mark(today, self.session.note(today))
            self.session.save()
            self.notify(f"Marked {today.isoformat()}.")
            self.refresh_data()

        def action_undo(self) -> None:
            if self.session.undo() is None:
                self.notify("Nothing to undo.", severity="warning")
                return
            self.session.save()
            self.notify("Undone.")
            self.refresh_data()

        def action_switch_habit(self) -> None:
            rows = self.session.habits()
            if len(rows) < 2:
                self.notify("Only one habit. Add one with: ht habit add <name>", severity="warning")
                return
            names = [row["name"] for row in rows]
            try:
                index = names.index(self.session.habit_label)
            except ValueError:
                index = 0
            self.session.use_habit(names[(index + 1) % len(names)])
            self.notify(f"Tracking {self.session.habit_label}.")
            self.refresh_data()

        def action_reload(self) -> None:
            self.session = Session(settings, habit=self.session.habit)
            self.refresh_data()

    return HabitApp


def run(settings: Settings, console: Console, habit: str | None = None) -> int:
    """Entry point for the interactive terminal interface.

    Prefers the full-screen Textual app and falls back to the numbered menu.
    """
    if textual_available():
        app_class = build_textual_app(settings, habit=habit)
        if app_class is not None:
            try:
                app_class().run()
                return 0
            except Exception:
                log.debug("textual app failed; falling back to the menu", exc_info=True)
                console.line(f"  Textual failed to start ({TEXTUAL_HINT} to reinstall).")

    if not HAS_TEXTUAL:
        log.debug("textual not installed; using the plain menu")
    return InteractiveApp(settings, console, habit=habit).run()
