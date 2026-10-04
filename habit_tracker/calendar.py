"""Month grid model shared by the terminal and desktop views.

Pure functions over a single-habit view (the ``{"goal", "sessions"}`` shape
that :mod:`habit_tracker.tracker` reads), so the CLI's ``ht month`` and the GUI
calendar cannot disagree about what a month looks like.

No I/O and no widgets: :class:`MonthCell` knows how to draw itself as text, and
the GUI only reads the fields.
"""

from __future__ import annotations

import calendar as _calendar
from dataclasses import dataclass
from datetime import date, datetime

MONTH_HEADER = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")
_BLANK = "  .  "
_MONTH_FORMATS = ("%Y-%m", "%Y-%m-%d", "%Y/%m", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y")


@dataclass(frozen=True)
class MonthCell:
    """One day position in a month grid."""

    day: date | None
    done: bool = False
    note: str = ""
    today: bool = False
    future: bool = False

    @property
    def label(self) -> str:
        """Two-character day number, blank for padding."""
        return f"{self.day.day:>2}" if self.day else "  "

    def render(self, width: int = 5) -> str:
        """Text representation: a marker plus the day number."""
        if self.day is None:
            return _BLANK.rjust(width)
        if self.future:
            marker = "."
        elif self.done:
            marker = "#"
        else:
            marker = " "
        return f"{marker}{self.label}".rjust(width)

    def marker(self) -> str:
        """Single-character status for compact displays and heatmaps."""
        if self.day is None:
            return " "
        if self.future:
            return "."
        return "x" if self.done else " "


@dataclass(frozen=True)
class MonthSummary:
    """Totals for a displayed month."""

    anchor: date
    done: int
    elapsed: int
    possible: int
    rate: float
    best_day: int
    future_days: int
    has_data: bool

    @property
    def percent(self) -> int:
        return round(self.rate * 100)


def parse_month(text: str) -> date:
    """Parse a month argument, returning the first day of that month.

    Accepts ``YYYY-MM``, ``YYYY-MM-DD``, slash-separated equivalents, and
    ``DD-MM-YYYY``. Raises :class:`ValueError` on nonsense so callers can report
    it as user error rather than a traceback.
    """
    raw = str(text).strip()
    for fmt in _MONTH_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date().replace(day=1)
        except ValueError:
            continue
    raise ValueError(f"Could not read {text!r} as a month. Use YYYY-MM, for example 2026-10.")


def month_grid(anchor: date, view: dict, today: date | None = None) -> list[list[MonthCell]]:
    """Weeks of ``anchor``'s month as cells, Monday-first with padding.

    ``view`` is a single-habit view, matching :func:`month_summary` so callers
    pass the same thing to both. ``today`` defaults to the real current date;
    pass it explicitly in tests or when a habit is tracked in another timezone.
    """
    reference = today or date.today()
    sessions = view.get("sessions", {}) if isinstance(view, dict) else {}
    done_set: set[date] = set()
    for entry in sessions:
        try:
            day = date.fromisoformat(str(entry))
        except ValueError:
            continue
        if day.year == anchor.year and day.month == anchor.month:
            done_set.add(day)

    weeks: list[list[MonthCell]] = []
    for week in _calendar.Calendar(firstweekday=0).monthdatescalendar(anchor.year, anchor.month):
        cells: list[MonthCell] = []
        for day in week:
            if day.month != anchor.month:
                cells.append(MonthCell(None))
                continue
            cells.append(
                MonthCell(
                    day=day,
                    done=day in done_set,
                    note=sessions.get(day.isoformat(), ""),
                    today=day == reference,
                    future=day > reference,
                )
            )
        weeks.append(cells)
    return weeks


def month_summary(anchor: date, view: dict, today: date | None = None) -> MonthSummary:
    """Completion totals for the month, counting only elapsed days.

    Days in the future are excluded from the denominator, so a month shown on
    the 3rd never reads as "0% done" because most of it has not happened yet.
    """
    reference = today or date.today()
    days_in_month = _calendar.monthrange(anchor.year, anchor.month)[1]

    elapsed = 0
    for offset in range(1, days_in_month + 1):
        day = date(anchor.year, anchor.month, offset)
        if day <= reference:
            elapsed += 1
    possible = elapsed

    done = 0
    for iso in view.get("sessions", {}):
        try:
            day = date.fromisoformat(iso)
        except ValueError:
            continue
        if day.year == anchor.year and day.month == anchor.month and day <= reference:
            done += 1

    future_days = max(days_in_month - elapsed, 0)
    best = _longest_run_within(view, anchor, reference)
    return MonthSummary(
        anchor=anchor,
        done=done,
        elapsed=elapsed,
        possible=possible,
        rate=(done / possible) if possible else 0.0,
        best_day=best,
        future_days=future_days,
        has_data=done > 0,
    )


def _longest_run_within(view: dict, anchor: date, reference: date) -> int:
    """Longest consecutive run of marked days inside the month, up to today."""
    days_in_month = _calendar.monthrange(anchor.year, anchor.month)[1]
    sessions = view.get("sessions", {})
    best = 0
    current = 0
    for offset in range(1, days_in_month + 1):
        day = date(anchor.year, anchor.month, offset)
        if day > reference:
            break
        if sessions.get(day.isoformat()) is not None:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best
