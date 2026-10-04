"""Calendar helpers and lenient user-facing date parsing.

Accepts ``today`` / ``t`` / ``yesterday`` / ``y`` / ISO ``YYYY-MM-DD`` with the
standard library alone. When the optional ``dateparser`` package is installed,
relative phrases such as ``last friday`` or ``2 days ago`` work too.

Weekday phrases (``friday``, ``last friday``, ``past tues``) are understood with
the standard library alone, so they behave the same whether or not ``dateparser``
is installed.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

ONE_DAY = timedelta(days=1)
ONE_WEEK = timedelta(weeks=1)

WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTH_NAMES = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)

_RELATIVE_TOKENS = {
    "": 0,
    "t": 0,
    "today": 0,
    "now": 0,
    "tonight": 0,
    "y": -1,
    "yest": -1,
    "yesterday": -1,
    "1d": -1,
}

try:
    import dateparser as _dateparser
except ImportError:
    _dateparser = None

HAS_DATEPARSER = _dateparser is not None

DATEPARSER_HINT = 'install the "dates" extra for phrases like "last friday"'


class DateParseError(ValueError):
    """Raised when a user-supplied date cannot be understood."""


def parse_date(
    text: str,
    *,
    today: date | None = None,
    allow_future: bool = False,
) -> date:
    """Turn free text into a :class:`datetime.date`.

    Raises :class:`DateParseError` for anything unrecognised, and for future
    dates unless ``allow_future`` is set.
    """
    cleaned = (text or "").strip()
    anchor = today or date.today()

    if cleaned.lower() in _RELATIVE_TOKENS:
        return anchor + timedelta(days=_RELATIVE_TOKENS[cleaned.lower()])

    try:
        parsed = date.fromisoformat(cleaned)
    except ValueError:
        parsed = _reject_impossible_iso(cleaned) or _parse_relative(cleaned, anchor)

    if not allow_future and parsed > anchor:
        raise DateParseError(f"{parsed.isoformat()} is in the future")
    return parsed


_ISO_SHAPE = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}$")


def _reject_impossible_iso(cleaned: str) -> None:
    """Fail loudly on a well-shaped but impossible ``YYYY-MM-DD`` date.

    ``dateparser`` rewrites inputs such as ``2026-13-01`` into a *different*
    valid date, which would quietly log a mark on the wrong day. Anything that
    already looks like an ISO date is therefore validated here, so the result
    never depends on whether the optional dependency is installed.
    """
    if not _ISO_SHAPE.match(cleaned):
        return
    raise DateParseError(f"{cleaned!r} is not a real date. Use today, yesterday or YYYY-MM-DD.")


_WEEKDAY_FULL = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

_WEEKDAY_INDEX: dict[str, int] = {}
for _position, _name in enumerate(_WEEKDAY_FULL):
    _WEEKDAY_INDEX[_name] = _position
    _WEEKDAY_INDEX[_name[:3]] = _position
_WEEKDAY_INDEX["tues"] = 1
_WEEKDAY_INDEX["thur"] = 3
_WEEKDAY_INDEX["thurs"] = 3

_BEFORE_WORDS = frozenset({"last", "past", "previous"})


def _parse_weekday(cleaned: str, anchor: date) -> date | None:
    """Resolve ``friday`` / ``last friday`` without any optional dependency.

    ``dateparser`` does not reliably understand ``last <weekday>``, and this
    phrase is common enough to deserve working identically everywhere.
    """
    tokens = cleaned.lower().replace(",", " ").replace("-", " ").split()
    strictly_before = bool(tokens) and tokens[0] in _BEFORE_WORDS
    if strictly_before:
        tokens = tokens[1:]
    if len(tokens) != 1:
        return None
    index = _WEEKDAY_INDEX.get(tokens[0])
    if index is None:
        return None
    back = (anchor.weekday() - index) % 7
    if back == 0 and strictly_before:
        back = 7
    return anchor - timedelta(days=back)


def _parse_relative(cleaned: str, anchor: date) -> date:
    native = _parse_weekday(cleaned, anchor)
    if native is not None:
        return native
    if _dateparser is not None:
        try:
            parsed = _dateparser.parse(
                cleaned,
                settings={
                    # dateparser requires a datetime here, not an ISO string.
                    "RELATIVE_BASE": datetime(anchor.year, anchor.month, anchor.day),
                    "RETURN_AS_TIMEZONE_AWARE": False,
                },
            )
        except Exception:  # a bad third-party guess must never crash the CLI
            parsed = None
        if parsed is not None:
            return parsed.date()

    hint = f" ({DATEPARSER_HINT})" if not HAS_DATEPARSER else ""
    raise DateParseError(f"Could not read {cleaned!r}. Use today, yesterday or YYYY-MM-DD{hint}.")


def accepted_formats() -> str:
    """Human-readable list of accepted inputs, for help text and error messages."""
    base = "today | yesterday | YYYY-MM-DD"
    return f"{base}, plus free-form dates" if HAS_DATEPARSER else base


def week_start(day: date) -> date:
    """Monday of the week containing ``day``."""
    return day - timedelta(days=day.weekday())


def week_days(day: date) -> list[date]:
    """The seven dates of the week containing ``day``, Monday first."""
    first = week_start(day)
    return [first + timedelta(days=offset) for offset in range(7)]


def month_days(day: date) -> list[date]:
    """Every date in the calendar month containing ``day``."""
    first = day.replace(day=1)
    if first.month == 12:
        following = first.replace(year=first.year + 1, month=1)
    else:
        following = first.replace(month=first.month + 1)
    return [first + timedelta(days=offset) for offset in range((following - first).days)]


def month_label(day: date) -> str:
    """Short month name for ``day``, blanked out once a year rolls over."""
    return MONTH_NAMES[day.month - 1]
