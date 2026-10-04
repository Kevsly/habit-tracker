from __future__ import annotations

import json
import subprocess
import sys

import pytest

from habit_tracker import backup, config, state, storage
from habit_tracker.backup import BackupError


@pytest.fixture
def data() -> dict:
    return {"goal": 4, "sessions": {"2026-03-01": "one", "2026-03-02": "#tagged"}}


class TestExport:
    def test_writes_the_requested_path(self, tmp_path, data):
        target = tmp_path / "backup.json"
        assert backup.export_to(target, data) == target
        assert target.exists()

    def test_round_trips_through_import(self, tmp_path, data):
        target = backup.export_to(tmp_path / "backup.json", data)
        assert backup.import_from(target) == storage.ensure_schema(data)

    def test_output_is_readable_json(self, tmp_path, data):
        target = backup.export_to(tmp_path / "backup.json", data)
        parsed = json.loads(target.read_text(encoding="utf-8"))
        assert state.goal_of(parsed) == 4

    def test_creates_missing_directories(self, tmp_path, data):
        target = backup.export_to(tmp_path / "nested" / "deep" / "backup.json", data)
        assert target.exists()

    def test_exports_the_live_store_when_no_data_is_given(self, tmp_path, monkeypatch):
        monkeypatch.setenv(config.ENV_DATA_DIR, str(tmp_path))
        storage.save_data({"goal": 9, "sessions": {}}, tmp_path / "data.json")
        written = backup.export_to(tmp_path / "out.json")
        parsed = json.loads(written.read_text(encoding="utf-8"))
        assert state.goal_of(parsed) == 9

    def test_unwritable_destination_raises(self, tmp_path, data):
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        with pytest.raises(BackupError, match="Could not export"):
            backup.export_to(blocker / "sub" / "backup.json", data)


class TestImport:
    def test_reads_a_valid_export(self, tmp_path, data):
        target = backup.export_to(tmp_path / "backup.json", data)
        assert state.sessions_of(backup.import_from(target))["2026-03-02"] == "#tagged"

    def test_importing_does_not_write_to_the_live_store(self, tmp_path, data):
        live = tmp_path / "live.json"
        storage.save_data({"goal": 1, "sessions": {}}, live)
        target = backup.export_to(tmp_path / "backup.json", data)
        backup.import_from(target)
        assert state.goal_of(storage.load_data(live)) == 1

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(BackupError, match="No such file"):
            backup.import_from(tmp_path / "absent.json")

    def test_invalid_json_raises(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{ not json", encoding="utf-8")
        with pytest.raises(BackupError, match="not valid JSON"):
            backup.import_from(bad)

    def test_non_object_payload_raises(self, tmp_path):
        listy = tmp_path / "list.json"
        listy.write_text("[1, 2, 3]", encoding="utf-8")
        with pytest.raises(BackupError, match="does not contain"):
            backup.import_from(listy)

    def test_missing_fields_are_filled_in(self, tmp_path):
        partial = tmp_path / "partial.json"
        partial.write_text("{}", encoding="utf-8")
        loaded = backup.import_from(partial)
        assert state.goal_of(loaded) == 5
        assert state.sessions_of(loaded) == {}

    def test_unusable_sessions_are_dropped_on_import(self, tmp_path):
        messy = tmp_path / "messy.json"
        messy.write_text(json.dumps({"sessions": {"nope": "x", "2026-03-01": "ok"}}))
        assert state.sessions_of(backup.import_from(messy)) == {"2026-03-01": "ok"}


class TestNoTkinterImport:
    @pytest.mark.parametrize(
        "module",
        ["habit_tracker", "habit_tracker.backup", "habit_tracker.cli", "habit_tracker.tracker"],
    )
    def test_the_headless_path_never_loads_tkinter(self, module):
        """Regression: the old entry point imported tkinter eagerly, so the CLI
        could not start on a machine without Tk (headless Linux, for example)."""
        code = f"import sys, {module}; print('tkinter' in sys.modules)"
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=True
        )
        assert result.stdout.strip() == "False"

    def test_the_gui_module_is_what_loads_tkinter(self):
        code = "import sys, habit_tracker.gui; print('tkinter' in sys.modules)"
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=True
        )
        assert result.stdout.strip() == "True"

    def test_dialog_helpers_exist_without_tkinter_installed(self):
        assert callable(backup.export_dialog)
        assert callable(backup.import_dialog)


class TestSqliteExport:
    def test_a_sqlite_store_exports_to_json(self, tmp_path):
        source = storage.SqliteBackend(tmp_path / "data.sqlite3")
        source.save({"goal": 6, "sessions": {"2026-03-01": "from sqlite"}})
        written = backup.export_to(tmp_path / "export.json", source.load())
        assert state.sessions_of(backup.import_from(written)) == {"2026-03-01": "from sqlite"}
