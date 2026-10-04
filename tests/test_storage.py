from __future__ import annotations

import json
import sqlite3
from datetime import date

import pytest

from habit_tracker import state, storage
from habit_tracker.storage import SCHEMA_VERSION, StorageError

TODAY = date(2026, 3, 15)


def make_data(goal: int = 3, **sessions: str) -> dict:
    """A v2 document with a single habit."""
    doc = state.new_document(goal=goal, today=TODAY)
    for day, note in sessions.items():
        state.mark(doc, day, note)
    return doc


def make_multi_data() -> dict:
    """A v2 document with three habits and undo history."""
    doc = state.new_document(goal=3, today=TODAY)
    state.mark(doc, "2026-03-01", "coding")
    run = state.add_habit(doc, "Morning Run", goal=4, today=TODAY)
    state.mark(doc, "2026-03-02", "miles", habit=run)
    read = state.add_habit(doc, "Read", goal=0, today=TODAY)
    state.set_active(doc, read)
    state.push_history(doc)
    state.mark(doc, "2026-03-03", "a chapter")
    return doc


@pytest.fixture
def data() -> dict:
    return make_data(goal=3, **{"2026-03-01": "one", "2026-03-02": ""})


@pytest.fixture
def multi() -> dict:
    return make_multi_data()


class TestRoundTrip:
    def test_json_round_trip(self, tmp_path, data):
        backend = storage.JsonBackend(tmp_path / "data.json")
        backend.save(data)
        assert backend.load() == data

    def test_sqlite_round_trip(self, tmp_path, data):
        backend = storage.SqliteBackend(tmp_path / "data.sqlite3")
        backend.save(data)
        assert backend.load() == data

    def test_json_round_trip_with_multiple_habits(self, tmp_path, multi):
        backend = storage.JsonBackend(tmp_path / "data.json")
        backend.save(multi)
        assert backend.load() == multi

    def test_sqlite_round_trip_with_multiple_habits(self, tmp_path, multi):
        backend = storage.SqliteBackend(tmp_path / "data.sqlite3")
        backend.save(multi)
        assert backend.load() == multi

    def test_undo_history_survives_both_backends(self, tmp_path):
        doc = make_data(goal=5, **{"2026-03-01": "one"})
        for kind in ("json", "sqlite"):
            backend = storage.get_backend(kind, tmp_path / f"h.{kind}")
            backend.save(doc)
            loaded = backend.load()
            assert len(loaded["history"]) == len(doc["history"]), kind

    def test_schema_version_is_stamped(self, tmp_path, data):
        backend = storage.JsonBackend(tmp_path / "data.json")
        backend.save(data)
        assert backend.load()["schema_version"] == SCHEMA_VERSION

    def test_saving_creates_missing_directories(self, tmp_path, data):
        backend = storage.JsonBackend(tmp_path / "nested" / "deeper" / "data.json")
        backend.save(data)
        assert backend.load() == data

    def test_overwrite_replaces_previous_content(self, tmp_path):
        backend = storage.JsonBackend(tmp_path / "data.json")
        backend.save(make_data(goal=5, **{"2026-03-01": "first"}))
        backend.save(make_data(goal=1))
        loaded = backend.load()
        assert state.goal_of(loaded) == 1
        assert state.sessions_of(loaded) == {}

    def test_deleting_a_habit_survives_a_save(self, tmp_path, multi):
        backend = storage.JsonBackend(tmp_path / "data.json")
        backend.save(multi)
        reloaded = backend.load()
        state.remove_habit(reloaded, "read")
        backend.save(reloaded)
        assert "read" not in backend.load()["habits"]


class TestEmptyStore:
    def test_json_missing_file_gives_defaults(self, tmp_path):
        loaded = storage.JsonBackend(tmp_path / "absent.json").load()
        assert loaded["schema_version"] == SCHEMA_VERSION
        assert list(loaded["habits"]) == [state.DEFAULT_HABIT_ID]
        assert state.goal_of(loaded) == 5
        assert state.sessions_of(loaded) == {}

    def test_sqlite_missing_file_gives_defaults(self, tmp_path):
        loaded = storage.SqliteBackend(tmp_path / "absent.sqlite3").load()
        assert list(loaded["habits"]) == [state.DEFAULT_HABIT_ID]
        assert state.goal_of(loaded) == 5
        assert state.sessions_of(loaded) == {}

    def test_default_data_shape(self):
        default = storage.default_data()
        assert default["schema_version"] == SCHEMA_VERSION
        assert default["active_habit"] == state.DEFAULT_HABIT_ID
        assert default["history"] == []
        assert set(default) == {"schema_version", "active_habit", "habits", "sessions", "history"}


class TestEnsureSchema:
    def test_non_dict_becomes_empty_state(self):
        assert state.sessions_of(storage.ensure_schema(["nope"])) == {}

    def test_goal_string_is_coerced(self):
        assert state.goal_of(storage.ensure_schema({"sessions": {}, "goal": "4"})) == 4

    def test_negative_goal_is_clamped(self):
        assert state.goal_of(storage.ensure_schema({"sessions": {}, "goal": -2})) == 0

    def test_non_numeric_goal_falls_back_to_default(self):
        assert state.goal_of(storage.ensure_schema({"sessions": {}, "goal": "many"})) == 5

    def test_missing_goal_gets_the_default(self):
        assert state.goal_of(storage.ensure_schema({})) == 5

    def test_non_dict_sessions_are_replaced(self):
        loaded = storage.ensure_schema({"sessions": [], "goal": 3})
        assert state.sessions_of(loaded) == {}

    def test_unparseable_session_dates_are_dropped(self):
        loaded = storage.ensure_schema({"sessions": {"not-a-date": "x", "2026-03-01": "ok"}})
        assert state.sessions_of(loaded) == {"2026-03-01": "ok"}

    def test_non_string_notes_become_empty_strings(self):
        loaded = storage.ensure_schema({"sessions": {"2026-03-01": 42}})
        assert state.sessions_of(loaded) == {"2026-03-01": ""}

    def test_extra_keys_are_preserved_on_a_v2_document(self):
        doc = state.new_document(goal=3, today=TODAY)
        doc["custom"] = 1
        assert storage.ensure_schema(doc)["custom"] == 1

    def test_a_v1_upgrade_drops_legacy_top_level_keys(self):
        """The upgrade reshapes the document, so v1 cruft is not carried forward."""
        loaded = storage.ensure_schema({"goal": 3, "sessions": {}, "legacy_cruft": 1})
        assert "legacy_cruft" not in loaded

    def test_v1_files_are_upgraded_on_load(self, tmp_path):
        path = tmp_path / "data.json"
        path.write_text(
            json.dumps({"goal": 6, "sessions": {"2026-03-01": "old"}}), encoding="utf-8"
        )
        loaded = storage.JsonBackend(path).load()
        assert loaded["schema_version"] == SCHEMA_VERSION
        assert state.sessions_of(loaded) == {"2026-03-01": "old"}
        assert state.goal_of(loaded) == 6


class TestJsonRecovery:
    def test_corrupt_file_falls_back_to_the_backup(self, tmp_path):
        path = tmp_path / "data.json"
        backend = storage.JsonBackend(path)
        backend.save(make_data(goal=4, **{"2026-03-01": "kept"}))
        backend.save(make_data(goal=5, **{"2026-03-02": "newer"}))
        path.write_text("{ not json", encoding="utf-8")
        assert state.sessions_of(backend.load()) == {"2026-03-01": "kept"}

    def test_corrupt_file_with_no_backup_gives_defaults(self, tmp_path):
        path = tmp_path / "data.json"
        path.write_text("{ not json", encoding="utf-8")
        loaded = storage.JsonBackend(path).load()
        assert state.goal_of(loaded) == 5
        assert state.sessions_of(loaded) == {}

    def test_corrupt_file_is_set_aside_not_deleted(self, tmp_path):
        path = tmp_path / "data.json"
        path.write_text("{ not json", encoding="utf-8")
        storage.JsonBackend(path).load()
        assert not path.exists()
        assert (tmp_path / "data.json.corrupt").exists()

    def test_a_save_rotates_the_previous_file_into_a_backup(self, tmp_path):
        backend = storage.JsonBackend(tmp_path / "data.json")
        backend.save(make_data(goal=1))
        backend.save(make_data(goal=2))
        assert backend.backup_path.exists()
        backed_up = json.loads(backend.backup_path.read_text())
        assert state.goal_of(backed_up) == 1

    def test_no_temporary_file_is_left_behind(self, tmp_path):
        backend = storage.JsonBackend(tmp_path / "data.json")
        backend.save(make_data(goal=1))
        assert list(tmp_path.glob("*.tmp")) == []

    def test_the_data_file_is_never_absent_mid_save(self, tmp_path):
        path = tmp_path / "data.json"
        backend = storage.JsonBackend(path)
        backend.save(make_data(goal=1))
        assert path.exists()


class TestSqliteDetails:
    def test_a_goal_of_zero_survives(self, tmp_path):
        backend = storage.SqliteBackend(tmp_path / "data.sqlite3")
        backend.save(make_data(goal=0, **{"2026-03-01": ""}))
        assert state.goal_of(backend.load()) == 0

    def test_unicode_notes_survive(self, tmp_path):
        backend = storage.SqliteBackend(tmp_path / "data.sqlite3")
        backend.save(make_data(goal=5, **{"2026-03-01": "café über"}))
        assert state.sessions_of(backend.load()) == {"2026-03-01": "café über"}

    def test_repeated_saves_do_not_duplicate_rows(self, tmp_path):
        backend = storage.SqliteBackend(tmp_path / "data.sqlite3")
        for _ in range(3):
            backend.save(make_data(goal=5, **{"2026-03-01": "x"}))
        assert state.sessions_of(backend.load()) == {"2026-03-01": "x"}

    def test_saving_over_a_missing_row_deletes_it(self, tmp_path):
        backend = storage.SqliteBackend(tmp_path / "data.sqlite3")
        backend.save(make_data(goal=5, **{"2026-03-01": "x", "2026-03-02": "y"}))
        backend.save(make_data(goal=5, **{"2026-03-01": "x"}))
        assert list(state.sessions_of(backend.load())) == ["2026-03-01"]

    def test_schema_is_created_on_demand(self, tmp_path):
        path = tmp_path / "data.sqlite3"
        storage.SqliteBackend(path).load()
        with sqlite3.connect(path) as connection:
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        assert {"meta", "habits", "sessions", "history"} <= tables

    def test_sessions_are_queryable_per_habit(self, tmp_path, multi):
        path = tmp_path / "data.sqlite3"
        storage.SqliteBackend(path).save(multi)
        with sqlite3.connect(path) as connection:
            rows = connection.execute(
                "SELECT habit, day FROM sessions WHERE habit = 'morning-run'"
            ).fetchall()
        assert rows == [("morning-run", "2026-03-02")]

    def test_active_habit_is_stored_in_meta(self, tmp_path, multi):
        path = tmp_path / "data.sqlite3"
        storage.SqliteBackend(path).save(multi)
        loaded = storage.SqliteBackend(path).load()
        assert loaded["active_habit"] == "read"

    def test_the_same_day_can_exist_in_two_habits(self, tmp_path):
        doc = state.new_document(goal=5, today=TODAY)
        run = state.add_habit(doc, "Run", goal=3, today=TODAY)
        state.mark(doc, "2026-03-01", "coded")
        state.mark(doc, "2026-03-01", "ran", habit=run)
        backend = storage.SqliteBackend(tmp_path / "data.sqlite3")
        backend.save(doc)
        loaded = backend.load()
        assert state.sessions_of(loaded) == {"2026-03-01": "coded"}
        assert state.sessions_of(loaded, run) == {"2026-03-01": "ran"}


class TestModuleHelpers:
    def test_infer_backend_from_suffix(self):
        assert storage.infer_backend("data.json") == "json"
        assert storage.infer_backend("data.sqlite3") == "sqlite"
        assert storage.infer_backend("data.db") == "sqlite"
        assert storage.infer_backend("data") == "json"

    def test_load_and_save_with_an_explicit_json_path(self, tmp_path, data):
        path = tmp_path / "data.json"
        storage.save_data(data, path)
        assert storage.load_data(path) == data

    def test_load_and_save_with_an_explicit_sqlite_path(self, tmp_path, data):
        path = tmp_path / "data.sqlite3"
        storage.save_data(data, path)
        assert storage.load_data(path) == data

    def test_get_backend_by_name(self, tmp_path):
        assert isinstance(storage.get_backend("json", tmp_path / "a.json"), storage.JsonBackend)
        assert isinstance(
            storage.get_backend("sqlite", tmp_path / "b.sqlite3"), storage.SqliteBackend
        )

    def test_get_backend_rejects_an_unknown_name(self):
        with pytest.raises(StorageError, match="Unknown backend"):
            storage.get_backend("mysql")


class TestMigration:
    def test_json_migrates_into_sqlite(self, tmp_path, data):
        source = tmp_path / "data.json"
        storage.save_data(data, source)
        target = storage.migrate_json_to_sqlite(source, tmp_path / "out.sqlite3")
        assert storage.load_data(target) == data

    def test_json_migrates_multiple_habits_into_sqlite(self, tmp_path, multi):
        source = tmp_path / "data.json"
        storage.save_data(multi, source)
        target = storage.migrate_json_to_sqlite(source, tmp_path / "out.sqlite3")
        assert storage.load_data(target) == multi

    def test_migration_defaults_the_destination_next_to_the_source(self, tmp_path, data):
        source = tmp_path / "data.json"
        storage.save_data(data, source)
        assert storage.migrate_json_to_sqlite(source).suffix == ".sqlite3"


class TestLegacySqliteSchema:
    """A v1 SQLite file has a flat ``sessions`` table with no ``habit`` column."""

    @staticmethod
    def build_v1(path, goal=5, **sessions):
        connection = sqlite3.connect(path)
        connection.executescript(
            """
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE sessions (day TEXT PRIMARY KEY, note TEXT NOT NULL DEFAULT '');
            """
        )
        connection.execute("INSERT INTO meta (key, value) VALUES ('goal', ?)", (str(goal),))
        connection.executemany(
            "INSERT INTO sessions (day, note) VALUES (?, ?)",
            list(sessions.items()),
        )
        connection.commit()
        connection.close()
        return path

    def test_the_legacy_table_is_rebuilt_on_load(self, tmp_path):
        path = self.build_v1(tmp_path / "old.sqlite3", 7, **{"2026-03-01": "shipped"})
        loaded = storage.load_data(path)
        assert loaded["sessions"][state.DEFAULT_HABIT_ID] == {"2026-03-01": "shipped"}

    def test_the_legacy_goal_is_kept(self, tmp_path):
        path = self.build_v1(tmp_path / "old.sqlite3", 7)
        assert state.goal_of(storage.load_data(path), None) == 7

    def test_a_habit_row_is_created_for_the_legacy_data(self, tmp_path):
        path = self.build_v1(tmp_path / "old.sqlite3")
        loaded = storage.load_data(path)
        assert state.DEFAULT_HABIT_ID in state.habit_ids(loaded)
        assert loaded["active_habit"] == state.DEFAULT_HABIT_ID

    def test_the_rebuilt_table_is_queryable(self, tmp_path):
        path = self.build_v1(tmp_path / "old.sqlite3", **{"2026-03-01": "a", "2026-03-02": "b"})
        storage.load_data(path)
        with sqlite3.connect(path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT habit, day, note FROM sessions ORDER BY day"
            ).fetchall()
        assert [row["day"] for row in rows] == ["2026-03-01", "2026-03-02"]
        assert {row["habit"] for row in rows} == {state.DEFAULT_HABIT_ID}

    def test_the_upgrade_survives_a_save_and_reload(self, tmp_path):
        path = self.build_v1(tmp_path / "old.sqlite3", **{"2026-03-01": "a"})
        loaded = storage.load_data(path)
        storage.save_data(loaded, path)
        assert storage.load_data(path) == loaded

    def test_the_upgrade_is_idempotent(self, tmp_path):
        path = self.build_v1(tmp_path / "old.sqlite3", **{"2026-03-01": "a"})
        first = storage.load_data(path)
        assert storage.load_data(path) == first

    def test_an_empty_legacy_table_migrates_cleanly(self, tmp_path):
        path = self.build_v1(tmp_path / "old.sqlite3")
        loaded = storage.load_data(path)
        assert loaded["sessions"][state.DEFAULT_HABIT_ID] == {}


class TestSharedContract:
    @pytest.mark.parametrize("kind", ["json", "sqlite"])
    def test_both_backends_agree_after_a_save_and_load(self, tmp_path, kind, data):
        backend = storage.get_backend(kind, tmp_path / f"data.{kind}")
        backend.save(data)
        loaded = backend.load()
        assert state.sessions_of(loaded) == state.sessions_of(data)
        assert state.goal_of(loaded) == state.goal_of(data)

    @pytest.mark.parametrize("kind", ["json", "sqlite"])
    def test_both_backends_keep_habits_separate(self, tmp_path, kind, multi):
        backend = storage.get_backend(kind, tmp_path / f"data.{kind}")
        backend.save(multi)
        loaded = backend.load()
        assert sorted(loaded["habits"]) == ["coding", "morning-run", "read"]
        assert state.sessions_of(loaded, "coding") == {"2026-03-01": "coding"}
        assert state.sessions_of(loaded, "morning-run") == {"2026-03-02": "miles"}

    @pytest.mark.parametrize("kind", ["json", "sqlite"])
    def test_backends_accept_a_v1_document_and_agree(self, tmp_path, kind):
        legacy = {"goal": 6, "sessions": {"2026-03-01": "ancient"}}
        backend = storage.get_backend(kind, tmp_path / f"legacy.{kind}")
        backend.save(legacy)
        loaded = backend.load()
        assert loaded["schema_version"] == SCHEMA_VERSION
        assert state.sessions_of(loaded) == {"2026-03-01": "ancient"}
        assert state.goal_of(loaded) == 6
