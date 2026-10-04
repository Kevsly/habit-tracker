from __future__ import annotations

from datetime import date, timedelta

import pytest

from habit_tracker import tracker


@pytest.fixture
def data() -> dict:
    return {"goal": 5, "sessions": {}}


def marked(days: list[str], goal: int = 5) -> dict:
    return {"goal": goal, "sessions": dict.fromkeys(days, "")}


class TestSessions:
    def test_mark_and_read_back(self, data):
        tracker.mark_session(data, date(2026, 3, 1), "wrote tests")
        assert tracker.has_session(data, date(2026, 3, 1)) is True
        assert tracker.note_for(data, date(2026, 3, 1)) == "wrote tests"

    def test_mark_without_note_defaults_to_empty(self, data):
        tracker.mark_session(data, date(2026, 3, 1))
        assert tracker.note_for(data, date(2026, 3, 1)) == ""

    def test_re_marking_replaces_the_note(self, data):
        day = date(2026, 3, 1)
        tracker.mark_session(data, day, "first")
        tracker.mark_session(data, day, "second")
        assert tracker.note_for(data, day) == "second"
        assert tracker.total_sessions(data) == 1

    def test_clear_reports_whether_anything_was_there(self, data):
        day = date(2026, 3, 1)
        assert tracker.clear_session(data, day) is False
        tracker.mark_session(data, day, "note")
        assert tracker.clear_session(data, day) is True
        assert tracker.has_session(data, day) is False

    def test_missing_note_is_empty_string(self, data):
        assert tracker.note_for(data, date(2026, 3, 1)) == ""

    def test_malformed_session_keys_are_ignored(self):
        data = {"goal": 5, "sessions": {"not-a-date": "x", "2026-03-01": "ok"}}
        assert tracker.total_sessions(data) == 1
        assert tracker.session_days(data) == [date(2026, 3, 1)]


class TestWeekProgress:
    def test_counts_only_marked_days(self, data):
        week = date(2026, 3, 2)
        tracker.mark_session(data, date(2026, 3, 3))
        tracker.mark_session(data, date(2026, 3, 4))
        assert tracker.week_progress(data, week) == (2, 5)

    def test_future_days_do_not_count_towards_the_goal(self):
        """Regression: pre-marking the future used to inflate weekly progress."""
        today = date(2026, 3, 4)
        data = marked(["2026-03-02", "2026-03-03", "2026-03-05", "2026-03-06"], goal=4)
        assert tracker.week_progress(data, today, today) == (2, 4)

    def test_sunday_of_a_partial_week_is_still_excluded(self):
        today = date(2026, 3, 4)
        data = marked(["2026-03-08"])
        assert tracker.week_progress(data, today, today)[0] == 0

    def test_goal_is_never_negative(self):
        data = marked([], goal=-3)
        assert tracker.week_progress(data, date(2026, 3, 2))[1] == 0

    def test_missing_goal_key_is_treated_as_zero(self):
        data = {"sessions": {"2026-03-03": ""}}
        assert tracker.week_progress(data, date(2026, 3, 2)) == (1, 0)


class TestWeekRows:
    def test_rows_are_monday_first_and_seven_long(self, data):
        rows = tracker.week_rows(data, date(2026, 3, 4))
        assert len(rows) == 7
        assert [row["label"] for row in rows] == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        assert rows[0]["day"] == date(2026, 3, 2)

    def test_future_flag_marks_days_after_today(self, data):
        today = date(2026, 3, 4)
        rows = tracker.week_rows(data, today, today)
        assert [row["future"] for row in rows] == [False, False, False, True, True, True, True]


class TestStreaks:
    def test_consecutive_days_ending_today(self, data):
        today = date(2026, 3, 10)
        for offset in range(3):
            tracker.mark_session(data, today - timedelta(days=offset))
        assert tracker.current_streak(data, today) == 3

    def test_streak_still_counts_when_today_is_unmarked(self, data):
        today = date(2026, 3, 10)
        tracker.mark_session(data, today - timedelta(days=1))
        tracker.mark_session(data, today - timedelta(days=2))
        assert tracker.current_streak(data, today) == 2

    def test_gap_ends_the_streak(self, data):
        today = date(2026, 3, 10)
        tracker.mark_session(data, today)
        tracker.mark_session(data, today - timedelta(days=2))
        assert tracker.current_streak(data, today) == 1

    def test_empty_data_has_no_streak(self, data):
        assert tracker.current_streak(data, date(2026, 3, 10)) == 0

    def test_longest_streak_spans_the_whole_history(self):
        data = marked(["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-10", "2026-01-11"])
        assert tracker.longest_streak(data) == 3

    def test_longest_streak_of_a_single_day(self):
        assert tracker.longest_streak(marked(["2026-01-01"])) == 1

    def test_longest_streak_of_empty_data(self, data):
        assert tracker.longest_streak(data) == 0


class TestBusiestWeekday:
    def test_counts_per_weekday(self):
        data = marked(["2026-03-02", "2026-03-03", "2026-03-09"])
        assert tracker.busiest_weekday(data) == ("Mon", 2)

    def test_no_data_reports_no_winner(self, data):
        """Regression: this used to report 'Mon (0)' instead of admitting no data."""
        assert tracker.busiest_weekday(data) == (None, 0)

    def test_a_single_session_is_the_busiest_day(self):
        assert tracker.busiest_weekday(marked(["2026-03-04"])) == ("Wed", 1)


class TestHeatmap:
    def test_grid_starts_on_a_monday(self, data):
        grid = tracker.heatmap_grid(data, end=date(2026, 3, 11), weeks=4)
        assert grid[0]["day"].weekday() == 0
        assert grid[0]["day"] == date(2026, 2, 16)

    def test_grid_has_one_column_per_week(self, data):
        grid = tracker.heatmap_grid(data, end=date(2026, 3, 11), weeks=4)
        assert len(grid) == 28
        assert sorted({cell["col"] for cell in grid}) == [0, 1, 2, 3]

    def test_every_column_is_a_monday_to_sunday_block(self, data):
        """Regression: the old grid started on an arbitrary weekday, so columns
        were not calendar weeks at all."""
        grid = tracker.heatmap_grid(data, end=date(2026, 3, 11), weeks=4)
        for col in range(4):
            days = [cell["day"] for cell in grid if cell["col"] == col]
            assert days[0].weekday() == 0
            assert days[-1].weekday() == 6
            assert days == sorted(days)

    def test_rows_follow_the_weekday(self, data):
        grid = tracker.heatmap_grid(data, end=date(2026, 3, 11), weeks=2)
        assert [cell["row"] for cell in grid[:7]] == [0, 1, 2, 3, 4, 5, 6]

    def test_last_column_contains_the_end_date(self, data):
        grid = tracker.heatmap_grid(data, end=date(2026, 3, 11), weeks=4)
        assert date(2026, 3, 11) in [cell["day"] for cell in grid]

    def test_statuses_reflect_the_data(self):
        today = date(2026, 3, 11)
        data = marked(["2026-03-11", "2026-03-10"])
        grid = tracker.heatmap_grid(data, end=today, weeks=2, today=today)
        statuses = {cell["day"]: cell["status"] for cell in grid}
        assert statuses[today] == tracker.DONE
        assert statuses[today - timedelta(days=1)] == tracker.DONE
        assert statuses[today - timedelta(days=2)] == tracker.MISS

    def test_days_after_today_are_future(self):
        today = date(2026, 3, 11)
        grid = tracker.heatmap_grid({}, end=today, weeks=2, today=today)
        assert any(cell["status"] == tracker.FUTURE for cell in grid)

    def test_month_labels_appear_once_per_month_change(self):
        grid = tracker.heatmap_grid({}, end=date(2026, 3, 11), weeks=12)
        labels = tracker.heatmap_month_labels(grid)
        assert labels[0] == "Dec"
        assert "Jan" in labels.values()
        assert "Feb" in labels.values()
        assert list(labels) == sorted(labels)


class TestDayStatus:
    def test_marked_day(self, data):
        day = date(2026, 3, 1)
        tracker.mark_session(data, day)
        assert tracker.day_status(data, day, day) == tracker.DONE

    def test_unmarked_past_day(self, data):
        assert tracker.day_status(data, date(2026, 3, 1), date(2026, 3, 5)) == tracker.MISS

    def test_day_after_today_is_future(self, data):
        assert tracker.day_status(data, date(2026, 3, 6), date(2026, 3, 5)) == tracker.FUTURE


class TestRangesAndRates:
    def test_sessions_in_range_filters_inclusively(self):
        data = marked(["2026-02-27", "2026-03-01", "2026-03-02", "2026-03-03"])
        found = tracker.sessions_in_range(data, date(2026, 3, 1), date(2026, 3, 2))
        assert found == [date(2026, 3, 1), date(2026, 3, 2)]

    def test_completion_rate_of_a_fully_marked_past_range(self):
        data = marked(["2026-03-01", "2026-03-02", "2026-03-03"])
        rate = tracker.completion_rate(data, date(2026, 3, 1), date(2026, 3, 3))
        assert rate == 1.0

    def test_completion_rate_of_a_half_marked_range(self):
        data = marked(["2026-03-01"])
        rate = tracker.completion_rate(data, date(2026, 3, 1), date(2026, 3, 2))
        assert rate == 0.5

    def test_completion_rate_ignores_future_days(self):
        data = marked(["2026-03-01"])
        rate = tracker.completion_rate(
            data, date(2026, 3, 1), date(2026, 3, 5), today=date(2026, 3, 1)
        )
        assert rate == 1.0

    def test_month_totals_group_by_day_of_month(self):
        data = marked(["2026-03-01", "2026-03-01", "2026-03-15"])
        totals = tracker.month_totals(data, date(2026, 3, 20))
        assert totals == {1: 1, 15: 1}

    def test_month_totals_across_a_year_boundary(self):
        data = marked(["2025-12-30", "2026-01-02"])
        totals = tracker.month_totals(data, date(2026, 1, 10))
        assert totals == {2: 1}
