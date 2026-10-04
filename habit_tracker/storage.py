"""Persistence backends.

``JsonBackend`` is the default and stores the whole state as one readable file.
``SqliteBackend`` uses the standard library's ``sqlite3`` module for a schema
that can grow without rewriting a monolith. Both satisfy :class:`Backend`, so
``load_data`` / ``save_data`` are interchangeable.

Writes are atomic: content goes to a temporary file in the same directory and is
then moved into place with :func:`os.replace`, so an interrupted save can never
truncate the previous state.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
from datetime import date
from pathlib import Path
from typing import Protocol

from . import state
from .config import DEFAULT_BACKEND, DEFAULT_GOAL, data_file

log = logging.getLogger(__name__)

SCHEMA_VERSION = state.SCHEMA_VERSION
SQLITE_SUFFIXES = (".sqlite", ".sqlite3", ".db")


class Backend(Protocol):
    """Minimal persistence contract shared by every backend."""

    path: Path

    def load(self) -> dict: ...

    def save(self, data: dict) -> None: ...


class StorageError(RuntimeError):
    """Raised when persisted data cannot be read or written."""


def default_data() -> dict:
    """A fresh, empty state document with one default habit."""
    return state.new_document(goal=DEFAULT_GOAL)


def ensure_schema(data: object) -> dict:
    """Coerce arbitrary loaded data into a valid v2 state document.

    Thin wrapper around :func:`habit_tracker.state.migrate`, which owns the
    version dispatch. Backends call this on both load and save, so it must stay
    idempotent. Bad entries are dropped with a warning rather than raising.
    """
    return state.migrate(data)


class JsonBackend:
    """Atomic single-file JSON storage with a rotating ``.bak`` copy."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.backup_path = self.path.with_suffix(self.path.suffix + ".bak")

    def load(self) -> dict:
        if not self.path.exists():
            return default_data()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            log.error("Corrupt data file %s: %s", self.path, exc)
            recovered = self._load_backup()
            if recovered is not None:
                log.warning("Recovered data from %s.", self.backup_path)
                return recovered
            self._quarantine()
            return default_data()
        except OSError as exc:
            raise StorageError(f"Could not read {self.path}: {exc}") from exc
        return ensure_schema(raw)

    def save(self, data: dict) -> None:
        payload = ensure_schema(data)
        staging = self.path.with_name(f"{self.path.name}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists():
                shutil.copy2(self.path, self.backup_path)
            with staging.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            staging.replace(self.path)
        except OSError as exc:
            staging.unlink(missing_ok=True)
            raise StorageError(f"Could not write {self.path}: {exc}") from exc

    def _load_backup(self) -> dict | None:
        if not self.backup_path.exists():
            return None
        try:
            return ensure_schema(json.loads(self.backup_path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            return None

    def _quarantine(self) -> None:
        broken = self.path.with_name(f"{self.path.name}.corrupt")
        try:
            self.path.replace(broken)
            log.error("Moved unreadable data file to %s.", broken)
        except OSError:
            log.exception("Could not quarantine %s.", self.path)


class SqliteBackend:
    """Relational storage using the standard library ``sqlite3`` module.

    Habits, sessions, and undo snapshots get their own tables so the store can
    be queried directly (``SELECT * FROM sessions WHERE habit = 'run'``) without
    going through the JSON blob. ``meta`` carries the document-level values.
    """

    SCHEMA = """
        CREATE TABLE IF NOT EXISTS meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS habits (
            id      TEXT PRIMARY KEY,
            name    TEXT NOT NULL,
            goal    INTEGER NOT NULL DEFAULT 0,
            created TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            habit TEXT NOT NULL,
            day   TEXT NOT NULL,
            note  TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (habit, day)
        );
        CREATE TABLE IF NOT EXISTS history (
            seq      INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot TEXT NOT NULL
        );
    """

    # Created after the tables, and only once the legacy-table rebuild has run:
    # indexing (habit, day) against a pre-v2 ``sessions`` table would fail.
    INDEXES = "CREATE INDEX IF NOT EXISTS idx_sessions_habit ON sessions (habit, day);"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.executescript(self.SCHEMA)
        self._upgrade_legacy_tables(connection)
        connection.executescript(self.INDEXES)
        return connection

    @staticmethod
    def _upgrade_legacy_tables(connection: sqlite3.Connection) -> None:
        """Rebuild a pre-v2 ``sessions`` table so old databases keep working.

        v1 stored one flat ``sessions(day PRIMARY KEY, note)`` table. The v2
        schema adds ``habit`` to the primary key, and ``CREATE TABLE IF NOT
        EXISTS`` will not alter an existing table, so the shape has to be
        checked and rebuilt explicitly. Existing rows are kept and attributed to
        the active habit, which is what they meant in v1.
        """
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(sessions)")}
        if not columns or "habit" in columns:
            return

        log.warning("Upgrading legacy SQLite schema to version %d.", state.SCHEMA_VERSION)
        habit_id = state.DEFAULT_HABIT_ID
        row = connection.execute("SELECT value FROM meta WHERE key = 'active_habit'").fetchone()
        if row is not None and str(row["value"]).strip():
            habit_id = str(row["value"]).strip()

        connection.execute("ALTER TABLE sessions RENAME TO sessions_v1")
        connection.execute(
            """
            CREATE TABLE sessions (
                habit TEXT NOT NULL,
                day   TEXT NOT NULL,
                note  TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (habit, day)
            )
            """
        )
        connection.execute(
            "INSERT OR REPLACE INTO sessions (habit, day, note) "
            f"SELECT '{habit_id}', day, note FROM sessions_v1"
        )
        connection.execute("DROP TABLE sessions_v1")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_sessions_habit ON sessions (habit, day)")

        known = connection.execute("SELECT 1 FROM habits WHERE id = ?", (habit_id,)).fetchone()
        if known is None:
            goal_row = connection.execute("SELECT value FROM meta WHERE key = 'goal'").fetchone()
            try:
                goal = max(int(goal_row["value"]), 0) if goal_row is not None else DEFAULT_GOAL
            except (TypeError, ValueError):
                goal = DEFAULT_GOAL
            connection.execute(
                "INSERT INTO habits (id, name, goal, created) VALUES (?, ?, ?, ?)",
                (habit_id, habit_id.title(), goal, date.today().isoformat()),
            )
        connection.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('active_habit', ?)", (habit_id,)
        )
        connection.commit()

    def load(self) -> dict:
        try:
            with self._connect() as connection:
                meta = {
                    row["key"]: row["value"]
                    for row in connection.execute("SELECT key, value FROM meta")
                }
                habits = {
                    row["id"]: {
                        "name": row["name"],
                        "goal": row["goal"],
                        "created": row["created"],
                    }
                    for row in connection.execute(
                        "SELECT id, name, goal, created FROM habits ORDER BY rowid"
                    )
                }
                sessions: dict[str, dict[str, str]] = {}
                for row in connection.execute("SELECT habit, day, note FROM sessions"):
                    sessions.setdefault(row["habit"], {})[row["day"]] = row["note"]
                history = [
                    json.loads(row["snapshot"])
                    for row in connection.execute("SELECT snapshot FROM history ORDER BY seq")
                ]
        except (sqlite3.Error, json.JSONDecodeError) as exc:
            raise StorageError(f"Could not read {self.path}: {exc}") from exc

        data: dict = {
            "habits": habits,
            "sessions": sessions,
            "history": history,
            "active_habit": meta.get("active_habit", ""),
        }
        if "schema_version" in meta:
            data["schema_version"] = int(meta["schema_version"])
        return ensure_schema(data)

    def save(self, data: dict) -> None:
        payload = ensure_schema(data)
        habits = payload.get("habits", {})
        sessions = payload.get("sessions", {})
        history = payload.get("history", [])
        try:
            with self._connect() as connection:
                connection.execute("DELETE FROM sessions")
                connection.execute("DELETE FROM habits")
                connection.execute("DELETE FROM history")
                connection.executemany(
                    "INSERT INTO habits (id, name, goal, created) VALUES (?, ?, ?, ?)",
                    [
                        (habit_id, entry["name"], int(entry["goal"]), entry["created"])
                        for habit_id, entry in habits.items()
                    ],
                )
                connection.executemany(
                    "INSERT INTO sessions (habit, day, note) VALUES (?, ?, ?)",
                    sorted(
                        (habit_id, day, note)
                        for habit_id, entries in sessions.items()
                        for day, note in entries.items()
                    ),
                )
                connection.executemany(
                    "INSERT INTO history (snapshot) VALUES (?)",
                    [(json.dumps(entry, sort_keys=True),) for entry in history],
                )
                connection.executemany(
                    "INSERT INTO meta (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    [
                        ("schema_version", str(payload["schema_version"])),
                        ("active_habit", str(payload["active_habit"])),
                    ],
                )
        except sqlite3.Error as exc:
            raise StorageError(f"Could not write {self.path}: {exc}") from exc


def infer_backend(path: str | Path) -> str:
    """Guess ``sqlite`` or ``json`` from a filename suffix."""
    return "sqlite" if Path(path).suffix.lower() in SQLITE_SUFFIXES else "json"


def get_backend(kind: str = DEFAULT_BACKEND, path: str | Path | None = None) -> Backend:
    """Build a backend for ``kind``, defaulting the path to the configured location."""
    if kind == "json":
        return JsonBackend(path or data_file(backend="json"))
    if kind == "sqlite":
        return SqliteBackend(path or data_file(backend="sqlite"))
    raise StorageError(f"Unknown backend {kind!r}. Choose 'json' or 'sqlite'.")


def load_data(path: str | Path | None = None, *, backend: str | None = None) -> dict:
    """Load state, inferring the backend from ``path`` when not given."""
    if path is not None:
        chosen = backend or infer_backend(path)
        return get_backend(chosen, path).load()
    return get_backend(backend or DEFAULT_BACKEND).load()


def save_data(data: dict, path: str | Path | None = None, *, backend: str | None = None) -> None:
    """Save state, inferring the backend from ``path`` when not given."""
    if path is not None:
        chosen = backend or infer_backend(path)
        get_backend(chosen, path).save(data)
        return
    get_backend(backend or DEFAULT_BACKEND).save(data)


def migrate_json_to_sqlite(source: str | Path, destination: str | Path | None = None) -> Path:
    """Copy a JSON data file into a SQLite store. Returns the database path."""
    target = Path(destination) if destination else Path(source).with_suffix(".sqlite3")
    SqliteBackend(target).save(JsonBackend(source).load())
    return target
