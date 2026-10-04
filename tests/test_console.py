from __future__ import annotations

import io
import json

import pytest

from habit_tracker import console as console_module
from habit_tracker.console import Console, bar, percentage


class TestBar:
    def test_partial_progress(self):
        assert bar(1, 2, width=4) == "[##--]  1/2"

    def test_full_progress(self):
        assert bar(5, 5, width=4) == "[####]  5/5"

    def test_no_progress(self):
        assert bar(0, 5, width=4) == "[----]  0/5"

    def test_over_goal_is_capped_at_full(self):
        assert bar(9, 5, width=4) == "[####]  9/5"

    def test_zero_goal_reads_as_off(self):
        assert bar(0, 0, width=4) == "[????]  off"

    def test_bar_is_a_fixed_width(self):
        for done in range(0, 6):
            assert len(bar(done, 5, width=20)) == len(bar(0, 5, width=20))


class TestPercentage:
    def test_exact(self):
        assert percentage(1, 2) == 50

    def test_rounds_to_whole_numbers(self):
        assert percentage(1, 3) == 33

    def test_capped_at_one_hundred(self):
        assert percentage(10, 5) == 100

    def test_never_negative(self):
        assert percentage(-1, 5) == 0

    def test_zero_goal_is_zero(self):
        assert percentage(0, 0) == 0

    def test_zero_goal_is_never_full(self):
        """Regression: the GUI progress bar used to read 100% when the goal was off."""
        assert percentage(0, 0) != 100


@pytest.fixture
def sink() -> io.StringIO:
    return io.StringIO()


def make(sink: io.StringIO, **kwargs) -> Console:
    kwargs.setdefault("color", False)
    return Console(stream=sink, error_stream=sink, **kwargs)


class TestPlainOutput:
    def test_line_writes_text(self, sink):
        make(sink).line("hello")
        assert sink.getvalue() == "hello\n"

    def test_detail_is_indented_and_aligned(self, sink):
        make(sink).detail("Streak", "4 day(s)")
        assert sink.getvalue().startswith("  Streak")

    def test_success_and_warn_use_a_marker(self, sink):
        con = make(sink)
        con.success("done")
        con.warn("careful")
        assert "+ done" in sink.getvalue()
        assert "! careful" in sink.getvalue()

    def test_table_has_a_header_and_a_rule(self, sink):
        make(sink).table(["Tag", "Count"], [("#python", 3)])
        out = sink.getvalue()
        assert "Tag" in out
        assert "---" in out
        assert "#python" in out

    def test_table_handles_no_rows(self, sink):
        make(sink).table(["Tag", "Count"], [])
        assert "Tag" in sink.getvalue()

    def test_progress_line_shows_the_bar(self, sink):
        make(sink).progress(1, 2)
        assert "1/2" in sink.getvalue()
        assert "50%" in sink.getvalue()

    def test_progress_line_with_the_goal_off(self, sink):
        make(sink).progress(3, 0)
        assert "off" in sink.getvalue()
        assert "%" not in sink.getvalue()

    def test_rich_is_not_used_when_colour_is_off(self, sink):
        assert make(sink, color=False)._rich is None


class TestJsonMode:
    def test_emit_writes_a_json_document(self, sink):
        make(sink, json_mode=True).emit({"ok": True, "n": 1})
        assert json.loads(sink.getvalue()) == {"ok": True, "n": 1}

    def test_json_mode_suppresses_human_text(self, sink):
        con = make(sink, json_mode=True)
        con.line("should not appear")
        con.detail("label", "value")
        con.success("nope")
        con.progress(1, 2)
        assert sink.getvalue() == ""

    def test_errors_become_json_in_json_mode(self, sink):
        make(sink, json_mode=True).error("went wrong")
        assert json.loads(sink.getvalue()) == {"ok": False, "error": "went wrong"}

    def test_dates_serialise(self, sink):
        from datetime import date

        make(sink, json_mode=True).emit({"day": date(2026, 3, 1)})
        assert json.loads(sink.getvalue())["day"] == "2026-03-01"

    def test_emit_is_a_no_op_outside_json_mode(self, sink):
        make(sink).emit({"ok": True})
        assert sink.getvalue() == ""


class TestRichIntegration:
    def test_rich_is_used_when_available_and_allowed(self, sink):
        pytest.importorskip("rich")
        assert Console(color=True, stream=sink, error_stream=sink)._rich is not None

    def test_json_mode_never_uses_rich(self, sink):
        pytest.importorskip("rich")
        con = Console(color=True, json_mode=True, stream=sink, error_stream=sink)
        assert con._rich is None

    def test_rich_table_renders(self, sink):
        pytest.importorskip("rich")
        Console(color=True, stream=sink, error_stream=sink).table(
            ["Tag", "Count"], [("#python", 3)]
        )
        assert "python" in sink.getvalue()

    def test_rich_heading_renders(self, sink):
        pytest.importorskip("rich")
        Console(color=True, stream=sink, error_stream=sink).heading("Stats")
        assert "Stats" in sink.getvalue()

    def test_missing_rich_degrades_to_plain(self, sink, monkeypatch):
        monkeypatch.setattr(console_module, "_load_rich", lambda: None)
        con = Console(color=True, stream=sink, error_stream=sink)
        assert con._rich is None
        con.table(["Tag"], [("#python",)])
        assert "#python" in sink.getvalue()
