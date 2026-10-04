"""Tests for webhook notification composition and delivery.

No network is used: :func:`habit_tracker.notify.build_report` is pure, and
:func:`~habit_tracker.notify.send` is exercised through a stubbed ``urlopen``.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from urllib import error as urlerror

import pytest

from habit_tracker import notify

TODAY = date(2026, 10, 4)


def view(**sessions: str) -> dict:
    return {"goal": 5, "sessions": dict(sessions)}


def days_ending_today(count: int) -> dict:
    """The last ``count`` days up to and including :data:`TODAY`."""
    return {(TODAY - timedelta(days=offset)).isoformat(): "" for offset in range(count)}


class FakeResponse:
    def __init__(self, status: int = 200) -> None:
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc_info) -> bool:
        return False


class TestBuildReport:
    def test_reports_the_streak_and_weekly_progress(self):
        report = notify.build_report(view(**days_ending_today(3)), TODAY, habit="Coding")
        assert report.current_streak == 3
        assert report.week_done == 3
        assert report.goal == 5
        assert report.habit == "Coding"
        assert "3-day streak" in report.message
        assert "3/5 this week" in report.message

    def test_names_the_habit(self):
        report = notify.build_report(view(), TODAY, habit="Reading")
        assert report.message.startswith("Reading:")

    def test_encourages_when_nothing_is_logged(self):
        report = notify.build_report(view(), TODAY)
        assert "Nothing logged yet" in report.message

    def test_mentions_the_goal_when_it_is_reached(self):
        report = notify.build_report(view(**days_ending_today(5)), TODAY)
        assert "Goal reached." in report.message

    def test_mentions_the_best_streak_when_beating_it(self):
        # A five-day run last month, but only two days so far: best is 5.
        sessions = {(TODAY - timedelta(days=offset)).isoformat(): "" for offset in range(8, 13)}
        sessions.update(days_ending_today(2))
        report = notify.build_report(view(**sessions), TODAY)
        assert report.current_streak == 2
        assert "Best so far: 5." in report.message

    def test_a_lapsed_streak_is_not_reported_as_never_started(self):
        """Logging days last month must not read as 'nothing logged yet'."""
        sessions = {"2026-09-01": "", "2026-09-02": "", "2026-09-03": ""}
        report = notify.build_report(view(**sessions), TODAY)
        assert report.current_streak == 0
        assert "Best so far: 3." not in report.message
        assert "Streak has lapsed" in report.message

    def test_a_goal_of_zero_says_so_instead_of_showing_a_fraction(self):
        bare = {"goal": 0, "sessions": {}}
        report = notify.build_report(bare, TODAY)
        assert "/0" not in report.message
        assert "no goal set" in report.message

    def test_the_note_is_excluded_by_default(self):
        """Webhook URLs are usually third-party, so prose stays local."""
        report = notify.build_report(
            view(**{"2026-10-04": "saw the doctor"}),
            TODAY,
            include_note=False,
            note="saw the doctor",
        )
        assert "saw the doctor" not in report.message

    def test_the_note_is_included_on_request(self):
        report = notify.build_report(
            view(**{"2026-10-04": "saw the doctor"}),
            TODAY,
            include_note=True,
            note="saw the doctor",
        )
        assert "saw the doctor" in report.message

    def test_an_empty_note_adds_nothing_even_when_requested(self):
        report = notify.build_report(view(), TODAY, include_note=True, note="")
        assert "Note:" not in report.message

    def test_build_report_is_pure(self):
        original = view(**days_ending_today(2))
        snapshot = json.dumps(original, sort_keys=True)
        notify.build_report(original, TODAY)
        assert json.dumps(original, sort_keys=True) == snapshot


class TestPayload:
    def test_includes_slack_and_discord_keys(self):
        payload = notify.Report(
            message="hi", habit="x", current_streak=0, week_done=0, goal=0
        ).payload()
        assert payload["text"] == "hi"
        assert payload["content"] == "hi"

    def test_payload_is_json_serialisable(self):
        report = notify.build_report(view(), TODAY)
        assert json.loads(json.dumps(report.payload()))["text"] == report.message


class TestSend:
    def test_posts_json_with_a_user_agent(self, monkeypatch):
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["body"] = req.data
            captured["method"] = req.get_method()
            captured["headers"] = req.headers
            captured["timeout"] = timeout
            return FakeResponse(200)

        monkeypatch.setattr(notify.urlrequest, "urlopen", fake_urlopen)
        notify.send("https://example.test/hook", notify.build_report(view(), TODAY))

        assert captured["url"] == "https://example.test/hook"
        assert captured["method"] == "POST"
        assert captured["timeout"] == notify.DEFAULT_TIMEOUT
        assert json.loads(captured["body"].decode("utf-8"))["text"]
        assert captured["headers"]["Content-type"] == "application/json"
        assert notify.USER_AGENT in str(captured["headers"]["User-agent"])

    def test_a_dry_run_is_left_to_the_caller(self, monkeypatch):
        """Nothing is sent unless :func:`send` is called."""
        calls = []
        monkeypatch.setattr(notify.urlrequest, "urlopen", lambda *a, **k: calls.append(1))
        notify.build_report(view(), TODAY)
        assert calls == []

    def test_a_custom_timeout_is_passed_through(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            notify.urlrequest,
            "urlopen",
            lambda req, timeout=None: (captured.update(timeout=timeout), FakeResponse(200))[1],
        )
        notify.send("https://example.test/hook", notify.build_report(view(), TODAY), timeout=1.5)
        assert captured["timeout"] == 1.5

    @pytest.mark.parametrize("url", ["", "   ", "ftp://example.test", "example.test/hook"])
    def test_a_bad_url_is_rejected_before_any_request(self, monkeypatch, url):
        monkeypatch.setattr(
            notify.urlrequest, "urlopen", lambda *a, **k: pytest.fail("must not make a request")
        )
        with pytest.raises(notify.NotificationError):
            notify.send(url, notify.build_report(view(), TODAY))

    def test_an_http_error_becomes_a_notification_error(self, monkeypatch):
        def fake_urlopen(req, timeout=None):
            raise urlerror.HTTPError(req.full_url, 403, "Forbidden", {}, None)

        monkeypatch.setattr(notify.urlrequest, "urlopen", fake_urlopen)
        with pytest.raises(notify.NotificationError, match="403"):
            notify.send("https://example.test/hook", notify.build_report(view(), TODAY))

    def test_a_network_failure_becomes_a_notification_error(self, monkeypatch):
        def fake_urlopen(req, timeout=None):
            raise urlerror.URLError("name resolution failed")

        monkeypatch.setattr(notify.urlrequest, "urlopen", fake_urlopen)
        with pytest.raises(notify.NotificationError, match="Could not reach"):
            notify.send("https://example.test/hook", notify.build_report(view(), TODAY))

    def test_a_timeout_becomes_a_notification_error(self, monkeypatch):
        def fake_urlopen(req, timeout=None):
            raise TimeoutError

        monkeypatch.setattr(notify.urlrequest, "urlopen", fake_urlopen)
        with pytest.raises(notify.NotificationError, match="timed out"):
            notify.send("https://example.test/hook", notify.build_report(view(), TODAY))

    def test_an_error_status_on_a_response_is_caught(self, monkeypatch):
        monkeypatch.setattr(
            notify.urlrequest, "urlopen", lambda req, timeout=None: FakeResponse(500)
        )
        with pytest.raises(notify.NotificationError, match="500"):
            notify.send("https://example.test/hook", notify.build_report(view(), TODAY))

    def test_a_successful_send_raises_nothing(self, monkeypatch):
        monkeypatch.setattr(
            notify.urlrequest, "urlopen", lambda req, timeout=None: FakeResponse(204)
        )
        notify.send("https://example.test/hook", notify.build_report(view(), TODAY))
