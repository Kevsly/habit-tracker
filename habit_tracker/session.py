"""The shared front-end session.

Every UI (CLI, Textual, Tkinter) used to open the data file, resolve "today",
and write changes back by hand. :class:`Session` does that once.

It also owns the *policy* that used to be copy-pasted per front-end: which
habit is active, that every mutation records an undo step, and that writes to
an unknown habit fail loudly instead of landing in the wrong one.

Reads go through :attr:`view`, a single-habit projection that
:mod:`habit_tracker.tracker` already understands. Writes go through the methods
below, which keep :mod:`habit_tracker.state` invariants intact.
"""

from __future__ import annotations

import argparse
import logging
from datetime import date

from . import config, state, storage, tracker
from .config import Settings

log = logging.getLogger(__name__)


class SessionError(RuntimeError):
    """Base class for session-level problems the user can fix."""


class UnknownHabit(SessionError):
    """Raised when a habit name does not match any defined habit."""


def _label(day: date | str) -> str:
    """Render a day as ISO text for history labels."""
    return day.isoformat() if isinstance(day, date) else str(day)


class Session:
    """One habit's data plus the settings needed to reach and persist it."""

    def __init__(self, settings: Settings, habit: str | None = None) -> None:
        self.settings = settings
        self.document = storage.load_data(settings.data_file, backend=settings.backend)
        self._requested: str | None = None
        if habit is not None:
            self.use(habit)

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> Session:
        """Build a session from parsed CLI arguments."""
        settings = config.resolve_settings(
            getattr(args, "data_dir", None),
            getattr(args, "backend", None),
            getattr(args, "tz", None),
        )
        return cls(settings, habit=getattr(args, "habit", None))

    # -- identity ---------------------------------------------------------

    @property
    def habit(self) -> str:
        """The habit id this session reads and writes."""
        return state.resolve(self.document, self._requested)

    @property
    def habit_label(self) -> str:
        """Display name of the current habit."""
        return state.habit_name(self.document, self.habit)

    def use(self, habit: str | None) -> str:
        """Target a specific habit for this session.

        Raises :class:`UnknownHabit` rather than falling back, so a mistyped
        ``--habit`` can never quietly edit the wrong habit.
        """
        if habit is not None and not state.has_habit(self.document, habit):
            known = ", ".join(sorted(state.habit_ids(self.document))) or "none"
            raise UnknownHabit(f"Unknown habit {habit!r}. Known habits: {known}.")
        self._requested = None if habit is None else state.resolve_strict(self.document, habit)
        return self.habit

    # -- reads ------------------------------------------------------------

    @property
    def view(self) -> dict:
        """Single-habit projection for the analytics layer.

        A copy each access: treat it as read-only.
        """
        return state.habit_view(self.document, self._requested)

    def today(self) -> date:
        """Today's date in the configured timezone."""
        return config.today(self.settings.timezone)

    def goal(self) -> int:
        return state.goal_of(self.document, self._requested)

    def sessions(self) -> dict[str, str]:
        return state.sessions_of(self.document, self._requested)

    def notes_list(self) -> list[str]:
        """Every note string for the active habit.

        The tag indexer takes an iterable of notes, not a ``{day: note}``
        mapping, so this keeps that shape in one place.
        """
        return tracker.session_notes(self.view)

    def notes_all(self) -> list[str]:
        """Every note string across every habit."""
        notes: list[str] = []
        for habit_id in state.habit_ids(self.document):
            notes.extend(tracker.session_notes(state.habit_view(self.document, habit_id)))
        return notes

    def note(self, day: date | str) -> str:
        return state.note_for(self.document, day, self._requested)

    def total_sessions(self) -> int:
        """Sessions across every habit, not just this one."""
        return state.total_sessions(self.document)

    def habits(self) -> list[dict]:
        return state.summarise(self.document)

    def undo_depth(self) -> int:
        return state.undo_depth(self.document)

    def history(self) -> list[dict]:
        """Undoable steps, newest first, for display."""
        return state.history_log(self.document)

    # -- writes -----------------------------------------------------------

    def mark(self, day: date | str, note: str = "") -> str | None:
        """Record a session, recording an undo step first.

        Returns the note it replaced, if any. Call :meth:`save` to persist.
        """
        state.push_history(self.document, f"mark {_label(day)}")
        previous = state.mark(self.document, day, note, self._requested)
        return previous or None

    def clear(self, day: date | str) -> bool:
        """Remove a session, recording an undo step first."""
        state.push_history(self.document, f"clear {_label(day)}")
        return state.clear(self.document, day, self._requested)

    def set_goal(self, goal: int) -> int:
        state.push_history(self.document, "set goal")
        return state.set_goal(self.document, goal, self._requested)

    def undo(self) -> str | None:
        """Roll back the last change. Returns a description, or ``None``."""
        return state.undo(self.document)

    def save(self) -> None:
        """Write the document to disk."""
        storage.save_data(self.document, self.settings.data_file, backend=self.settings.backend)

    # -- habit management -------------------------------------------------

    def add_habit(
        self, name: str, goal: int = 5, today: date | None = None, activate: bool = False
    ) -> str:
        state.push_history(self.document, f"add habit {name}")
        habit_id = state.add_habit(
            self.document, name, goal=goal, today=today or self.today(), activate=activate
        )
        self.save()
        return habit_id

    def rename_habit(self, name: str) -> str:
        state.push_history(self.document, f"rename habit to {name}")
        habit_id = state.rename_habit(self.document, self.habit, name)
        self.save()
        return habit_id

    def use_habit(self, name: str | None) -> str:
        """Change the stored default habit and save it."""
        state.push_history(self.document, f"switch to {name or 'default'}")
        habit_id = state.set_active(self.document, name)
        self._requested = None
        self.save()
        return habit_id

    def remove_habit(self, name: str | None = None) -> str:
        state.push_history(self.document, "remove habit")
        habit_id = state.remove_habit(self.document, name or self.habit)
        if self._requested == habit_id:
            self._requested = None
        self.save()
        return habit_id


def open_session(args: argparse.Namespace | None = None, **overrides) -> Session:
    """Build a :class:`Session` from an argparse namespace or keyword overrides."""
    if args is not None:
        return Session.from_args(args)
    settings = config.resolve_settings(
        overrides.pop("data_dir", None),
        overrides.pop("backend", None),
        overrides.pop("timezone", None),
    )
    return Session(settings, habit=overrides.pop("habit", None))
