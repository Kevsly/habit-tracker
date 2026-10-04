"""The state document: schema, habits, sessions, and undo history.

This module owns the *shape* of what gets persisted. It knows nothing about
files, terminals, or Tkinter.

Schema version 2 introduced multiple habits and an undo stack. A document
looks like this::

    {
      "schema_version": 2,
      "active_habit": "coding",
      "habits": {
        "coding": {"name": "Coding", "goal": 5, "created": "2026-10-03"}
      },
      "sessions": {
        "coding": {"2026-10-03": "note text"}
      },
      "history": [ ... previous documents ... ]
    }

Version 1 was a single unnamed habit::

    {"schema_version": 1, "goal": 5, "sessions": {"2026-10-03": "note"}}

:meth:`migrate` upgrades either shape, and is safe to call repeatedly because
every backend runs it on both load and save.

A *view* is the single-habit projection used by the analytics layer::

    {"goal": 5, "sessions": {"2026-10-03": "note"}}

That is deliberately byte-for-byte the version 1 shape, which is why
:mod:`habit_tracker.tracker` and :mod:`habit_tracker.tags` work on habits
without being aware they exist. :meth:`migrate` is the only thing that
understands versions; everything above it speaks views.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any

log = logging.getLogger(__name__)

SCHEMA_VERSION = 2
DEFAULT_HABIT_ID = "coding"
DEFAULT_HABIT_NAME = "Coding"
MAX_UNDO_DEPTH = 50

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    """Turn a habit name into a lowercase, dash-separated identifier."""
    slug = _SLUG_STRIP.sub("-", name.strip().lower()).strip("-")
    return slug or "habit"


def unique_id(base: str, taken: Any) -> str:
    """Return ``base``, or ``base-2``, ``base-3``... if it is already used."""
    if base not in taken:
        return base
    suffix = 2
    while f"{base}-{suffix}" in taken:
        suffix += 1
    return f"{base}-{suffix}"


def new_document(goal: int = 5, today: date | None = None) -> dict:
    """A fresh document with a single default habit and no sessions."""
    day = (today or date.today()).isoformat()
    return {
        "schema_version": SCHEMA_VERSION,
        "active_habit": DEFAULT_HABIT_ID,
        "habits": {
            DEFAULT_HABIT_ID: {
                "name": DEFAULT_HABIT_NAME,
                "goal": max(int(goal), 0),
                "created": day,
            }
        },
        "sessions": {DEFAULT_HABIT_ID: {}},
        "history": [],
    }


def _looks_v2(data: dict) -> bool:
    """A document is v2 if it says so, or if it carries v2-only keys."""
    if "habits" in data or "active_habit" in data:
        return True
    version = data.get("schema_version")
    if not isinstance(version, int):
        return False
    return version >= SCHEMA_VERSION


def _upgrade_v1(data: dict, today: date | None) -> dict:
    """Wrap a single-habit v1 document into a one-habit v2 document."""
    habit_id = unique_id(DEFAULT_HABIT_ID, data)

    try:
        goal = int(data.get("goal", 5))
    except (TypeError, ValueError):
        log.warning("Goal %r is not a number; using 5.", data.get("goal"))
        goal = 5
    goal = max(goal, 0)

    raw_sessions = data.get("sessions")
    if not isinstance(raw_sessions, dict):
        log.warning("Sessions field is not an object; starting with none.")
        raw_sessions = {}

    sessions = _clean_sessions(raw_sessions)

    log.info(
        "Migrating single-habit data to schema v2 as habit %r (%d session(s)).",
        habit_id,
        len(sessions),
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "active_habit": habit_id,
        "habits": {
            habit_id: {
                "name": DEFAULT_HABIT_NAME,
                "goal": goal,
                "created": (today or date.today()).isoformat(),
            }
        },
        "sessions": {habit_id: sessions},
        "history": [],
    }


def _clean_sessions(raw: Any) -> dict[str, str]:
    """Coerce a sessions mapping into ``{iso-date: note}``, dropping bad entries."""
    if not isinstance(raw, dict):
        return {}
    sessions: dict[str, str] = {}
    for key, note in raw.items():
        try:
            iso = date.fromisoformat(str(key)).isoformat()
        except ValueError:
            log.warning("Dropping session with unparseable date %r.", key)
            continue
        sessions[iso] = note if isinstance(note, str) else ""
    return sessions


def migrate(data: object, today: date | None = None) -> dict:
    """Coerce arbitrary loaded data into a valid v2 document.

    Dispatches on ``schema_version``: unknown or missing versions are treated as
    version 1. Idempotent, so backends can call it on every load and save.

    A document written by a *newer* release is returned untouched rather than
    downgraded: stamping it as version 2 would invite the next save to drop
    fields this code does not understand.
    """
    if not isinstance(data, dict):
        log.warning("Expected a JSON object at the top level; starting fresh.")
        data = {}

    version = data.get("schema_version")
    if isinstance(version, int) and not isinstance(version, bool) and version > SCHEMA_VERSION:
        log.warning(
            "Data declares schema version %d but this build understands %d; "
            "leaving it as-is. Upgrade habit-tracker to edit it.",
            version,
            SCHEMA_VERSION,
        )
        return data

    if not _looks_v2(data):
        data = _upgrade_v1(data, today)
    else:
        data = dict(data)

    raw_habits = data.get("habits")
    if not isinstance(raw_habits, dict) or not raw_habits:
        log.warning("Habits field is missing or empty; creating a default habit.")
        return new_document(today=today)

    habits: dict[str, dict] = {}
    raw_sessions = data.get("sessions")
    raw_sessions = raw_sessions if isinstance(raw_sessions, dict) else {}

    for habit_id, entry in raw_habits.items():
        key = str(habit_id).strip()
        if not key:
            log.warning("Skipping habit with a blank id.")
            continue
        entry = entry if isinstance(entry, dict) else {}
        try:
            goal = int(entry.get("goal", 5))
        except (TypeError, ValueError):
            log.warning("Goal %r for habit %r is not a number; using 0.", entry.get("goal"), key)
            goal = 0
        name = entry.get("name")
        created = entry.get("created")
        try:
            created = date.fromisoformat(str(created)).isoformat()
        except ValueError:
            created = (today or date.today()).isoformat()
        habits[key] = {
            "name": name if isinstance(name, str) and name.strip() else key,
            "goal": max(goal, 0),
            "created": created,
        }

    sessions = {key: _clean_sessions(raw_sessions.get(key)) for key in habits}

    active = data.get("active_habit")
    if not isinstance(active, str) or active not in habits:
        active = next(iter(habits))

    data["habits"] = habits
    data["sessions"] = sessions
    data["active_habit"] = active
    data["history"] = _clean_history(data.get("history"))
    data["schema_version"] = SCHEMA_VERSION
    return data


def _clean_history(raw: Any) -> list[dict]:
    """Keep only usable history snapshots, newest last, capped at the limit."""
    if not isinstance(raw, list):
        return []
    kept = [dict(entry) for entry in raw if isinstance(entry, dict)]
    return kept[-MAX_UNDO_DEPTH:]


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------


def habit_ids(doc: dict) -> list[str]:
    """Habit identifiers in document order."""
    habits = doc.get("habits")
    return list(habits) if isinstance(habits, dict) else []


def habit_name(doc: dict, habit_id: str) -> str:
    """Display name for ``habit_id``, falling back to its identifier."""
    entry = doc.get("habits", {}).get(habit_id)
    if isinstance(entry, dict) and isinstance(entry.get("name"), str) and entry["name"].strip():
        return entry["name"]
    return habit_id


def resolve(doc: dict, habit: str | None) -> str:
    """Map a user-supplied name or id to a habit id, case-insensitively.

    Lenient, so reads never fail on a typo: falls back to the active habit when
    the argument is ``None`` or matches nothing. Writing code must use
    :func:`resolve_strict` instead, otherwise a typo would silently land in the
    wrong habit.
    """
    habits = doc.get("habits", {})
    active = doc.get("active_habit")
    if not isinstance(active, str) or active not in habits:
        active = next(iter(habits), None)
    if habit is None:
        return active

    match = _match(doc, habit)
    return match if match is not None else active


def _match(doc: dict, habit: str) -> str | None:
    """Find a habit by id, display name, or slug. ``None`` when not found."""
    habits = doc.get("habits", {})
    wanted = str(habit).strip().lower()
    if wanted in habits:
        return wanted
    slug = slugify(str(habit))
    if slug in habits:
        return slug
    for habit_id in habits:
        if habit_id.lower() == wanted or habit_name(doc, habit_id).lower() == wanted:
            return habit_id
    return None


def resolve_strict(doc: dict, habit: str | None) -> str:
    """Like :func:`resolve`, but raises ``KeyError`` for an unknown habit.

    Used by every mutating helper so that ``--habit tpyo`` fails loudly instead
    of quietly editing the active habit.
    """
    if habit is None:
        return resolve(doc, None)
    match = _match(doc, habit)
    if match is None:
        known = ", ".join(sorted(state_key for state_key in doc.get("habits", {}))) or "none"
        raise KeyError(f"Unknown habit {habit!r}. Known habits: {known}.")
    return match


def has_habit(doc: dict, habit: str) -> bool:
    """True when ``habit`` names an existing habit."""
    wanted = str(habit).strip().lower()
    if wanted in doc.get("habits", {}):
        return True
    return any(habit_name(doc, habit_id).lower() == wanted for habit_id in doc.get("habits", {}))


def habit_view(doc: dict, habit: str | None = None) -> dict:
    """Project one habit into the single-habit shape the analytics layer reads.

    The returned dict is a *copy*: mutating it will not change ``doc``. Use
    :func:`mark` and :func:`clear` to persist changes.
    """
    habit_id = resolve(doc, habit)
    entry = doc.get("habits", {}).get(habit_id, {})
    goal = entry.get("goal", 0) if isinstance(entry, dict) else 0
    sessions = doc.get("sessions", {}).get(habit_id, {})
    return {"goal": goal, "sessions": dict(sessions)}


def sessions_of(doc: dict, habit: str | None = None) -> dict[str, str]:
    """Session notes for one habit."""
    return dict(doc.get("sessions", {}).get(resolve(doc, habit), {}))


def total_sessions(doc: dict) -> int:
    """Sessions recorded across every habit."""
    sessions = doc.get("sessions", {})
    if not isinstance(sessions, dict):
        return 0
    return sum(len(entries) for entries in sessions.values() if isinstance(entries, dict))


def goal_of(doc: dict, habit: str | None = None) -> int:
    """Weekly goal for one habit."""
    habit_id = resolve(doc, habit)
    entry = doc.get("habits", {}).get(habit_id, {})
    return entry.get("goal", 0) if isinstance(entry, dict) else 0


def note_for(doc: dict, day: date | str, habit: str | None = None) -> str:
    """The note stored for ``day``, or an empty string."""
    sessions = doc.get("sessions", {}).get(resolve(doc, habit), {})
    if isinstance(day, date):
        day = day.isoformat()
    note = sessions.get(day)
    return note if isinstance(note, str) else ""


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------


def _snapshot(doc: dict) -> dict:
    """Capture the undoable parts of a document (never the history itself)."""
    return {
        "active_habit": doc.get("active_habit"),
        "habits": {k: dict(v) for k, v in doc.get("habits", {}).items() if isinstance(v, dict)},
        "sessions": {k: dict(v) for k, v in doc.get("sessions", {}).items() if isinstance(v, dict)},
    }


def push_history(doc: dict, action: str = "", now: datetime | None = None) -> None:
    """Record the current state so it can be restored by :func:`undo`.

    ``action`` is a short label describing the change about to be made, kept so
    ``ht history`` can say what each undoable step was instead of only how many
    exist.
    """
    history = doc.setdefault("history", [])
    history.append(
        {
            "at": (now or datetime.now()).isoformat(timespec="seconds"),
            "action": str(action or ""),
            "document": _snapshot(doc),
        }
    )
    if len(history) > MAX_UNDO_DEPTH:
        del history[: len(history) - MAX_UNDO_DEPTH]


def history_log(doc: dict) -> list[dict]:
    """Undoable steps, newest first, for display.

    Each entry is ``{"at", "action", "habits", "sessions"}``. Steps written
    before labels existed have no timestamp or action, so those come back as
    empty strings rather than being dropped.
    """
    history = doc.get("history")
    if not isinstance(history, list):
        return []

    rows: list[dict] = []
    for entry in reversed(history):
        if not isinstance(entry, dict):
            continue
        snapshot = _entry_snapshot(entry)
        rows.append(
            {
                "at": entry.get("at") if isinstance(entry.get("at"), str) else "",
                "action": entry.get("action") if isinstance(entry.get("action"), str) else "",
                "habits": len(snapshot.get("habits", {})),
                "sessions": sum(len(notes) for notes in snapshot.get("sessions", {}).values()),
            }
        )
    return rows


def _entry_snapshot(entry: dict) -> dict:
    """The document snapshot inside a history entry.

    Accepts both the labelled envelope written by :func:`push_history` and the
    bare snapshot written by earlier versions, so old files keep working.
    """
    inner = entry.get("document")
    return inner if isinstance(inner, dict) else entry


def undo_depth(doc: dict) -> int:
    """How many steps are available to undo."""
    history = doc.get("history")
    return len(history) if isinstance(history, list) else 0


def undo(doc: dict) -> str | None:
    """Roll back the most recent change.

    Returns a short description of what was restored, or ``None`` when there is
    nothing to undo. The undone step is dropped rather than re-applied, so
    repeated calls walk backwards through history instead of toggling.
    """
    history = doc.get("history")
    if not isinstance(history, list) or not history:
        return None

    snapshot = history.pop()
    if not isinstance(snapshot, dict):
        return None

    snapshot = _entry_snapshot(snapshot)
    restored = snapshot.get("active_habit")
    doc["habits"] = {
        k: dict(v) for k, v in snapshot.get("habits", {}).items() if isinstance(v, dict)
    }
    doc["sessions"] = {
        k: dict(v) for k, v in snapshot.get("sessions", {}).items() if isinstance(v, dict)
    }
    active = doc.get("active_habit")
    if isinstance(restored, str) and restored in doc["habits"]:
        doc["active_habit"] = restored
    elif active not in doc["habits"]:
        doc["active_habit"] = next(iter(doc["habits"]), DEFAULT_HABIT_ID)

    return f"restored {len(doc['habits'])} habit(s) with {total_sessions(doc)} session(s)"


def mark(doc: dict, day: date | str, note: str = "", habit: str | None = None) -> str | None:
    """Record a session for ``day``. Returns the note it replaced, if any.

    Caller is responsible for saving; see :func:`push_history` for undo.
    """
    habit_id = resolve_strict(doc, habit)
    if habit_id not in doc.get("habits", {}):
        raise KeyError(f"Unknown habit {habit_id!r}")

    if isinstance(day, date):
        day = day.isoformat()
    else:
        day = date.fromisoformat(str(day)).isoformat()

    sessions = doc.setdefault("sessions", {}).setdefault(habit_id, {})
    previous = sessions.get(day)
    sessions[day] = note if isinstance(note, str) else ""
    return previous if isinstance(previous, str) and previous else None


def clear(doc: dict, day: date | str, habit: str | None = None) -> bool:
    """Remove the session for ``day``. True when something was removed."""
    habit_id = resolve_strict(doc, habit)
    if isinstance(day, date):
        day = day.isoformat()
    sessions = doc.get("sessions", {}).get(habit_id)
    if not isinstance(sessions, dict) or day not in sessions:
        return False
    del sessions[day]
    return True


def set_goal(doc: dict, goal: int, habit: str | None = None) -> int:
    """Set a habit's weekly goal. ``0`` turns the goal off."""
    habit_id = resolve_strict(doc, habit)
    entry = doc.get("habits", {}).get(habit_id)
    if not isinstance(entry, dict):
        raise KeyError(f"Unknown habit {habit_id!r}")
    value = max(int(goal), 0)
    entry["goal"] = value
    return value


def _reject_duplicate_name(doc: dict, name: str, *, exclude: str | None = None) -> None:
    """Refuse a display name another habit already uses.

    Habits are targeted by name as well as by id, so two habits sharing a name
    would make ``--habit <name>`` silently pick the first one.
    """
    wanted = name.strip().lower()
    for habit_id in doc.get("habits", {}):
        if habit_id != exclude and habit_name(doc, habit_id).strip().lower() == wanted:
            raise ValueError(f"A habit named {name.strip()!r} already exists.")


def add_habit(
    doc: dict,
    name: str,
    goal: int = 5,
    today: date | None = None,
    activate: bool = False,
) -> str:
    """Create a habit and return its new identifier.

    Raises ``ValueError`` for an empty or already-used name. Distinct names whose
    slugs collide still get distinct ids via :func:`unique_id`.
    """
    habits = doc.setdefault("habits", {})
    clean = name.strip()
    if not clean:
        raise ValueError("Habit name cannot be empty.")
    _reject_duplicate_name(doc, clean)

    habit_id = unique_id(slugify(clean), habits)
    habits[habit_id] = {
        "name": clean,
        "goal": max(int(goal), 0),
        "created": (today or date.today()).isoformat(),
    }
    doc.setdefault("sessions", {}).setdefault(habit_id, {})
    if activate:
        doc["active_habit"] = habit_id
    return habit_id


def rename_habit(doc: dict, habit: str, name: str) -> str:
    """Change a habit's display name, keeping its identifier stable."""
    habit_id = resolve_strict(doc, habit)
    clean = name.strip()
    if not clean:
        raise ValueError("Habit name cannot be empty.")
    _reject_duplicate_name(doc, clean, exclude=habit_id)
    doc["habits"][habit_id]["name"] = clean
    return habit_id


def set_active(doc: dict, habit: str | None) -> str:
    """Make ``habit`` the default. Returns the resulting active identifier."""
    habits = doc.get("habits", {})
    if not habits:
        raise KeyError("No habits defined.")
    if habit is None:
        habit_id = doc.get("active_habit")
        if not isinstance(habit_id, str) or habit_id not in habits:
            habit_id = next(iter(habits))
    else:
        wanted = str(habit).strip().lower()
        match = wanted if wanted in habits else None
        if match is None:
            for candidate in habits:
                if habit_name(doc, candidate).lower() == wanted or slugify(candidate) == wanted:
                    match = candidate
                    break
        if match is None:
            raise KeyError(f"Unknown habit {habit!r}.")
        habit_id = match
    doc["active_habit"] = habit_id
    return habit_id


def remove_habit(doc: dict, habit: str) -> str:
    """Delete a habit and its sessions.

    The last remaining habit cannot be removed.
    """
    habit_id = resolve_strict(doc, habit)
    habits = doc.get("habits", {})
    if len(habits) <= 1:
        raise ValueError("Cannot remove the only habit.")
    del habits[habit_id]
    doc.get("sessions", {}).pop(habit_id, None)
    if doc.get("active_habit") == habit_id:
        doc["active_habit"] = next(iter(habits))
    return habit_id


def summarise(doc: dict) -> list[dict]:
    """One row per habit for ``ht habit list``."""
    active = doc.get("active_habit")
    rows = []
    for habit_id in habit_ids(doc):
        entry = doc.get("habits", {}).get(habit_id, {})
        sessions = doc.get("sessions", {}).get(habit_id, {})
        rows.append(
            {
                "id": habit_id,
                "name": entry.get("name", habit_id),
                "goal": entry.get("goal", 0),
                "sessions": len(sessions),
                "created": entry.get("created", ""),
                "active": habit_id == active,
            }
        )
    return rows
