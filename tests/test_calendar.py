"""Tests for the shared month-grid model.

``ht month`` and the GUI calendar both render from this module, so these tests
are what keeps the two views from disagreeing.
"""

from __future__ import annotations

from datetime import date

import pytest

from habit_tracker import calendar as cal


def view(**sessions: str) -> dict:
    """A single-habit view, the shape both entry points pass in."""
    return {"goal": 5, "sessions": dict(sessions)}


def flat(weeks: list[list[cal.MonthCell]]) -> list[cal.MonthCell]:
    return [cell for week in weeks for cell in week]


class TestParseMonth:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("2026-03", date(2026, 3, 1)),
            ("2026-03-17", date(2026, 3, 1)),
            ("2026/03", date(2026, 3, 1)),
            ("2026/03/17", date(2026, 3, 1)),
            ("17-03-2026", date(2026, 3, 1)),
            ("17/03/2026", date(2026, 3, 1)),
            ("  2026-03  ", date(2026, 3, 1)),
        ],
    )
    def test_accepts_the_documented_formats(self, text, expected):
        assert cal.parse_month(text) == expected

    @pytest.mark.parametrize("text", ["", "March", "2026-13", "2026", "03-2026", "nope"])
    def test_nonsense_raises_value_error(self, text):
        """Callers report this as user error, so it must not be a traceback."""
        with pytest.raises(ValueError):
            cal.parse_month(text)

    def test_the_error_shows_the_expected_format(self):
        with pytest.raises(ValueError, match="YYYY-MM"):
            cal.parse_month("nope")


class TestMonthGrid:
    def test_every_week_has_seven_cells(self):
        weeks = cal.month_grid(date(2026, 3, 1), view(), today=date(2026, 3, 15))
        assert all(len(week) == 7 for week in weeks)

    def test_days_outside_the_month_are_padding(self):
        weeks = cal.month_grid(date(2026, 3, 1), view(), today=date(2026, 3, 15))
        # 2026-03-01 is a Sunday, so week one is six padding cells then the 1st.
        assert [cell.day for cell in weeks[0]] == [
            None,
            None,
            None,
            None,
            None,
            None,
            date(2026, 3, 1),
        ]
        assert all(cell.day is None for cell in weeks[-1][2:])

    def test_each_real_day_appears_exactly_once(self):
        weeks = cal.month_grid(date(2026, 3, 1), view(), today=date(2026, 3, 15))
        days = [cell.day for cell in flat(weeks) if cell.day is not None]
        assert len(days) == 31
        assert len(set(days)) == 31
        assert min(days) == date(2026, 3, 1)
        assert max(days) == date(2026, 3, 31)

    def test_weeks_start_on_monday(self):
        # June 2026 begins on a Monday, so its first week is all real days.
        weeks = cal.month_grid(date(2026, 6, 1), view(), today=date(2026, 6, 15))
        first = next(cell for cell in flat(weeks) if cell.day is not None)
        assert first.day == date(2026, 6, 1)
        assert first.day.weekday() == 0
        assert cal.MONTH_HEADER[first.day.weekday()] == "Mo"

    def test_every_day_lands_under_the_right_weekday_header(self):
        weeks = cal.month_grid(date(2026, 3, 1), view(), today=date(2026, 3, 15))
        for week in weeks:
            for column, cell in enumerate(week):
                if cell.day is not None:
                    assert cell.day.weekday() == column

    def test_marked_days_are_done_and_carry_their_note(self):
        weeks = cal.month_grid(
            date(2026, 3, 1), view(**{"2026-03-04": "shipped"}), today=date(2026, 3, 15)
        )
        done = [cell for cell in flat(weeks) if cell.done]
        assert [cell.day for cell in done] == [date(2026, 3, 4)]
        assert done[0].note == "shipped"

    def test_an_empty_note_still_counts_as_done(self):
        """Marking a day with no text is still showing up."""
        weeks = cal.month_grid(
            date(2026, 3, 1), view(**{"2026-03-04": ""}), today=date(2026, 3, 15)
        )
        assert [cell.day for cell in flat(weeks) if cell.done] == [date(2026, 3, 4)]

    def test_today_is_flagged(self):
        weeks = cal.month_grid(date(2026, 3, 1), view(), today=date(2026, 3, 15))
        today_cells = [cell for cell in flat(weeks) if cell.today]
        assert [cell.day for cell in today_cells] == [date(2026, 3, 15)]

    def test_days_after_today_are_future(self):
        weeks = cal.month_grid(date(2026, 3, 1), view(), today=date(2026, 3, 15))
        future = [cell.day for cell in flat(weeks) if cell.future]
        assert min(future) == date(2026, 3, 16)
        assert max(future) == date(2026, 3, 31)

    def test_days_from_other_months_are_ignored(self):
        weeks = cal.month_grid(
            date(2026, 3, 1),
            view(**{"2026-02-28": "no", "2026-04-01": "no"}),
            today=date(2026, 3, 15),
        )
        assert not any(cell.done for cell in flat(weeks))

    def test_a_malformed_session_key_does_not_break_the_grid(self):
        weeks = cal.month_grid(
            date(2026, 3, 1),
            view(**{"not-a-date": "oops", "2026-03-04": "ok"}),
            today=date(2026, 3, 15),
        )
        assert [cell.day for cell in flat(weeks) if cell.done] == [date(2026, 3, 4)]

    def test_leap_february_has_29_days(self):
        weeks = cal.month_grid(date(2024, 2, 1), view(), today=date(2024, 2, 29))
        days = [cell.day for cell in flat(weeks) if cell.day is not None]
        assert len(days) == 29

    def test_non_leap_february_has_28_days(self):
        weeks = cal.month_grid(date(2026, 2, 1), view(), today=date(2026, 2, 28))
        assert len([cell for cell in flat(weeks) if cell.day is not None]) == 28

    def test_today_defaults_to_the_real_current_date(self):
        """Omitting ``today`` is the common interactive path, so it must work."""
        today = date.today()
        cells = flat(cal.month_grid(date(today.year, today.month, 1), view()))
        assert any(cell.day == today and cell.today for cell in cells)
        assert any(cell.future for cell in cells)

    def test_a_view_without_sessions_is_all_missed(self):
        weeks = cal.month_grid(date(2026, 3, 1), {}, today=date(2026, 3, 15))
        assert not any(cell.done for cell in flat(weeks))


class TestMonthCellRendering:
    def cell(self, **kwargs) -> cal.MonthCell:
        return cal.MonthCell(**kwargs)

    def test_padding_renders_as_blanks(self):
        rendered = self.cell(day=None).render(width=5)
        assert rendered.strip() in {"", "."}

    def test_a_done_day_is_marked(self):
        assert self.cell(day=date(2026, 3, 4), done=True).render().lstrip().startswith("#")

    def test_a_missed_day_has_no_marker(self):
        assert "#" not in self.cell(day=date(2026, 3, 4), done=False).render()

    def test_a_future_day_is_marked(self):
        assert "." in self.cell(day=date(2026, 3, 4), future=True).render()
        assert "#" not in self.cell(day=date(2026, 3, 4), future=True).render()

    def test_label_is_the_day_number(self):
        assert self.cell(day=date(2026, 3, 4)).label.strip() == "4"

    def test_label_is_fixed_width_so_columns_line_up(self):
        labels = [self.cell(day=date(2026, 3, day)).label for day in (1, 4, 28, 31)]
        assert {len(label) for label in labels} == {2}

    def test_padding_has_a_blank_label(self):
        assert self.cell(day=None).label.strip() == ""

    def test_rendering_is_right_aligned_to_the_requested_width(self):
        assert len(self.cell(day=date(2026, 3, 4)).render(width=6)) == 6

    def test_marker_is_a_single_character(self):
        for cell in (
            self.cell(day=None),
            self.cell(day=date(2026, 3, 4), done=True),
            self.cell(day=date(2026, 3, 4)),
            self.cell(day=date(2026, 3, 4), future=True),
        ):
            assert len(cell.marker()) == 1


class TestMonthSummary:
    def test_only_elapsed_days_are_possible(self):
        summary = cal.month_summary(date(2026, 3, 1), view(), today=date(2026, 3, 10))
        assert summary.possible == 10
        assert summary.elapsed == 10

    def test_done_counts_marked_days(self):
        summary = cal.month_summary(
            date(2026, 3, 1),
            view(**{"2026-03-01": "a", "2026-03-02": "b"}),
            today=date(2026, 3, 10),
        )
        assert summary.done == 2
        assert summary.rate == pytest.approx(0.2)
        assert summary.percent == 20

    def test_future_marks_do_not_inflate_the_rate(self):
        """``--allow-future`` marks must not count until the day arrives."""
        summary = cal.month_summary(
            date(2026, 3, 1), view(**{"2026-03-20": "later"}), today=date(2026, 3, 10)
        )
        assert summary.done == 0
        assert summary.possible == 10
        assert summary.percent == 0

    def test_a_fully_elapsed_month_can_reach_one_hundred_percent(self):
        every_day = {f"2026-01-{day:02d}": "" for day in range(1, 32)}
        summary = cal.month_summary(date(2026, 1, 1), view(**every_day), today=date(2026, 2, 1))
        assert summary.possible == 31
        assert summary.done == 31
        assert summary.percent == 100

    def test_the_current_month_never_counts_days_that_have_not_happened(self):
        summary = cal.month_summary(date(2026, 3, 1), view(), today=date(2026, 3, 31))
        assert summary.possible == 31
        assert summary.future_days == 0

    def test_future_days_are_reported(self):
        summary = cal.month_summary(date(2026, 3, 1), view(), today=date(2026, 3, 10))
        assert summary.future_days == 21

    def test_a_month_with_nothing_possible_does_not_divide_by_zero(self):
        summary = cal.month_summary(date(2026, 3, 1), view(), today=date(2026, 2, 28))
        assert summary.possible == 0
        assert summary.rate == 0.0
        assert summary.percent == 0

    def test_best_day_is_the_longest_run(self):
        summary = cal.month_summary(
            date(2026, 3, 1),
            view(**{"2026-03-01": "", "2026-03-02": "", "2026-03-03": "", "2026-03-05": ""}),
            today=date(2026, 3, 31),
        )
        assert summary.best_day == 3

    def test_best_day_is_zero_with_no_marks(self):
        assert cal.month_summary(date(2026, 3, 1), view(), today=date(2026, 3, 31)).best_day == 0

    def test_a_run_is_broken_by_a_missed_day(self):
        summary = cal.month_summary(
            date(2026, 3, 1),
            view(**{"2026-03-01": "", "2026-03-03": "", "2026-03-04": ""}),
            today=date(2026, 3, 31),
        )
        assert summary.best_day == 2

    def test_has_data_reports_whether_anything_was_marked(self):
        assert (
            cal.month_summary(date(2026, 3, 1), view(), today=date(2026, 3, 31)).has_data is False
        )
        marked = cal.month_summary(
            date(2026, 3, 1), view(**{"2026-03-01": "x"}), today=date(2026, 3, 31)
        )
        assert marked.has_data is True

    def test_the_anchor_is_kept_for_the_heading(self):
        anchor = date(2026, 3, 1)
        assert cal.month_summary(anchor, view(), today=anchor).anchor == anchor
