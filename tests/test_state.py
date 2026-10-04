"""Tests for the v2 state document and the v1 migration dispatcher."""

from __future__ import annotations

from datetime import date

import pytest

from habit_tracker import state

TODAY = date(2026, 10, 4)


def v1_doc(goal=5, **sessions):
    return {"schema_version": 1, "goal": goal, "sessions": dict(sessions)}


# --------------------------------------------------------------------------
# Migration
# --------------------------------------------------------------------------


def test_v1_document_becomes_a_single_habit():
    doc = state.migrate(v1_doc(goal=7, **{"2026-10-03": "did a thing"}), TODAY)

    assert doc["schema_version"] == state.SCHEMA_VERSION
    assert doc["habits"][state.DEFAULT_HABIT_ID]["goal"] == 7
    assert doc["sessions"][state.DEFAULT_HABIT_ID] == {"2026-10-03": "did a thing"}
    assert doc["active_habit"] == state.DEFAULT_HABIT_ID
    assert doc["history"] == []


def test_migration_is_idempotent():
    once = state.migrate(v1_doc(**{"2026-10-03": "note"}), TODAY)
    twice = state.migrate(once, TODAY)
    assert twice == once


def test_migration_three_times_is_stable():
    """Backends migrate on every load and save; repetition must not drift."""
    doc = state.migrate(v1_doc(goal=3, **{"2026-10-01": "a"}), TODAY)
    for _ in range(5):
        doc = state.migrate(doc, TODAY)
    assert list(doc["habits"]) == [state.DEFAULT_HABIT_ID]
    assert doc["sessions"][state.DEFAULT_HABIT_ID] == {"2026-10-01": "a"}
    assert doc["habits"][state.DEFAULT_HABIT_ID]["goal"] == 3


def test_document_without_version_is_treated_as_v1():
    doc = state.migrate({"goal": 4, "sessions": {"2026-10-02": "x"}}, TODAY)
    assert doc["schema_version"] == 2
    assert doc["sessions"][state.DEFAULT_HABIT_ID] == {"2026-10-02": "x"}
    assert doc["habits"][state.DEFAULT_HABIT_ID]["goal"] == 4


def test_non_dict_input_becomes_a_fresh_document():
    for value in (None, [], "nope", 42, [1, 2]):
        doc = state.migrate(value, TODAY)
        assert doc["schema_version"] == 2
        assert list(doc["habits"]) == [state.DEFAULT_HABIT_ID]


def test_migration_preserves_future_version_documents():
    """A v3 file should not be downgraded back to v2."""
    doc = state.migrate(
        {
            "schema_version": 3,
            "active_habit": "run",
            "habits": {"run": {"name": "Run", "goal": 4, "created": "2026-01-01"}},
            "sessions": {"run": {"2026-10-01": "miles"}},
            "future_field": True,
        },
        TODAY,
    )
    assert doc["active_habit"] == "run"
    assert doc["future_field"] is True
    assert doc["sessions"]["run"] == {"2026-10-01": "miles"}


def test_migration_does_not_downgrade_the_declared_version():
    """Stamping a v3 file as v2 would let the next save drop unknown fields."""
    doc = state.migrate(
        {
            "schema_version": 3,
            "active_habit": "run",
            "habits": {"run": {"name": "Run", "goal": 4, "created": "2026-01-01"}},
            "sessions": {"run": {}},
            "future_field": True,
        },
        TODAY,
    )
    assert doc["schema_version"] == 3


def test_a_newer_document_survives_a_save_and_reload(tmp_path):
    from habit_tracker import storage

    path = tmp_path / "data.json"
    path.write_text(
        '{"schema_version": 3, "active_habit": "run", '
        '"habits": {"run": {"name": "Run", "goal": 4, "created": "2026-01-01"}}, '
        '"sessions": {"run": {"2026-10-01": "miles"}}, "future_field": true}',
        encoding="utf-8",
    )
    loaded = storage.load_data(path)
    assert loaded["schema_version"] == 3
    assert loaded["future_field"] is True


def test_migration_drops_unparseable_session_dates():
    doc = state.migrate(
        {"schema_version": 1, "goal": 5, "sessions": {"not-a-date": "x", "2026-10-03": "ok"}},
        TODAY,
    )
    assert doc["sessions"][state.DEFAULT_HABIT_ID] == {"2026-10-03": "ok"}


def test_migration_coerces_non_string_notes():
    doc = state.migrate(
        {"schema_version": 1, "goal": 5, "sessions": {"2026-10-03": 42, "2026-10-04": None}},
        TODAY,
    )
    assert doc["sessions"][state.DEFAULT_HABIT_ID] == {"2026-10-03": "", "2026-10-04": ""}


def test_migration_falls_back_when_goal_is_not_numeric():
    doc = state.migrate({"schema_version": 1, "goal": "banana", "sessions": {}}, TODAY)
    assert doc["habits"][state.DEFAULT_HABIT_ID]["goal"] == 5


def test_migration_replaces_missing_habits_with_a_default():
    doc = state.migrate({"schema_version": 2, "habits": {}, "sessions": {}}, TODAY)
    assert list(doc["habits"]) == [state.DEFAULT_HABIT_ID]


def test_migration_repairs_a_dangling_active_habit():
    doc = state.migrate(
        {
            "schema_version": 2,
            "active_habit": "ghost",
            "habits": {"coding": {"name": "Coding", "goal": 5, "created": "2026-01-01"}},
            "sessions": {"coding": {}},
        },
        TODAY,
    )
    assert doc["active_habit"] == "coding"


def test_migration_adds_sessions_key_for_habits_that_lack_them():
    doc = state.migrate(
        {
            "schema_version": 2,
            "active_habit": "run",
            "habits": {"run": {"name": "Run", "goal": 3, "created": "2026-01-01"}},
            "sessions": {},
        },
        TODAY,
    )
    assert doc["sessions"]["run"] == {}


def test_migration_caps_history_depth():
    doc = state.migrate(
        {
            "schema_version": 2,
            "active_habit": "coding",
            "habits": {"coding": {"name": "Coding", "goal": 5, "created": "2026-01-01"}},
            "sessions": {"coding": {}},
            "history": [{"n": i} for i in range(state.MAX_UNDO_DEPTH + 10)],
        },
        TODAY,
    )
    assert len(doc["history"]) == state.MAX_UNDO_DEPTH


# --------------------------------------------------------------------------
# Views
# --------------------------------------------------------------------------


def test_view_is_the_v1_shape_so_analytics_need_no_changes():
    view = state.habit_view(state.migrate(v1_doc(goal=6, **{"2026-10-03": "n"}), TODAY))
    assert set(view) == {"goal", "sessions"}
    assert view == {"goal": 6, "sessions": {"2026-10-03": "n"}}


def test_view_is_a_copy_and_does_not_mutate_the_document():
    doc = state.migrate(v1_doc(**{"2026-10-03": "n"}), TODAY)
    view = state.habit_view(doc)
    view["sessions"]["2026-10-04"] = "sneaky"
    view["goal"] = 99
    assert "2026-10-04" not in doc["sessions"][state.DEFAULT_HABIT_ID]
    assert doc["habits"][state.DEFAULT_HABIT_ID]["goal"] == 5


def test_view_targets_a_named_habit():
    doc = state.new_document(goal=5, today=TODAY)
    read_id = state.add_habit(doc, "Read", goal=7, today=TODAY)
    state.mark(doc, date(2026, 10, 3), "chapter", habit=read_id)

    assert state.habit_view(doc, read_id) == {"goal": 7, "sessions": {"2026-10-03": "chapter"}}
    assert state.habit_view(doc) == {"goal": 5, "sessions": {}}


def test_resolve_accepts_id_name_and_slug():
    doc = state.new_document(today=TODAY)
    state.add_habit(doc, "Morning Run", goal=3, today=TODAY)

    assert state.resolve(doc, "coding") == "coding"
    assert state.resolve(doc, "Coding") == "coding"
    assert state.resolve(doc, "Morning Run") == "morning-run"
    assert state.resolve(doc, "morning-run") == "morning-run"
    assert state.resolve(doc, None) == "coding"


def test_resolve_falls_back_to_active_for_unknown_names():
    doc = state.new_document(today=TODAY)
    state.add_habit(doc, "Read", today=TODAY)
    assert state.resolve(doc, "does-not-exist") == "coding"


def test_has_habit_distinguishes_real_habits_from_fallbacks():
    doc = state.new_document(today=TODAY)
    state.add_habit(doc, "Read", today=TODAY)
    assert state.has_habit(doc, "Read")
    assert state.has_habit(doc, "read")
    assert not state.has_habit(doc, "nope")


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda doc: state.mark(doc, date(2026, 10, 3), "x", habit="tpyo"), id="mark"),
        pytest.param(lambda doc: state.clear(doc, date(2026, 10, 3), habit="tpyo"), id="clear"),
        pytest.param(lambda doc: state.set_goal(doc, 9, habit="tpyo"), id="set_goal"),
        pytest.param(lambda doc: state.rename_habit(doc, "tpyo", "New"), id="rename"),
        pytest.param(lambda doc: state.remove_habit(doc, "tpyo"), id="remove"),
    ],
)
def test_writes_reject_an_unknown_habit_instead_of_falling_back(mutate):
    """A typo must never silently land in the active habit."""
    doc = state.new_document(today=TODAY)
    with pytest.raises(KeyError):
        mutate(doc)
    assert state.sessions_of(doc) == {}


def test_reads_fall_back_rather_than_raising():
    """Leniency on the read side keeps statistics usable with a stale --habit."""
    doc = state.new_document(today=TODAY)
    state.mark(doc, date(2026, 10, 3), "note")
    assert state.resolve(doc, "tpyo") == state.DEFAULT_HABIT_ID
    assert state.habit_view(doc, "tpyo") == {"goal": 5, "sessions": {"2026-10-03": "note"}}
    assert state.note_for(doc, date(2026, 10, 3), habit="tpyo") == "note"


def test_total_sessions_counts_every_habit():
    doc = state.new_document(today=TODAY)
    run = state.add_habit(doc, "Run", today=TODAY)
    state.mark(doc, date(2026, 10, 1), "a")
    state.mark(doc, date(2026, 10, 2), "b")
    state.mark(doc, date(2026, 10, 3), "c", habit=run)
    assert state.total_sessions(doc) == 3


# --------------------------------------------------------------------------
# Marking
# --------------------------------------------------------------------------


def test_mark_records_a_session_and_accepts_dates_or_strings():
    doc = state.new_document(today=TODAY)
    state.mark(doc, date(2026, 10, 3), "from date")
    state.mark(doc, "2026-10-04", "from string")
    assert state.sessions_of(doc) == {"2026-10-03": "from date", "2026-10-04": "from string"}


def test_mark_returns_the_replaced_note():
    doc = state.new_document(today=TODAY)
    assert state.mark(doc, date(2026, 10, 3), "first") is None
    assert state.mark(doc, date(2026, 10, 3), "second") == "first"


def test_mark_does_not_touch_other_habits():
    doc = state.new_document(today=TODAY)
    run = state.add_habit(doc, "Run", today=TODAY)
    state.mark(doc, date(2026, 10, 3), "coding")
    state.mark(doc, date(2026, 10, 3), "running", habit=run)
    assert state.sessions_of(doc) == {"2026-10-03": "coding"}
    assert state.sessions_of(doc, run) == {"2026-10-03": "running"}


def test_mark_rejects_an_unknown_habit():
    doc = state.new_document(today=TODAY)
    with pytest.raises(KeyError):
        state.mark(doc, date(2026, 10, 3), "", habit="nope")


def test_mark_normalises_a_date_object_from_a_subclass():
    doc = state.new_document(today=TODAY)
    state.mark(doc, date(2026, 10, 3), "x")
    assert "2026-10-03" in state.sessions_of(doc)


def test_clear_reports_whether_anything_was_removed():
    doc = state.new_document(today=TODAY)
    state.mark(doc, date(2026, 10, 3), "x")
    assert state.clear(doc, date(2026, 10, 3)) is True
    assert state.clear(doc, date(2026, 10, 3)) is False
    assert state.clear(doc, date(2026, 10, 9)) is False


def test_clear_works_for_an_empty_note():
    """An empty-string note is still a real session, not an absent one."""
    doc = state.new_document(today=TODAY)
    state.mark(doc, date(2026, 10, 3), "")
    assert state.clear(doc, date(2026, 10, 3)) is True


def test_note_for_reads_a_single_day():
    doc = state.new_document(today=TODAY)
    state.mark(doc, date(2026, 10, 3), "hello")
    assert state.note_for(doc, date(2026, 10, 3)) == "hello"
    assert state.note_for(doc, date(2026, 10, 4)) == ""


# --------------------------------------------------------------------------
# Habits
# --------------------------------------------------------------------------


def test_add_habit_slugifies_and_defaults_goal():
    doc = state.new_document(today=TODAY)
    habit_id = state.add_habit(doc, "Morning Run!", today=TODAY)
    assert habit_id == "morning-run"
    assert doc["habits"]["morning-run"]["goal"] == 5
    assert doc["habits"]["morning-run"]["name"] == "Morning Run!"


def test_add_habit_rejects_a_duplicate_name():
    """Two habits sharing a name would make ``--habit <name>`` ambiguous."""
    doc = state.new_document(today=TODAY)
    state.add_habit(doc, "Read", today=TODAY)
    with pytest.raises(ValueError, match="already exists"):
        state.add_habit(doc, "Read", today=TODAY)
    with pytest.raises(ValueError, match="already exists"):
        state.add_habit(doc, "  read ", today=TODAY)


def test_add_habit_deduplicates_colliding_slugs():
    """Distinct names that slugify the same still need distinct ids."""
    doc = state.new_document(today=TODAY)
    assert state.add_habit(doc, "Read Books", today=TODAY) == "read-books"
    assert state.add_habit(doc, "read_books!", today=TODAY) == "read-books-2"


def test_rename_habit_keeps_its_own_name():
    doc = state.new_document(today=TODAY)
    state.add_habit(doc, "Read", today=TODAY)
    assert state.rename_habit(doc, "read", "Read") == "read"
    assert state.habit_name(doc, "read") == "Read"


def test_rename_habit_rejects_another_habits_name():
    doc = state.new_document(today=TODAY)
    state.add_habit(doc, "Read", today=TODAY)
    with pytest.raises(ValueError, match="already exists"):
        state.rename_habit(doc, "coding", "read")


def test_add_habit_can_activate():
    doc = state.new_document(today=TODAY)
    habit_id = state.add_habit(doc, "Read", today=TODAY, activate=True)
    assert doc["active_habit"] == habit_id


def test_add_habit_rejects_a_blank_name():
    doc = state.new_document(today=TODAY)
    with pytest.raises(ValueError):
        state.add_habit(doc, "   ", today=TODAY)


def test_add_habit_falls_back_when_the_name_has_no_word_characters():
    doc = state.new_document(today=TODAY)
    assert state.add_habit(doc, "!!!", today=TODAY) == "habit"


def test_rename_keeps_the_identifier_and_sessions():
    doc = state.new_document(today=TODAY)
    state.mark(doc, date(2026, 10, 3), "note")
    state.rename_habit(doc, "coding", "Deep Work")
    assert doc["habits"]["coding"]["name"] == "Deep Work"
    assert state.sessions_of(doc) == {"2026-10-03": "note"}


def test_set_goal_clamps_negatives():
    doc = state.new_document(today=TODAY)
    assert state.set_goal(doc, -3) == 0
    assert state.set_goal(doc, 4) == 4


def test_set_active_switches_and_persists():
    doc = state.new_document(today=TODAY)
    read = state.add_habit(doc, "Read", today=TODAY)
    assert state.set_active(doc, "Read") == read
    assert doc["active_habit"] == read


def test_set_active_with_none_keeps_the_current_habit():
    doc = state.new_document(today=TODAY)
    read = state.add_habit(doc, "Read", today=TODAY, activate=True)
    assert state.set_active(doc, None) == read


def test_set_active_rejects_an_unknown_habit():
    doc = state.new_document(today=TODAY)
    with pytest.raises(KeyError):
        state.set_active(doc, "nope")


def test_remove_habit_deletes_sessions_and_rehomes_active():
    doc = state.new_document(today=TODAY)
    read = state.add_habit(doc, "Read", today=TODAY)
    state.mark(doc, date(2026, 10, 3), "n", habit=read)
    state.set_active(doc, "Read")

    assert state.remove_habit(doc, "Read") == read
    assert "read" not in doc["habits"]
    assert "read" not in doc["sessions"]
    assert doc["active_habit"] == state.DEFAULT_HABIT_ID


def test_remove_habit_refuses_to_delete_the_last_one():
    doc = state.new_document(today=TODAY)
    with pytest.raises(ValueError):
        state.remove_habit(doc, "coding")


def test_summarise_reports_every_habit_with_an_active_flag():
    doc = state.new_document(goal=5, today=TODAY)
    state.mark(doc, date(2026, 10, 1), "a")
    state.mark(doc, date(2026, 10, 2), "b")
    read = state.add_habit(doc, "Read", goal=7, today=TODAY)

    rows = {row["id"]: row for row in state.summarise(doc)}
    assert rows["coding"]["sessions"] == 2
    assert rows["coding"]["goal"] == 5
    assert rows["coding"]["active"] is True
    assert rows[read]["sessions"] == 0
    assert rows[read]["goal"] == 7
    assert rows[read]["active"] is False


# --------------------------------------------------------------------------
# Undo
# --------------------------------------------------------------------------


def test_undo_restores_the_previous_state():
    doc = state.new_document(today=TODAY)
    state.push_history(doc)
    state.mark(doc, date(2026, 10, 3), "oops")
    assert state.sessions_of(doc) == {"2026-10-03": "oops"}

    assert state.undo(doc) is not None
    assert state.sessions_of(doc) == {}


def test_undo_walks_backwards_rather_than_toggling():
    doc = state.new_document(today=TODAY)
    state.mark(doc, date(2026, 10, 1), "first")
    state.push_history(doc)
    state.mark(doc, date(2026, 10, 2), "second")
    state.push_history(doc)
    state.mark(doc, date(2026, 10, 3), "third")

    state.undo(doc)
    assert sorted(state.sessions_of(doc)) == ["2026-10-01", "2026-10-02"]
    state.undo(doc)
    assert sorted(state.sessions_of(doc)) == ["2026-10-01"]
    assert state.undo(doc) is None


def test_undo_returns_none_with_empty_history():
    doc = state.new_document(today=TODAY)
    assert state.undo(doc) is None


def test_undo_depth_tracks_available_steps():
    doc = state.new_document(today=TODAY)
    assert state.undo_depth(doc) == 0
    state.push_history(doc)
    assert state.undo_depth(doc) == 1
    state.undo(doc)
    assert state.undo_depth(doc) == 0


def test_undo_restores_a_deleted_habit():
    doc = state.new_document(today=TODAY)
    state.add_habit(doc, "Read", today=TODAY)
    state.push_history(doc)
    state.remove_habit(doc, "Read")
    assert "read" not in doc["habits"]

    state.undo(doc)
    assert "read" in doc["habits"]


def test_undo_restores_a_goal_change():
    doc = state.new_document(goal=5, today=TODAY)
    state.push_history(doc)
    state.set_goal(doc, 7)
    assert state.goal_of(doc) == 7

    state.undo(doc)
    assert state.goal_of(doc) == 5


def test_history_is_capped():
    doc = state.new_document(today=TODAY)
    for _ in range(state.MAX_UNDO_DEPTH + 25):
        state.push_history(doc)
    assert state.undo_depth(doc) == state.MAX_UNDO_DEPTH


def test_snapshots_do_not_capture_history_itself():
    """Otherwise each entry would embed every earlier entry."""
    doc = state.new_document(today=TODAY)
    state.push_history(doc)
    state.push_history(doc)
    assert "history" not in doc["history"][0]
    assert "history" not in doc["history"][1]


def test_undo_survives_a_non_dict_history_entry():
    doc = state.new_document(today=TODAY)
    doc["history"] = ["garbage", None]
    assert state.undo(doc) is None
