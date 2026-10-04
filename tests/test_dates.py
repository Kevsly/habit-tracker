from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from habit_tracker import dates
from habit_tracker.dates import DateParseError

TODAY = date(2026, 3, 4)


class TestKeywords:
    @pytest.mark.parametrize("text", ["", "  ", "t", "T", "today", "Today", "TODAY", "now"])
    def test_today_aliases(self, text):
        assert dates.parse_date(text, today=TODAY) == TODAY

    @pytest.mark.parametrize("text", ["y", "yesterday", "Yesterday", " 1d "])
    def test_yesterday_aliases(self, text):
        assert dates.parse_date(text, today=TODAY) == date(2026, 3, 3)


class TestIso:
    def test_iso_string(self):
        assert dates.parse_date("2026-03-01", today=TODAY) == date(2026, 3, 1)

    def test_iso_with_surrounding_space(self):
        assert dates.parse_date("  2026-03-01 ", today=TODAY) == date(2026, 3, 1)

    def test_iso_leap_day(self):
        assert dates.parse_date("2024-02-29", today=TODAY) == date(2024, 2, 29)

    def test_non_leap_day_is_rejected(self):
        with pytest.raises(DateParseError):
            dates.parse_date("2026-02-29", today=TODAY)

    def test_impossible_month_is_rejected(self):
        with pytest.raises(DateParseError):
            dates.parse_date("2026-13-01", today=TODAY)

    @pytest.mark.parametrize("text", ["2026-13-01", "2026-00-10", "2026-04-31", "2026-1-1"])
    def test_an_impossible_iso_date_never_becomes_a_different_day(self, text):
        """dateparser would silently rewrite these; we must not.

        Guarded explicitly because the rewrite only happens when the optional
        dependency is installed, so the stdlib-only run would not catch it.
        """
        with pytest.raises(DateParseError):
            dates.parse_date(text, today=TODAY)

    def test_a_broken_dateparser_does_not_crash_the_cli(self, monkeypatch):
        """A third-party exception must surface as a clean DateParseError."""

        def explode(*args, **kwargs):
            raise RuntimeError("dateparser blew up")

        monkeypatch.setattr(dates, "_dateparser", SimpleNamespace(parse=explode))
        monkeypatch.setattr(dates, "HAS_DATEPARSER", True)
        # Only dateparser can resolve this one; the stdlib shortcuts do not apply.
        with pytest.raises(DateParseError):
            dates.parse_date("2 weeks ago", today=TODAY)

    @pytest.mark.skipif(not dates.HAS_DATEPARSER, reason="requires the dates extra")
    def test_relative_phrases_still_work(self):
        assert dates.parse_date("2 days ago", today=TODAY) == date(2026, 3, 2)


class TestWeekdayPhrases:
    """Weekday phrases are stdlib-only, so they work without the dates extra."""

    # 2026-03-04 is a Wednesday.
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("monday", date(2026, 3, 2)),
            ("mon", date(2026, 3, 2)),
            ("friday", date(2026, 2, 27)),
            ("last friday", date(2026, 2, 27)),
            ("past friday", date(2026, 2, 27)),
            ("last tues", date(2026, 3, 3)),
            ("last thursday", date(2026, 2, 26)),
            ("Last Friday", date(2026, 2, 27)),
            ("last fri", date(2026, 2, 27)),
        ],
    )
    def test_it_resolves(self, text, expected):
        assert dates.parse_date(text, today=TODAY) == expected

    def test_a_bare_weekday_can_mean_today(self):
        assert dates.parse_date("wednesday", today=TODAY) == TODAY

    def test_last_never_means_today(self):
        assert dates.parse_date("last wednesday", today=TODAY) == date(2026, 2, 25)

    @pytest.mark.parametrize("text", ["notaday", "lastday", "last friday and monday"])
    def test_non_weekdays_still_fail_cleanly(self, text):
        with pytest.raises(DateParseError):
            dates.parse_date(text, today=TODAY)


class TestFutureGuard:
    def test_future_date_is_rejected(self):
        with pytest.raises(DateParseError, match="in the future"):
            dates.parse_date("2026-03-05", today=TODAY)

    def test_future_date_allowed_when_requested(self):
        assert dates.parse_date("2026-03-05", today=TODAY, allow_future=True) == date(2026, 3, 5)

    def test_today_is_not_the_future(self):
        assert dates.parse_date("today", today=TODAY) == TODAY


class TestErrors:
    def test_nonsense_is_rejected(self):
        with pytest.raises(DateParseError):
            dates.parse_date("purple monkey", today=TODAY)

    def test_error_mentions_the_accepted_formats(self):
        with pytest.raises(DateParseError) as excinfo:
            dates.parse_date("purple monkey", today=TODAY)
        assert "YYYY-MM-DD" in str(excinfo.value)

    def test_none_input_behaves_like_empty_input(self):
        assert dates.parse_date(None, today=TODAY) == TODAY


class TestCalendarHelpers:
    def test_week_start_on_a_monday(self):
        assert dates.week_start(date(2026, 3, 4)) == date(2026, 3, 2)

    def test_week_start_of_a_monday_is_itself(self):
        assert dates.week_start(date(2026, 3, 2)) == date(2026, 3, 2)

    def test_week_start_of_a_sunday_looks_back(self):
        assert dates.week_start(date(2026, 3, 8)) == date(2026, 3, 2)

    def test_week_days_are_seven_consecutive(self):
        days = dates.week_days(date(2026, 3, 4))
        assert len(days) == 7
        assert days[0] == date(2026, 3, 2)
        assert days[-1] == date(2026, 3, 8)

    def test_month_days_for_a_30_day_month(self):
        assert len(dates.month_days(date(2026, 4, 15))) == 30

    def test_month_days_for_february_in_a_leap_year(self):
        assert len(dates.month_days(date(2028, 2, 15))) == 29

    def test_month_days_for_december_rolls_the_year(self):
        days = dates.month_days(date(2026, 12, 31))
        assert len(days) == 31
        assert days[-1] == date(2026, 12, 31)

    @pytest.mark.parametrize(
        ("day", "label"),
        [(date(2026, 1, 1), "Jan"), (date(2026, 12, 25), "Dec")],
    )
    def test_month_label(self, day, label):
        assert dates.month_label(day) == label


class TestAcceptedFormats:
    def test_includes_iso_when_dateparser_is_absent(self):
        text = dates.accepted_formats()
        assert "YYYY-MM-DD" in text

    def test_is_a_string_always(self):
        assert isinstance(dates.accepted_formats(), str)
