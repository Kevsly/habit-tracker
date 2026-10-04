"""Tests for the shared :class:`habit_tracker.session.Session` layer.

The point of ``Session`` is that CLI, Textual and Tkinter share one set of
rules, so these tests exercise the rules rather than any single front-end.
"""

from __future__ import annotations

import pytest

from habit_tracker import config, state, storage
from habit_tracker.session import Session, UnknownHabit, open_session


@pytest.fixture
def data_dir(tmp_path):
    return tmp_path


@pytest.fixture
def session(data_dir):
    return open_session(data_dir=data_dir)


class TestIdentity:
    def test_defaults_to_the_only_habit(self, session):
        assert session.habit == "coding"
        assert session.habit_label == "Coding"

    def test_an_unknown_habit_is_refused_not_ignored(self, session):
        """A typo must never silently write into the active habit."""
        with pytest.raises(UnknownHabit, match="Unknown habit"):
            session.use("cdoign")

    def test_use_accepts_a_habit_id_or_its_name(self, session):
        session.add_habit("Reading", goal=7)
        assert session.use("reading") == "reading"
        assert session.use("Reading") == "reading"

    def test_use_does_not_guess_from_a_partial_name(self, session):
        """Partial names are ambiguous, so they must fail rather than match."""
        session.add_habit("Reading", goal=7)
        with pytest.raises(UnknownHabit):
            session.use("read")

    def test_use_none_falls_back_to_the_active_habit(self, session):
        session.add_habit("Reading", goal=7)
        session.use("reading")
        assert session.use(None) == "coding"

    def test_use_is_case_insensitive_for_names(self, session):
        session.add_habit("Reading")
        assert session.use("READING") == "reading"

    def test_the_error_lists_the_known_habits(self, session):
        session.add_habit("Reading")
        with pytest.raises(UnknownHabit) as excinfo:
            session.use("swimming")
        assert "coding" in str(excinfo.value)
        assert "reading" in str(excinfo.value)

    def test_the_requested_habit_survives_a_reload(self, session, data_dir):
        session.add_habit("Reading", goal=7)
        session.save()
        reopened = Session(session.settings)
        assert reopened.use("reading") == "reading"
        assert reopened.sessions() == {}


class TestReads:
    def test_view_is_the_v1_shape_the_analytics_layer_expects(self, session):
        session.mark("2026-03-01", "hello")
        view = session.view
        assert set(view) == {"goal", "sessions"}
        assert view["sessions"] == {"2026-03-01": "hello"}

    def test_view_is_a_copy_so_callers_cannot_corrupt_the_document(self, session):
        session.view["sessions"]["2026-03-01"] = "injected"
        assert session.sessions() == {}

    def test_goal_and_notes_follow_the_targeted_habit(self, session):
        session.add_habit("Reading", goal=7)
        session.use("reading")
        assert session.goal() == 7
        session.mark("2026-03-01", "chapter one")
        assert session.sessions() == {"2026-03-01": "chapter one"}

        session.use("coding")
        assert session.sessions() == {}

    def test_habits_are_summarised(self, session):
        session.add_habit("Reading", goal=7)
        rows = {row["id"]: row for row in session.habits()}
        assert rows["coding"]["name"] == "Coding"
        assert rows["reading"]["goal"] == 7
        assert rows["coding"]["active"] is True

    def test_total_sessions_counts_every_habit(self, session):
        session.mark("2026-03-01")
        session.add_habit("Reading", goal=7)
        session.use("reading")
        session.mark("2026-03-02")
        assert session.total_sessions() == 2

    def test_notes_list_is_a_list_of_note_strings(self, session):
        session.mark("2026-03-01", "#python")
        session.mark("2026-03-02", "#rust")
        assert sorted(session.notes_list()) == ["#python", "#rust"]

    def test_notes_all_spans_every_habit(self, session):
        session.mark("2026-03-01", "#python")
        session.add_habit("Reading", goal=7)
        session.use("reading")
        session.mark("2026-03-02", "#rust")
        assert sorted(session.notes_all()) == ["#python", "#rust"]

    def test_note_returns_the_text_for_one_day(self, session):
        session.mark("2026-03-01", "hello")
        assert session.note("2026-03-01") == "hello"
        assert session.note(date_like("2026-03-02")) == ""

    def test_today_uses_the_configured_timezone(self, data_dir):
        settings = config.resolve_settings(data_dir, None, "UTC")
        assert open_session(data_dir=data_dir).today() == config.today("UTC")
        assert Session(settings).today() == config.today("UTC")


def date_like(value: str):
    from datetime import date

    return date.fromisoformat(value)


class TestWrites:
    def test_mark_returns_the_note_it_replaced(self, session):
        session.mark("2026-03-01", "first")
        assert session.mark("2026-03-01", "second") == "first"
        assert session.note("2026-03-01") == "second"

    def test_mark_returns_none_for_a_new_day(self, session):
        assert session.mark("2026-03-01", "first") is None

    def test_writes_do_not_persist_until_save(self, session, data_dir):
        session.mark("2026-03-01")
        session.save()
        assert storage.load_data(config.resolve_settings(data_dir).data_file)["sessions"]["coding"]


class TestHistory:
    def test_every_mutation_pushes_one_undo_step(self, session):
        assert session.undo_depth() == 0
        session.mark("2026-03-01")
        assert session.undo_depth() == 1
        session.set_goal(9)
        assert session.undo_depth() == 2

    def test_undo_returns_the_previous_state(self, session):
        session.mark("2026-03-01", "hello")
        session.undo()
        assert session.sessions() == {}

    def test_undo_with_nothing_to_roll_back(self, session):
        assert session.undo() is None

    def test_habit_changes_are_undoable(self, session):
        session.add_habit("Reading", goal=7)
        session.undo()
        assert state.habit_ids(session.document) == ["coding"]

    def test_undo_does_not_itself_push_history(self, session):
        session.mark("2026-03-01")
        session.undo()
        depth = session.undo_depth()
        session.undo()
        assert session.undo_depth() == depth


class TestHabitManagement:
    def test_add_habit_persists_immediately(self, session, data_dir):
        session.add_habit("Reading", goal=7)
        reopened = Session(session.settings)
        assert state.habit_name(reopened.document, "reading") == "Reading"
        assert state.goal_of(reopened.document, "reading") == 7

    def test_add_habit_can_activate(self, session):
        session.add_habit("Reading", goal=7, activate=True)
        assert session.habit == "reading"

    def test_duplicate_names_are_rejected(self, session):
        session.add_habit("Reading")
        with pytest.raises(ValueError, match="already exists"):
            session.add_habit("Reading")

    def test_rename_keeps_sessions(self, session):
        session.mark("2026-03-01", "kept")
        session.rename_habit("Deep work")
        assert state.habit_name(session.document, "coding") == "Deep work"
        assert session.note("2026-03-01") == "kept"

    def test_use_habit_persists_the_new_default(self, session):
        session.add_habit("Reading", goal=7)
        session.use_habit("reading")
        assert Session(session.settings).habit == "reading"

    def test_remove_habit_drops_its_sessions(self, session):
        session.add_habit("Reading", goal=7)
        session.use("reading")
        session.mark("2026-03-01", "bye")
        session.remove_habit()
        assert state.has_habit(session.document, "reading") is False
        assert session.total_sessions() == 0

    def test_removing_a_habit_you_are_targeting_resets_the_target(self, session):
        session.add_habit("Reading", goal=7)
        session.use("reading")
        session.remove_habit("reading")
        assert session.habit == "coding"

    def test_the_last_habit_cannot_be_removed(self, session):
        with pytest.raises(ValueError, match="only habit"):
            session.remove_habit("coding")


class TestBackends:
    def test_sqlite_round_trips_the_same_way_json_does(self, data_dir):
        for backend in ("json", "sqlite"):
            session = open_session(data_dir=data_dir, backend=backend)
            session.add_habit("Reading", goal=7)
            session.use("reading")
            session.mark("2026-03-01", "hello")
            session.save()

            reopened = Session(session.settings, habit="reading")
            assert state.habit_name(reopened.document, "reading") == "Reading", backend
            assert state.goal_of(reopened.document, "reading") == 7, backend
            assert reopened.sessions() == {"2026-03-01": "hello"}, backend

    def test_each_backend_uses_its_own_file(self, data_dir):
        assert open_session(data_dir=data_dir, backend="json").settings.data_file.suffix == ".json"
        sqlite = open_session(data_dir=data_dir, backend="sqlite").settings.data_file
        assert sqlite.suffix == ".sqlite3"

    def test_unknown_habits_fail_on_every_backend(self, data_dir):
        for backend in ("json", "sqlite"):
            session = open_session(data_dir=data_dir, backend=backend)
            with pytest.raises(UnknownHabit):
                session.use("nope")
