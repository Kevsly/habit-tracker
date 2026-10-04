"""Tests for the desktop widgets.

Tkinter needs a display, so everything here is gated: the suite still passes on a
headless machine, it just reports these as skipped. CI installs ``xvfb`` so the
GUI is actually exercised on Linux.
"""

from __future__ import annotations

import tkinter as tk
from datetime import date, timedelta
from tkinter import ttk

import pytest

from habit_tracker import calendar as month_calendar
from habit_tracker import gui, monthgrid, theme
from habit_tracker.session import open_session

TODAY = date(2026, 3, 15)


@pytest.fixture(scope="module")
def root():
    """A hidden Tk root, or a skip when there is no display."""
    try:
        window = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - depends on the machine
        pytest.skip(f"no display available: {exc}")
    window.withdraw()
    yield window
    window.destroy()


def view(**sessions: str) -> dict:
    return {"goal": 5, "sessions": dict(sessions)}


def _children(widget) -> list:
    """Every child widget, across the dict-or-tuple return of ``grid_slaves``."""
    slaves = widget.grid_slaves()
    return list(slaves.values()) if isinstance(slaves, dict) else list(slaves)


@pytest.fixture
def no_dialogs(monkeypatch):
    """Stop modal dialogs from blocking the test run.

    Every one of these would otherwise wait for a human, which hangs CI.
    """
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda *a, **k: None)
    monkeypatch.setattr(gui.messagebox, "showwarning", lambda *a, **k: None)
    monkeypatch.setattr(gui.messagebox, "showerror", lambda *a, **k: None)
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: False)
    monkeypatch.setattr(gui.picker, "ask_note", lambda *a, **k: "did some work")
    monkeypatch.setattr(gui.picker, "pick_date", lambda *a, **k: None)
    monkeypatch.setattr("tkinter.simpledialog.askinteger", lambda *a, **k: 9)
    monkeypatch.setattr("tkinter.simpledialog.askstring", lambda *a, **k: "Reading")


class TestMonthGrid:
    def build(self, root, sessions=None, on_select=None):
        return monthgrid.MonthGrid(
            root,
            view(**(sessions or {})),
            on_select=on_select,
            today=TODAY,
        )

    def test_one_button_per_real_day(self, root):
        grid = self.build(root)
        assert len(grid._buttons) == 31

    def test_padding_days_are_not_clickable(self, root):
        grid = self.build(root)
        # March 2026 starts on a Sunday, so those cells are labels, not buttons.
        assert date(2026, 3, 1) in grid._buttons
        assert len(grid._buttons) == 31

    def test_titles_the_month(self, root):
        grid = self.build(root)
        grid.update_idletasks()
        assert grid.title_var.get() == "March 2026"

    def test_marks_completed_days(self, root):
        grid = self.build(root, {"2026-03-04": "shipped"})
        assert date(2026, 3, 4) in grid._buttons
        assert date(2026, 3, 5) in grid._buttons

    def test_the_summary_matches_the_calendar_module(self, root):
        grid = self.build(root, {"2026-03-04": ""})
        assert grid.summary == month_calendar.month_summary(
            date(2026, 3, 1), view(**{"2026-03-04": ""}), today=TODAY
        )

    def test_clicking_a_day_calls_back(self, root):
        picked: list[date] = []
        grid = self.build(root, on_select=picked.append)
        grid._buttons[date(2026, 3, 7)].invoke()
        assert picked == [date(2026, 3, 7)]

    def test_clicking_without_a_callback_is_harmless(self, root):
        grid = self.build(root, on_select=None)
        grid._buttons[date(2026, 3, 7)].invoke()

    def test_next_month_moves_forward_and_retitles(self, root):
        grid = self.build(root)
        grid.next_month()
        grid.update_idletasks()
        assert grid.anchor == date(2026, 4, 1)
        assert grid.title_var.get() == "April 2026"
        assert len(grid._buttons) == 30

    def test_previous_month_moves_back(self, root):
        grid = self.build(root)
        grid.previous_month()
        grid.update_idletasks()
        assert grid.anchor == date(2026, 2, 1)
        assert len(grid._buttons) == 28

    def test_navigation_wraps_across_a_year_boundary(self, root):
        grid = self.build(root)
        for _ in range(10):
            grid.previous_month()
        assert grid.anchor == date(2025, 5, 1)
        for _ in range(20):
            grid.next_month()
        assert grid.anchor == date(2027, 1, 1)

    def test_day_cells_line_up_under_the_weekday_headers(self, root):
        """Headers and day buttons must share one grid to stay aligned."""
        grid = self.build(root)
        grid.update_idletasks()
        header_columns = {
            label.grid_info()["column"]
            for label in _children(grid.body)
            if isinstance(label, ttk.Label) and label.grid_info()["row"] == 0
        }
        assert header_columns == set(range(7))
        for day, button in grid._buttons.items():
            assert button.grid_info()["column"] == day.weekday()

    def test_set_view_switches_habits(self, root):
        grid = self.build(root)
        grid.set_view(view(**{"2026-03-20": "x"}))
        assert date(2026, 3, 20) in grid._buttons

    def test_each_cell_status_gets_its_own_colour(self, root):
        """Regression: a named ttk style needs an explicit layout.

        Configuring a style is not enough to make it usable. Without the layout
        every ``style=...`` assignment raised "Layout not found", was swallowed,
        and all the day cells rendered identically.
        """
        grid = self.build(root, sessions={"2026-03-10": "x"})
        style = ttk.Style()
        colours = {
            style.lookup(button.cget("style"), "background") for button in grid._buttons.values()
        }
        assert len(colours) >= 3, f"expected distinct done/today/missed colours, got {colours}"

    def test_set_palette_repaints_the_cells(self, root):
        grid = self.build(root, sessions={"2026-03-10": "x"})
        style = ttk.Style()
        done = date(2026, 3, 10)

        grid.set_palette(theme.DARK)
        assert style.lookup(grid._buttons[done].cget("style"), "background") == theme.DARK.success

        grid.set_palette(theme.LIGHT)
        assert style.lookup(grid._buttons[done].cget("style"), "background") == theme.LIGHT.success

    def test_the_default_palette_is_used_when_none_is_given(self, root):
        grid = monthgrid.MonthGrid(root, view(), today=TODAY)
        assert grid.palette in (theme.LIGHT, theme.DARK)

    def test_set_view_returns_the_new_summary(self, root):
        grid = self.build(root)
        summary = grid.set_view(view(**{"2026-03-01": ""}))
        assert summary.done == 1

    def test_refresh_does_not_leak_widgets(self, root):
        """Redrawing must replace the cells, not accumulate them."""
        grid = self.build(root)
        grid.update_idletasks()
        baseline = len(_children(grid.body))
        for _ in range(5):
            grid.refresh()
        grid.update_idletasks()
        assert len(grid._buttons) == 31
        assert len(_children(grid.body)) == baseline


class TestProgressValue:
    @pytest.mark.parametrize(
        "done,goal,expected",
        [(0, 5, 0), (1, 5, 20), (5, 5, 100), (3, 0, 0), (0, 0, 0)],
    )
    def test_percentages(self, done, goal, expected):
        assert gui.progress_value(done, goal) == expected

    def test_never_exceeds_one_hundred(self):
        assert gui.progress_value(9, 5) == 100

    def test_is_never_negative(self):
        assert gui.progress_value(-1, 5) == 0


class TestAppShell:
    @pytest.fixture(autouse=True)
    def _quiet(self, no_dialogs):
        return no_dialogs

    @pytest.fixture
    def app(self, root, tmp_path):
        session = open_session(data_dir=tmp_path)
        instance = gui.HabitTrackerApp(root, session=session)
        yield instance
        for child in root.winfo_children():
            child.destroy()

    def test_builds_without_error(self, app):
        assert app.session is not None

    def test_it_repaints_everything_when_the_theme_changes(self, app):
        """A theme switch must reach the widgets that set colours themselves."""
        before = {day: button.cget("style") for day, button in app.month._buttons.items()}
        app.set_theme("dark")
        assert app.palette is theme.DARK
        assert app.month.palette is theme.DARK
        assert app.heatmap.palette is theme.DARK
        assert set(app.month._buttons) == set(before)
        assert {day: b.cget("style") for day, b in app.month._buttons.items()} == before
        assert app.heatmap.cells, "the heatmap lost its cells on a theme change"

    def test_the_day_cells_use_the_palette_colours(self, app):
        today = app.session.today()
        done = today.replace(day=today.day - 1) if today.day > 1 else today
        missed = today.replace(day=today.day - 2) if today.day > 2 else today

        app.session.mark(done, "did work")
        app.refresh()
        app.set_theme("dark")
        palette = theme.DARK
        style = ttk.Style()

        def background(day: date) -> str:
            name = app.month._buttons[day].cget("style")
            return style.lookup(name, "background")

        assert background(done) == palette.success
        assert background(today) == palette.accent
        if missed != done:
            assert background(missed) == palette.missed

    def test_the_cell_colours_follow_the_light_palette_too(self, app):
        app.set_theme("light")
        style = ttk.Style()
        name = app.month._buttons[app.session.today()].cget("style")
        assert style.lookup(name, "background") == theme.LIGHT.accent

    def test_cycling_the_theme_visits_every_mode(self, app):
        seen = []
        for _ in range(len(gui.THEME_ORDER)):
            seen.append(app.theme_mode)
            app.cycle_theme()
        assert seen == list(gui.THEME_ORDER)
        assert app.theme_mode == gui.THEME_ORDER[0]

    def test_the_root_window_is_painted(self, app):
        app.set_theme("dark")
        assert app.root.cget("background") == theme.DARK.background

    def test_starts_on_the_week_tab(self, app):
        assert app.notebook.index(app.notebook.select()) == 0

    def test_mark_today_persists(self, app):
        app.mark_today()
        assert app.session.sessions()

    def test_mark_today_saves_to_disk(self, app):
        app.mark_today()
        reopened = open_session(data_dir=app.settings.data_dir)
        assert reopened.sessions()

    def test_undo_rolls_the_mark_back(self, app):
        app.mark_today()
        app.undo_last()
        assert app.session.sessions() == {}

    def test_setting_the_goal_updates_the_session(self, app):
        app.set_goal()
        assert app.session.goal() == 9

    def test_mark_day_writes_a_specific_day(self, app):
        app.mark_day(date(2026, 3, 4))
        assert "2026-03-04" in app.session.sessions()

    def test_mark_day_stores_the_note(self, app):
        app.mark_day(date(2026, 3, 4))
        assert app.session.note("2026-03-04") == "did some work"

    def test_a_cancelled_note_dialog_marks_nothing(self, app, monkeypatch):
        monkeypatch.setattr(gui.picker, "ask_note", lambda *a, **k: None)
        app.mark_day(date(2026, 3, 4))
        assert app.session.sessions() == {}

    def test_a_declined_future_date_marks_nothing(self, app, monkeypatch):
        monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: False)
        future = app.session.today() + timedelta(days=1)
        app.mark_day(future)
        assert future.isoformat() not in app.session.sessions()

    def test_an_accepted_future_date_is_marked(self, app, monkeypatch):
        monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: True)
        future = app.session.today() + timedelta(days=1)
        app.mark_day(future)
        assert future.isoformat() in app.session.sessions()

    def test_clear_selected_needs_a_selected_day(self, app):
        app.mark_day(date(2026, 3, 4))
        app.clear_selected()
        assert app.session.sessions()  # nothing selected, so nothing cleared

    def test_clear_selected_removes_a_confirmed_day(self, app, monkeypatch):
        today = app.session.today()
        app.mark_day(today)
        monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: True)
        app.tree.selection_set(today.isoformat())
        app.clear_selected()
        assert today.isoformat() not in app.session.sessions()

    def test_a_declined_clear_keeps_the_day(self, app, monkeypatch):
        today = app.session.today()
        app.mark_day(today)
        monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: False)
        app.tree.selection_set(today.isoformat())
        app.clear_selected()
        assert today.isoformat() in app.session.sessions()

    def test_a_new_habit_can_be_created_through_the_dialog(self, app):
        app.new_habit()
        assert "reading" in [row["id"] for row in app.session.habits()]

    def test_a_duplicate_habit_is_reported_not_raised(self, app, monkeypatch):
        monkeypatch.setattr("tkinter.simpledialog.askstring", lambda *a, **k: "Reading")
        app.new_habit()
        monkeypatch.setattr("tkinter.simpledialog.askstring", lambda *a, **k: "Reading")
        app.new_habit()
        assert len(app.session.habits()) == 2

    def test_export_reports_the_written_path(self, app, tmp_path, monkeypatch):
        destination = tmp_path / "out.json"
        monkeypatch.setattr(gui.backup, "export_dialog", lambda *a, **k: destination)
        app.export()  # must not raise

    def test_import_replaces_the_document(self, app, monkeypatch):
        app.mark_today()
        replacement = {"schema_version": 2, "active_habit": "coding", "habits": {}, "sessions": {}}
        monkeypatch.setattr(gui.backup, "import_dialog", lambda *a, **k: replacement)
        app.import_data()
        assert app.session.sessions() == {}

    def test_a_failed_export_is_reported_not_raised(self, app, monkeypatch):
        def boom(*args, **kwargs):
            raise gui.backup.BackupError("disk full")

        monkeypatch.setattr(gui.backup, "export_dialog", boom)
        app.export()  # must not raise
