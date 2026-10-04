"""Domain logic for sessions, streaks, goals and the calendar heatmap.

Pure and side-effect free: every function that needs the current date accepts an
optional ``today`` so callers (and tests) can pin it.
"""

from __future__ import annotations

from datetime import date, timedelta

from .dates import (
    ONE_DAY,
    ONE_WEEK,
    WEEKDAY_NAMES,
    DateParseError,
    month_label,
    parse_date,
    week_days,
    week_start,
)
from .tags import get_tags, ranked_tag_counts

__all__ = [
    "ONE_DAY",
    "ONE_WEEK",
    "WEEKDAY_NAMES",
    "DateParseError",
    "busiest_weekday",
    "clear_session",
    "completion_rate",
    "current_streak",
    "day_status",
    "get_tags",
    "has_session",
    "heatmap_grid",
    "heatmap_month_labels",
    "longest_streak",
    "mark_session",
    "month_label",
    "month_totals",
    "note_for",
    "parse_date",
    "ranked_tag_counts",
    "resolve_day",
    "session_notes",
    "sessions_in_range",
    "total_sessions",
    "week_days",
    "week_progress",
    "week_rows",
    "week_start",
]

DONE = "done"
MISS = "miss"
FUTURE = "future"


def resolve_day(text: str, today: date | None = None, *, allow_future: bool = False) -> date:
    """Parse user input into a date. See :func:`habit_tracker.dates.parse_date`."""
    return parse_date(text, today=today, allow_future=allow_future)


def session_days(data: dict) -> list[date]:
    """Every valid session date in ``data``, ascending. Malformed keys are skipped."""
    days: list[date] = []
    for key in data.get("sessions", {}):
        try:
            days.append(date.fromisoformat(key))
        except (TypeError, ValueError):
            continue
    return sorted(days)


def session_notes(data: dict) -> list[str]:
    """Every session note in ``data``."""
    return [note for note in data.get("sessions", {}).values() if isinstance(note, str)]


def mark_session(data: dict, day: date, note: str = "") -> dict:
    """Record a session on ``day``. Re-marking replaces the previous note."""
    data.setdefault("sessions", {})[day.isoformat()] = note or ""
    return data


def clear_session(data: dict, day: date) -> bool:
    """Remove a session. Returns ``True`` if one was there."""
    return data.setdefault("sessions", {}).pop(day.isoformat(), None) is not None


def has_session(data: dict, day: date) -> bool:
    """Whether ``day`` is marked."""
    return day.isoformat() in data.get("sessions", {})


def note_for(data: dict, day: date) -> str:
    """The note stored for ``day``, or an empty string."""
    return data.get("sessions", {}).get(day.isoformat(), "")


def day_status(data: dict, day: date, today: date | None = None) -> str:
    """``DONE``, ``FUTURE`` or ``MISS`` for a single day."""
    today = today or date.today()
    if has_session(data, day):
        return DONE
    if day > today:
        return FUTURE
    return MISS


def week_rows(data: dict, day: date, today: date | None = None) -> list[dict]:
    """One row per day of the week containing ``day``, Monday first."""
    today = today or date.today()
    return [
        {
            "day": current,
            "label": WEEKDAY_NAMES[current.weekday()],
            "done": has_session(data, current),
            "note": note_for(data, current),
            "future": current > today,
        }
        for current in week_days(day)
    ]


def week_progress(data: dict, day: date, today: date | None = None) -> tuple[int, int]:
    """Sessions completed and weekly goal.

    Future days are excluded from the count so a pre-marked week cannot inflate
    progress towards the goal.
    """
    today = today or date.today()
    rows = week_rows(data, day, today)
    done = sum(1 for row in rows if row["done"] and not row["future"])
    goal = data.get("goal", 0)
    return done, goal if isinstance(goal, int) and goal > 0 else 0


def completion_rate(data: dict, start: date, end: date, today: date | None = None) -> float:
    """Fraction of elapsed days in ``[start, end]`` that are marked.

    Days after ``today`` are excluded from the denominator.
    """
    today = today or date.today()
    elapsed_start = min(start, today)
    elapsed_end = min(end, today)
    if elapsed_end < elapsed_start:
        return 0.0
    total = (elapsed_end - elapsed_start).days + 1
    if total <= 0:
        return 0.0
    marked_days = sum(
        1 for current in session_days(data) if elapsed_start <= current <= elapsed_end
    )
    return marked_days / total


def current_streak(data: dict, today: date | None = None) -> int:
    """Length of the run of consecutive marked days ending today or yesterday."""
    today = today or date.today()
    sessions = data.get("sessions", {})
    cursor = today if today.isoformat() in sessions else today - ONE_DAY
    streak = 0
    while cursor.isoformat() in sessions:
        streak += 1
        cursor -= ONE_DAY
    return streak


def longest_streak(data: dict) -> int:
    """Longest run of consecutive marked days anywhere in the data."""
    best = 0
    run = 0
    previous: date | None = None

    for current in session_days(data):
        run = run + 1 if previous and current - previous == ONE_DAY else 1
        best = max(best, run)
        previous = current

    return best


def total_sessions(data: dict) -> int:
    """How many days are marked."""
    return len(session_days(data))


def busiest_weekday(data: dict) -> tuple[str | None, int]:
    """Most-used weekday and its count, or ``(None, 0)`` when there is no data."""
    counts = dict.fromkeys(WEEKDAY_NAMES, 0)
    for day in session_days(data):
        counts[WEEKDAY_NAMES[day.weekday()]] += 1

    top_count = max(counts.values(), default=0)
    if top_count == 0:
        return None, 0
    return max(counts, key=lambda name: counts[name]), top_count


def sessions_in_range(data: dict, start: date, end: date) -> list[date]:
    """Marked days within ``[start, end]``, ascending."""
    return [day for day in session_days(data) if start <= day <= end]


def month_totals(data: dict, day: date) -> dict[int, int]:
    """Sessions per day-of-month for the month containing ``day``."""
    totals: dict[int, int] = {}
    for current in sessions_in_range(data, day.replace(day=1), _month_end(day)):
        totals[current.day] = totals.get(current.day, 0) + 1
    return totals


def _month_end(day: date) -> date:
    following = (
        day.replace(year=day.year + 1, month=1)
        if day.month == 12
        else day.replace(month=day.month + 1)
    )
    return following - ONE_DAY


def heatmap_grid(
    data: dict,
    end: date | None = None,
    weeks: int = 12,
    today: date | None = None,
) -> list[dict]:
    """Week-aligned heatmap cells, Monday-first rows and one column per week.

    The final column is the week containing ``end``; earlier columns are whole
    weeks before it, so every column lines up with a calendar week.
    """
    end = end or date.today()
    today = today or end
    first = week_start(end) - timedelta(weeks=weeks - 1)
    grid = []
    for offset in range(weeks * 7):
        current = first + timedelta(days=offset)
        grid.append(
            {
                "day": current,
                "row": offset % 7,
                "col": offset // 7,
                "status": day_status(data, current, today),
            }
        )
    return grid


def heatmap_month_labels(grid: list[dict]) -> dict[int, str]:
    """Column index to month label, one label per month change across ``grid``.

    The first column always carries the month it starts in. Keys come back in
    ascending column order.
    """
    if not grid:
        return {}
    labels = {0: month_label(grid[0]["day"])}
    previous = grid[0]["day"]
    for cell in grid[1:]:
        current = cell["day"]
        if current.month != previous.month:
            labels.setdefault(cell["col"], month_label(current))
        previous = current
    return dict(sorted(labels.items()))
