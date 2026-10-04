"""End-to-end tests for the argparse interface."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from habit_tracker import calendar as month_calendar
from habit_tracker import cli, config, notify, state, storage


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(config.ENV_DATA_DIR, str(tmp_path))
    return tmp_path


def invoke(data_dir, *argv):
    return cli.main(["--data-dir", str(data_dir), *argv])


def load(data_dir) -> dict:
    return storage.load_data(data_dir / "data.json")


def sessions(data_dir, habit=None) -> dict:
    """Sessions for one habit, so assertions read the same as the v1 shape."""
    return state.sessions_of(load(data_dir), habit)


def goal(data_dir, habit=None) -> int:
    return state.goal_of(load(data_dir), habit)


def payload(capsys) -> dict:
    """The first top-level JSON object written to stdout.

    JSON mode pretty-prints across several lines and earlier commands in the
    same test may have written human text, so scan for the outermost parseable
    object. Nested objects always start *inside* it, so the first match wins.
    """
    out = capsys.readouterr().out
    decoder = json.JSONDecoder()
    for index, char in enumerate(out):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(out, index)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise AssertionError(f"no JSON object found in output: {out!r}")


def previous_month() -> date:
    """First day of the month before now: always fully in the past."""
    today = date.today()
    index = today.year * 12 + (today.month - 1) - 1
    return date(index // 12, index % 12 + 1, 1)


class TestMark:
    def test_marks_today_with_a_note(self, data_dir):
        assert invoke(data_dir, "mark", "2026-03-01", "-n", "wrote tests") == 0
        assert sessions(data_dir) == {"2026-03-01": "wrote tests"}

    def test_marks_a_note_free_session(self, data_dir):
        assert invoke(data_dir, "mark", "2026-03-01") == 0
        assert sessions(data_dir) == {"2026-03-01": ""}

    def test_adding_tags_from_the_command_line(self, data_dir):
        invoke(data_dir, "mark", "2026-03-01", "-n", "work", "--tag", "python, docs")
        assert sessions(data_dir)["2026-03-01"] == "work #python #docs"

    def test_rejects_a_future_date(self, data_dir, capsys):
        assert invoke(data_dir, "mark", "2099-01-01") == 2
        assert sessions(data_dir) == {}
        assert "future" in capsys.readouterr().err

    def test_allow_future_permits_it(self, data_dir):
        assert invoke(data_dir, "mark", "2099-01-01", "--allow-future") == 0
        assert "2099-01-01" in sessions(data_dir)

    def test_rejects_nonsense_dates(self, data_dir, capsys):
        assert invoke(data_dir, "mark", "purple monkey") == 2
        assert "Could not read" in capsys.readouterr().err

    def test_rejects_an_impossible_date(self, data_dir):
        assert invoke(data_dir, "mark", "2026-02-30") == 2

    def test_reports_json_when_asked(self, data_dir, capsys):
        invoke(data_dir, "--json", "mark", "2026-03-01", "-n", "note")
        assert payload(capsys) == {
            "ok": True,
            "habit": "coding",
            "habit_name": "Coding",
            "day": "2026-03-01",
            "note": "note",
            "replaced": None,
        }

    def test_marking_mentions_that_it_can_be_undone(self, data_dir, capsys):
        invoke(data_dir, "mark", "2026-03-01")
        assert "ht undo" in capsys.readouterr().out


class TestUnmark:
    def test_clears_an_existing_session(self, data_dir):
        invoke(data_dir, "mark", "2026-03-01")
        assert invoke(data_dir, "unmark", "2026-03-01", "--yes") == 0
        assert sessions(data_dir) == {}

    def test_clearing_an_unmarked_day_reports_failure(self, data_dir, capsys):
        assert invoke(data_dir, "unmark", "2026-03-01", "--yes") == 1
        assert "Nothing was marked" in capsys.readouterr().out

    def test_without_yes_and_no_tty_it_declines(self, data_dir):
        invoke(data_dir, "mark", "2026-03-01")
        assert invoke(data_dir, "unmark", "2026-03-01") == 1
        assert "2026-03-01" in sessions(data_dir)


class TestUndo:
    def test_undo_reverses_a_mark(self, data_dir, capsys):
        invoke(data_dir, "mark", "2026-03-01", "-n", "oops")
        assert invoke(data_dir, "undo") == 0
        assert sessions(data_dir) == {}
        assert "Undone" in capsys.readouterr().out

    def test_undo_reverses_an_unmark(self, data_dir):
        invoke(data_dir, "mark", "2026-03-01", "-n", "keep me")
        invoke(data_dir, "unmark", "2026-03-01", "--yes")
        assert sessions(data_dir) == {}
        invoke(data_dir, "undo")
        assert sessions(data_dir) == {"2026-03-01": "keep me"}

    def test_undo_walks_back_through_several_changes(self, data_dir):
        invoke(data_dir, "mark", "2026-03-01", "-n", "first")
        invoke(data_dir, "mark", "2026-03-02", "-n", "second")
        invoke(data_dir, "undo")
        invoke(data_dir, "undo")
        assert sessions(data_dir) == {}

    def test_undo_with_nothing_to_undo_reports_failure(self, data_dir, capsys):
        assert invoke(data_dir, "undo") == 1
        assert "Nothing to undo" in capsys.readouterr().out

    def test_undo_reverses_a_goal_change(self, data_dir):
        invoke(data_dir, "goal", "7")
        invoke(data_dir, "undo")
        assert goal(data_dir) == 5

    def test_undo_reports_how_many_steps_remain(self, data_dir, capsys):
        invoke(data_dir, "mark", "2026-03-01")
        invoke(data_dir, "mark", "2026-03-02")
        invoke(data_dir, "--json", "undo")
        body = payload(capsys)
        assert body["ok"] is True
        assert body["undo_available"] is True

    def test_undo_survives_a_restart(self, data_dir):
        """Two marks mean two undo steps, so two undos return to empty."""
        invoke(data_dir, "mark", "2026-03-01")
        invoke(data_dir, "mark", "2026-03-02")
        invoke(data_dir, "undo")
        assert sessions(data_dir) == {"2026-03-01": ""}
        assert invoke(data_dir, "undo") == 0
        assert sessions(data_dir) == {}


class TestHistory:
    def test_history_is_empty_at_first(self, data_dir, capsys):
        invoke(data_dir, "--json", "history")
        body = payload(capsys)
        assert body["steps"] == []
        assert body["undo_available"] is False

    def test_a_mark_is_recorded_as_a_labelled_step(self, data_dir, capsys):
        invoke(data_dir, "mark", "2026-03-01")
        invoke(data_dir, "--json", "history")
        steps = payload(capsys)["steps"]
        assert len(steps) == 1
        assert steps[0]["action"] == "mark 2026-03-01"
        assert steps[0]["at"]

    def test_newest_step_comes_first(self, data_dir, capsys):
        invoke(data_dir, "mark", "2026-03-01")
        invoke(data_dir, "habit", "add", "Reading")
        invoke(data_dir, "--json", "history")
        actions = [step["action"] for step in payload(capsys)["steps"]]
        assert actions[0] == "add habit Reading"
        assert actions[-1] == "mark 2026-03-01"

    def test_habit_changes_are_labelled_too(self, data_dir, capsys):
        invoke(data_dir, "habit", "add", "Reading")
        invoke(data_dir, "habit", "use", "reading")
        invoke(data_dir, "habit", "rename", "Reading now")
        invoke(data_dir, "--json", "history")
        actions = [step["action"] for step in payload(capsys)["steps"]]
        assert actions[:3] == [
            "rename habit to Reading now",
            "switch to reading",
            "add habit Reading",
        ]

    def test_goal_changes_are_labelled(self, data_dir, capsys):
        invoke(data_dir, "goal", "9")
        invoke(data_dir, "--json", "history")
        assert payload(capsys)["steps"][0]["action"] == "set goal"

    def test_unmark_is_labelled_as_a_clear(self, data_dir, capsys):
        invoke(data_dir, "mark", "2026-03-01")
        invoke(data_dir, "unmark", "2026-03-01", "--yes")
        invoke(data_dir, "--json", "history")
        assert payload(capsys)["steps"][0]["action"] == "clear 2026-03-01"

    def test_undo_consumes_the_step(self, data_dir, capsys):
        invoke(data_dir, "mark", "2026-03-01")
        invoke(data_dir, "undo")
        invoke(data_dir, "--json", "history")
        assert payload(capsys)["steps"] == []

    def test_the_table_renders(self, data_dir, capsys):
        invoke(data_dir, "mark", "2026-03-01", "-n", "#work")
        invoke(data_dir, "history")
        out = capsys.readouterr().out
        assert "Undo history" in out
        assert "mark 2026-03-01" in out
        assert "ht undo" in out

    def test_an_empty_history_says_so(self, data_dir, capsys):
        invoke(data_dir, "history")
        assert "No changes recorded yet." in capsys.readouterr().out

    def test_the_step_counts_match_the_snapshot(self, data_dir, capsys):
        invoke(data_dir, "mark", "2026-03-01")
        invoke(data_dir, "mark", "2026-03-02")
        invoke(data_dir, "--json", "history")
        steps = payload(capsys)["steps"]
        # The newest step was recorded before the second mark, so one session.
        assert [step["sessions"] for step in steps] == [1, 0]

    def test_history_survives_a_restart(self, data_dir, capsys):
        invoke(data_dir, "mark", "2026-03-01")
        invoke(data_dir, "--json", "history")
        steps = payload(capsys)["steps"]
        assert steps[0]["action"] == "mark 2026-03-01"


class TestHabits:
    def test_a_fresh_store_has_one_default_habit(self, data_dir, capsys):
        invoke(data_dir, "--json", "habit", "list")
        body = payload(capsys)
        assert [h["id"] for h in body["habits"]] == ["coding"]
        assert body["active"] == "coding"

    def test_adding_a_habit(self, data_dir, capsys):
        assert invoke(data_dir, "--json", "habit", "add", "Morning Run", "--goal", "3") == 0
        body = payload(capsys)
        assert body["id"] == "morning-run"
        assert body["goal"] == 3

    def test_adding_creates_a_separate_empty_habit(self, data_dir):
        invoke(data_dir, "mark", "2026-03-01", "-n", "coding day")
        invoke(data_dir, "habit", "add", "Read", "--goal", "7")
        assert sessions(data_dir) == {"2026-03-01": "coding day"}
        assert sessions(data_dir, "read") == {}
        assert goal(data_dir, "read") == 7

    def test_activate_switches_the_default(self, data_dir, capsys):
        invoke(data_dir, "habit", "add", "Read", "--activate")
        invoke(data_dir, "--json", "habit", "list")
        assert payload(capsys)["active"] == "read"

    def test_use_switches_by_name_or_id(self, data_dir, capsys):
        invoke(data_dir, "habit", "add", "Morning Run")
        assert invoke(data_dir, "--json", "habit", "use", "morning-run") == 0
        assert payload(capsys)["habit"] == "morning-run"

    def test_use_rejects_an_unknown_habit(self, data_dir, capsys):
        assert invoke(data_dir, "habit", "use", "nope") == 2
        assert "Unknown habit" in capsys.readouterr().err

    def test_rename_keeps_the_identifier(self, data_dir):
        invoke(data_dir, "mark", "2026-03-01", "-n", "note")
        invoke(data_dir, "habit", "add", "Read")
        assert invoke(data_dir, "habit", "rename", "Deep Work") == 0
        doc = load(data_dir)
        assert doc["habits"]["coding"]["name"] == "Deep Work"
        assert sessions(data_dir) == {"2026-03-01": "note"}

    def test_removing_deletes_sessions_and_rehomes_active(self, data_dir):
        invoke(data_dir, "habit", "add", "Read")
        invoke(data_dir, "mark", "2026-03-01", "-n", "read a book", "--habit", "read")
        assert invoke(data_dir, "habit", "rm", "Read", "--force") == 0
        assert "read" not in load(data_dir)["habits"]
        assert "read" not in load(data_dir)["sessions"]

    def test_removing_asks_for_confirmation_first(self, data_dir, capsys):
        """Deleting a habit destroys its sessions, so it must not be silent."""
        invoke(data_dir, "habit", "add", "Read")
        assert invoke(data_dir, "habit", "rm", "Read") == 1
        assert "Cancelled" in capsys.readouterr().out
        assert "read" in load(data_dir)["habits"]

    def test_force_skips_the_confirmation(self, data_dir):
        invoke(data_dir, "habit", "add", "Read")
        assert invoke(data_dir, "habit", "rm", "Read", "-f") == 0
        assert "read" not in load(data_dir)["habits"]

    def test_an_unknown_habit_fails_before_the_prompt(self, data_dir, capsys):
        assert invoke(data_dir, "habit", "rm", "nope", "--force") == 2
        assert "Unknown habit" in capsys.readouterr().err

    def test_removing_the_only_habit_is_refused(self, data_dir, capsys):
        assert invoke(data_dir, "habit", "rm", "coding", "--force") == 2
        assert "only habit" in capsys.readouterr().err

    def test_a_removal_can_be_undone(self, data_dir):
        invoke(data_dir, "habit", "add", "Read")
        invoke(data_dir, "habit", "rm", "Read", "--force")
        assert invoke(data_dir, "undo") == 0
        assert "read" in load(data_dir)["habits"]

    def test_habit_list_marks_the_active_row(self, data_dir, capsys):
        invoke(data_dir, "habit", "add", "Read")
        invoke(data_dir, "habit", "list")
        out = capsys.readouterr().out
        active_line = next(line for line in out.splitlines() if "Coding" in line)
        assert active_line.strip().startswith("*")
        read_line = next(line for line in out.splitlines() if "Read" in line)
        assert not read_line.strip().startswith("*")

    def test_habit_requires_an_action(self, data_dir):
        with pytest.raises(SystemExit):
            invoke(data_dir, "habit")


class TestHabitFlag:
    def test_mark_can_target_another_habit(self, data_dir):
        invoke(data_dir, "habit", "add", "Read")
        invoke(data_dir, "mark", "2026-03-01", "-n", "chapter", "--habit", "read")
        assert sessions(data_dir) == {}
        assert sessions(data_dir, "read") == {"2026-03-01": "chapter"}

    def test_the_flag_accepts_a_display_name(self, data_dir):
        invoke(data_dir, "habit", "add", "Morning Run")
        invoke(data_dir, "mark", "2026-03-01", "--habit", "Morning Run")
        assert sessions(data_dir, "morning-run") == {"2026-03-01": ""}

    def test_a_mistyped_habit_fails_loudly(self, data_dir, capsys):
        invoke(data_dir, "mark", "2026-03-01", "-n", "note", "--habit", "raed")
        assert "Unknown habit" in capsys.readouterr().err
        assert invoke(data_dir, "mark", "2026-03-02", "--habit", "raed") == 2

    def test_a_mistyped_habit_never_writes_to_the_active_one(self, data_dir):
        invoke(data_dir, "habit", "add", "Read")
        invoke(data_dir, "mark", "2026-03-05", "-n", "should not land", "--habit", "raed")
        assert sessions(data_dir) == {}
        assert sessions(data_dir, "read") == {}

    def test_goal_can_target_another_habit(self, data_dir):
        invoke(data_dir, "habit", "add", "Read")
        invoke(data_dir, "goal", "9", "--habit", "read")
        assert goal(data_dir) == 5
        assert goal(data_dir, "read") == 9

    def test_stats_reports_both_totals(self, data_dir, capsys):
        invoke(data_dir, "mark", "2026-03-01", "-n", "a")
        invoke(data_dir, "habit", "add", "Read")
        invoke(data_dir, "mark", "2026-03-02", "-n", "b", "--habit", "read")
        invoke(data_dir, "--json", "stats")
        body = payload(capsys)
        assert body["total_sessions"] == 1
        assert body["all_habits_sessions"] == 2


class TestWeek:
    def test_shows_the_current_week(self, data_dir, capsys):
        invoke(data_dir, "mark", "today")
        invoke(data_dir, "week")
        out = capsys.readouterr().out
        assert "Week of" in out
        assert "Goal reached" not in out

    def test_reaches_the_goal(self, data_dir, capsys):
        invoke(data_dir, "goal", "1")
        invoke(data_dir, "mark", "today")
        invoke(data_dir, "week")
        assert "Goal reached" in capsys.readouterr().out

    def test_json_output_lists_each_day(self, data_dir, capsys):
        capsys.readouterr()
        invoke(data_dir, "--json", "week")
        body = payload(capsys)
        assert len(body["days"]) == 7
        assert body["goal"] == 5

    def test_a_past_week_can_be_requested(self, data_dir, capsys):
        capsys.readouterr()
        invoke(data_dir, "--json", "week", "--week-of", "2026-01-07")
        assert payload(capsys)["week_of"] == "2026-01-05"

    def test_future_days_do_not_count(self, data_dir, capsys):
        future = date.today() + timedelta(days=30)
        invoke(data_dir, "goal", "3")
        invoke(data_dir, "mark", future.isoformat(), "--allow-future", "-n", "planned")
        capsys.readouterr()
        invoke(data_dir, "--json", "week", "--week-of", future.isoformat())
        body = payload(capsys)
        assert any(day["future"] and day["done"] for day in body["days"])
        assert body["done"] == 0

    def test_the_habit_name_appears_in_the_heading(self, data_dir, capsys):
        invoke(data_dir, "habit", "add", "Read")
        invoke(data_dir, "--json", "week", "--habit", "read")
        assert payload(capsys)["habit"] == "read"


class TestMonth:
    def test_defaults_to_the_current_month(self, data_dir, capsys):
        invoke(data_dir, "--json", "month")
        assert payload(capsys)["month"] == date.today().strftime("%Y-%m")

    def test_a_named_month_is_shown(self, data_dir, capsys):
        assert invoke(data_dir, "--json", "month", "--month", "2026-03") == 0
        assert payload(capsys)["month"] == "2026-03"

    def test_a_bad_month_is_reported(self, data_dir, capsys):
        assert invoke(data_dir, "month", "--month", "banana") == 2
        assert "Could not read" in capsys.readouterr().err

    def test_grid_is_seven_columns(self, data_dir, capsys):
        invoke(data_dir, "--json", "month", "--month", "2026-03")
        for week in payload(capsys)["weeks"]:
            assert len(week) == 7

    def test_marked_days_are_flagged(self, data_dir, capsys):
        invoke(data_dir, "mark", "2026-03-04", "-n", "shipped")
        invoke(data_dir, "--json", "month", "--month", "2026-03")
        body = payload(capsys)
        marked = [cell for week in body["weeks"] for cell in week if cell["done"]]
        assert [cell["date"] for cell in marked] == ["2026-03-04"]
        assert marked[0]["note"] == "shipped"

    def test_completion_is_measured_over_elapsed_days_only(self, data_dir, capsys):
        anchor = previous_month()
        invoke(data_dir, "mark", anchor.isoformat(), "-n", "one")
        invoke(data_dir, "--json", "month", "--month", anchor.strftime("%Y-%m"))
        body = payload(capsys)
        assert body["done"] == 1
        assert body["possible"] > 1
        assert 0 < body["completion_rate"] < 1

    def test_a_fully_elapsed_month_with_one_day_is_100_percent(self, data_dir, capsys):
        anchor = previous_month()
        # Mark every day of the previous month so it reads as complete.
        days = month_calendar.month_grid(anchor, {}, today=date.today())
        for week in days:
            for cell in week:
                if cell.day is not None:
                    invoke(data_dir, "mark", cell.day.isoformat(), "--allow-future")
        invoke(data_dir, "--json", "month", "--month", anchor.strftime("%Y-%m"))
        body = payload(capsys)
        assert body["completion_rate"] == 1.0

    def test_text_output_renders_a_header_and_percentage(self, data_dir, capsys):
        anchor = previous_month()
        invoke(data_dir, "mark", anchor.isoformat())
        assert invoke(data_dir, "month", "--month", anchor.strftime("%Y-%m")) == 0
        out = capsys.readouterr().out
        assert "Mo" in out and "Su" in out
        assert "%" in out

    def test_future_days_are_excluded_from_the_total(self, data_dir, capsys):
        """A month shown on the 4th must not read as mostly missed."""
        now = date.today()
        invoke(data_dir, "--json", "month", "--month", now.strftime("%Y-%m"))
        body = payload(capsys)
        assert body["possible"] == now.day
        assert body["possible"] < 31


class TestStatsAndTags:
    def test_stats_json(self, data_dir, capsys):
        invoke(data_dir, "mark", "2026-03-01")
        capsys.readouterr()
        invoke(data_dir, "--json", "stats")
        body = payload(capsys)
        assert body["total_sessions"] == 1
        assert body["longest_streak"] == 1

    def test_stats_of_an_empty_store_report_no_busiest_day(self, data_dir, capsys):
        capsys.readouterr()
        invoke(data_dir, "--json", "stats")
        assert payload(capsys)["busiest_weekday"] is None

    def test_tags_json_is_ranked(self, data_dir, capsys):
        invoke(data_dir, "mark", "2026-03-01", "-n", "#python #rust")
        invoke(data_dir, "mark", "2026-03-02", "-n", "#python")
        capsys.readouterr()
        invoke(data_dir, "--json", "tags")
        assert payload(capsys)["tags"] == [
            {"tag": "python", "count": 2},
            {"tag": "rust", "count": 1},
        ]

    def test_tags_says_so_when_there_are_none(self, data_dir, capsys):
        invoke(data_dir, "tags")
        assert "No tags yet" in capsys.readouterr().out

    def test_tags_default_to_the_active_habit(self, data_dir, capsys):
        invoke(data_dir, "habit", "add", "Read")
        invoke(data_dir, "mark", "2026-03-01", "-n", "#coding")
        invoke(data_dir, "mark", "2026-03-02", "-n", "#reading", "--habit", "read")
        capsys.readouterr()
        invoke(data_dir, "--json", "tags")
        assert [t["tag"] for t in payload(capsys)["tags"]] == ["coding"]

    def test_tags_all_merges_every_habit(self, data_dir, capsys):
        invoke(data_dir, "habit", "add", "Read")
        invoke(data_dir, "mark", "2026-03-01", "-n", "#coding")
        invoke(data_dir, "mark", "2026-03-02", "-n", "#reading #coding", "--habit", "read")
        capsys.readouterr()
        invoke(data_dir, "--json", "tags", "--all")
        assert payload(capsys)["tags"] == [
            {"tag": "coding", "count": 2},
            {"tag": "reading", "count": 1},
        ]


class TestGoal:
    def test_sets_the_goal(self, data_dir):
        assert invoke(data_dir, "goal", "6") == 0
        assert goal(data_dir) == 6

    def test_zero_disables_the_goal(self, data_dir):
        invoke(data_dir, "goal", "0")
        assert goal(data_dir) == 0

    def test_querying_reports_the_current_goal(self, data_dir, capsys):
        invoke(data_dir, "goal", "3")
        invoke(data_dir, "goal")
        assert "3" in capsys.readouterr().out

    def test_a_non_numeric_goal_is_rejected_by_argparse(self, data_dir):
        with pytest.raises(SystemExit):
            invoke(data_dir, "goal", "many")

    def test_a_negative_goal_is_reported(self, data_dir, capsys):
        assert invoke(data_dir, "goal", "-1") == 2
        assert "cannot be negative" in capsys.readouterr().err


class TestNotify:
    def test_a_url_flag_works_without_any_configuration(self, data_dir, capsys, monkeypatch):
        monkeypatch.delenv(config.ENV_WEBHOOK, raising=False)
        sent: list[str] = []
        monkeypatch.setattr(notify, "send", lambda url, *a, **k: sent.append(url))
        assert invoke(data_dir, "notify", "--url", "https://example.invalid/hook") == 0
        assert sent == ["https://example.invalid/hook"]

    def test_the_url_flag_overrides_the_configured_one(self, data_dir, monkeypatch):
        monkeypatch.setenv(config.ENV_WEBHOOK, "https://configured.invalid/hook")
        sent: list[str] = []
        monkeypatch.setattr(notify, "send", lambda url, *a, **k: sent.append(url))
        assert invoke(data_dir, "notify", "--url", "https://flag.invalid/hook") == 0
        assert sent == ["https://flag.invalid/hook"]

    def test_dry_run_prints_without_sending(self, data_dir, capsys, monkeypatch):
        monkeypatch.setenv(config.ENV_WEBHOOK, "https://example.invalid/hook")
        monkeypatch.setattr(notify, "send", lambda *a, **k: pytest.fail("dry run must not send"))
        assert invoke(data_dir, "notify", "--dry-run") == 0
        out = capsys.readouterr().out
        assert "Dry run" in out
        assert "streak" in out

    def test_without_a_webhook_it_reports_clearly(self, data_dir, capsys):
        assert invoke(data_dir, "notify") == 2
        assert "No webhook configured" in capsys.readouterr().err

    def test_it_posts_the_message_when_configured(self, data_dir, capsys, monkeypatch):
        sent: list[tuple] = []
        monkeypatch.setenv(config.ENV_WEBHOOK, "https://example.invalid/hook")
        monkeypatch.setattr(notify, "send", lambda url, report: sent.append((url, report)))
        invoke(data_dir, "mark", "2026-03-01", "-n", "private thoughts")
        assert invoke(data_dir, "notify") == 0
        assert len(sent) == 1
        url, report = sent[0]
        assert url == "https://example.invalid/hook"
        assert "streak" in report.message

    def test_the_note_is_excluded_unless_asked_for(self, data_dir, monkeypatch):
        sent: list[str] = []
        monkeypatch.setenv(config.ENV_WEBHOOK, "https://example.invalid/hook")
        monkeypatch.setattr(notify, "send", lambda url, report: sent.append(report.message))
        invoke(data_dir, "mark", "2026-03-01", "-n", "secret plan")
        invoke(data_dir, "notify")
        invoke(data_dir, "notify", "--include-note", "--day", "2026-03-01")
        assert "secret plan" not in sent[0]
        assert "secret plan" in sent[1]

    def test_json_reports_the_message_and_configuration(self, data_dir, capsys, monkeypatch):
        monkeypatch.setenv(config.ENV_WEBHOOK, "https://example.invalid/hook")
        monkeypatch.setattr(notify, "send", lambda url, report: None)
        invoke(data_dir, "--json", "notify")
        body = payload(capsys)
        assert body["configured"] is True
        assert "streak" in body["message"]

    def test_a_delivery_failure_is_reported_not_raised(self, data_dir, capsys, monkeypatch):
        def boom(url, report):
            raise notify.NotificationError("Could not reach the webhook: refused.")

        monkeypatch.setenv(config.ENV_WEBHOOK, "https://example.invalid/hook")
        monkeypatch.setattr(notify, "send", boom)
        assert invoke(data_dir, "notify") == 1
        assert "Could not send" in capsys.readouterr().out


class TestBackup:
    def test_export_then_import_round_trips(self, data_dir, tmp_path):
        invoke(data_dir, "mark", "2026-03-01", "-n", "one")
        archive = tmp_path / "archive.json"
        assert invoke(data_dir, "export", str(archive)) == 0
        invoke(data_dir, "unmark", "2026-03-01", "--yes")
        assert invoke(data_dir, "import", str(archive), "--force") == 0
        assert sessions(data_dir) == {"2026-03-01": "one"}

    def test_export_includes_every_habit(self, data_dir, tmp_path):
        invoke(data_dir, "habit", "add", "Read")
        invoke(data_dir, "mark", "2026-03-02", "-n", "read", "--habit", "read")
        archive = tmp_path / "archive.json"
        invoke(data_dir, "export", str(archive))
        restored = json.loads(archive.read_text(encoding="utf-8"))
        assert set(restored["habits"]) == {"coding", "read"}

    def test_importing_a_missing_file_reports_an_error(self, data_dir, capsys):
        assert invoke(data_dir, "import", str(data_dir / "nope.json"), "--force") == 1
        assert "No such file" in capsys.readouterr().err

    def test_export_json_names_the_path(self, data_dir, tmp_path, capsys):
        archive = tmp_path / "a.json"
        invoke(data_dir, "--json", "export", str(archive))
        assert payload(capsys)["path"] == str(archive)


class TestSqliteBackend:
    def test_state_survives_a_round_trip_through_sqlite(self, data_dir):
        assert invoke(data_dir, "--backend", "sqlite", "mark", "2026-03-01", "-n", "in sqlite") == 0
        loaded = storage.load_data(data_dir / "data.sqlite3")
        assert state.sessions_of(loaded) == {"2026-03-01": "in sqlite"}

    def test_habits_survive_sqlite(self, data_dir):
        invoke(data_dir, "--backend", "sqlite", "habit", "add", "Read", "--goal", "4")
        invoke(data_dir, "--backend", "sqlite", "mark", "2026-03-02", "-n", "r", "--habit", "read")
        loaded = storage.load_data(data_dir / "data.sqlite3")
        assert state.sessions_of(loaded, "read") == {"2026-03-02": "r"}
        assert state.goal_of(loaded, "read") == 4

    def test_migrating_copies_json_into_sqlite(self, data_dir):
        invoke(data_dir, "mark", "2026-03-01", "-n", "one")
        target = data_dir / "migrated.sqlite3"
        assert invoke(data_dir, "migrate-to-sqlite", "--output", str(target)) == 0
        assert state.sessions_of(storage.load_data(target)) == {"2026-03-01": "one"}

    def test_the_json_store_is_untouched_by_a_sqlite_write(self, data_dir):
        invoke(data_dir, "mark", "2026-03-01")
        invoke(data_dir, "--backend", "sqlite", "mark", "2026-03-02")
        assert list(sessions(data_dir)) == ["2026-03-01"]


class TestEnv:
    def test_env_reports_the_resolved_paths(self, data_dir, capsys):
        invoke(data_dir, "--json", "env")
        body = payload(capsys)
        assert body["data_dir"] == str(data_dir)
        assert body["backend"] == "json"

    def test_env_lists_optional_packages(self, data_dir, capsys):
        invoke(data_dir, "--json", "env")
        packages = payload(capsys)["optional_packages"]
        assert set(packages) >= {"rich", "textual", "dateparser", "tkcalendar", "platformdirs"}

    def test_env_reports_the_schema_version(self, data_dir, capsys):
        invoke(data_dir, "--json", "env")
        assert payload(capsys)["schema_version"] == 2

    def test_env_reports_habits_and_the_active_one(self, data_dir, capsys):
        invoke(data_dir, "habit", "add", "Read")
        invoke(data_dir, "--json", "env")
        body = payload(capsys)
        assert sorted(body["habits"]) == ["coding", "read"]
        assert body["active_habit"] == "coding"

    def test_env_reports_whether_a_webhook_is_configured(self, data_dir, capsys):
        invoke(data_dir, "--json", "env")
        assert payload(capsys)["webhook_configured"] is False

    def test_env_reports_the_theme_and_how_it_resolves(self, data_dir, capsys, monkeypatch):
        monkeypatch.delenv(config.ENV_THEME, raising=False)
        invoke(data_dir, "--json", "env")
        body = payload(capsys)
        assert body["theme"] == "system"
        assert body["theme_resolved"] in {"light", "dark"}

    def test_env_reports_an_explicit_theme(self, data_dir, capsys, monkeypatch):
        monkeypatch.setenv(config.ENV_THEME, "dark")
        invoke(data_dir, "--json", "env")
        body = payload(capsys)
        assert body["theme"] == "dark"
        assert body["theme_resolved"] == "dark"

    def test_a_bad_theme_is_reported_cleanly(self, data_dir, capsys, monkeypatch):
        monkeypatch.setenv(config.ENV_THEME, "neon")
        assert invoke(data_dir, "env") == 1
        assert "Unknown theme" in capsys.readouterr().err

    def test_env_reports_the_configured_timezone(self, data_dir, capsys):
        invoke(data_dir, "--json", "--tz", "UTC", "env")
        assert payload(capsys)["timezone"] == "UTC"

    def test_a_bad_timezone_is_reported_cleanly(self, data_dir, capsys):
        assert invoke(data_dir, "--tz", "Mars/Olympus", "env") == 1
        assert "Unknown timezone" in capsys.readouterr().err


class TestParserPlumbing:
    def test_no_arguments_prints_help_when_not_a_tty(self, capsys, monkeypatch):
        monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False, raising=False)
        assert cli.main([]) == 0
        assert "usage: ht" in capsys.readouterr().out

    def test_version_is_reported(self, capsys):
        with pytest.raises(SystemExit) as excinfo:
            cli.main(["--version"])
        assert excinfo.value.code == 0
        assert "ht" in capsys.readouterr().out

    def test_an_unknown_backend_is_rejected_by_argparse(self):
        with pytest.raises(SystemExit):
            cli.main(["--backend", "mysql", "stats"])

    def test_help_lists_every_command(self, capsys):
        with pytest.raises(SystemExit):
            cli.main(["--help"])
        out = capsys.readouterr().out
        for command in (
            "mark",
            "unmark",
            "week",
            "month",
            "stats",
            "tags",
            "goal",
            "habit",
            "undo",
            "notify",
            "export",
            "import",
            "gui",
            "env",
        ):
            assert command in out

    def test_the_legacy_gui_flag_is_accepted(self, monkeypatch):
        called: list[bool] = []
        monkeypatch.setattr(cli, "cmd_gui", lambda ctx, args: called.append(True) or 0)
        assert cli.main(["--gui"]) == 0
        assert called == [True]
