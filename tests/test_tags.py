from __future__ import annotations

from datetime import date

import pytest

from habit_tracker import tags


class TestGetTags:
    def test_finds_a_single_tag(self):
        assert tags.get_tags("worked on #python") == ["python"]

    def test_finds_multiple_tags(self):
        assert tags.get_tags("shipped #python and #rust") == ["python", "rust"]

    def test_lowercases_tags(self):
        assert tags.get_tags("learning #Python #FastAPI") == ["python", "fastapi"]

    def test_ignores_trailing_punctuation(self):
        assert tags.get_tags("finally shipped #python, then #rust.") == ["python", "rust"]

    def test_underscores_and_digits_survive(self):
        assert tags.get_tags("#step_2 #a1") == ["step_2", "a1"]

    def test_bare_hash_is_not_a_tag(self):
        assert tags.get_tags("a # b") == []

    def test_empty_note_has_no_tags(self):
        assert tags.get_tags("") == []

    def test_none_note_has_no_tags(self):
        assert tags.get_tags(None) == []

    def test_preserves_order_of_appearance(self):
        assert tags.get_tags("#c #a #b") == ["c", "a", "b"]


class TestNormaliseTag:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("#Python", "python"),
            ("  RUST ", "rust"),
            ("a-b", "ab"),
            ("#a.b", "ab"),
            ("##double", "double"),
        ],
    )
    def test_normalisation(self, raw, expected):
        assert tags.normalise_tag(raw) == expected

    def test_symbols_are_stripped_to_nothing(self):
        assert tags.normalise_tag("!!!") == ""


class TestParseTagInput:
    def test_space_separated(self):
        assert tags.parse_tag_input("python rust") == ["python", "rust"]

    def test_comma_separated(self):
        assert tags.parse_tag_input("python, rust") == ["python", "rust"]

    def test_mixed_separators(self):
        assert tags.parse_tag_input("#python, rust  go") == ["python", "rust", "go"]

    def test_duplicates_are_collapsed(self):
        assert tags.parse_tag_input("python, python PYTHON") == ["python"]

    def test_leading_hashes_are_optional(self):
        assert tags.parse_tag_input("#a #b") == ["a", "b"]

    def test_empty_input_yields_nothing(self):
        assert tags.parse_tag_input("   ") == []


class TestAddTagToNote:
    def test_appends_to_an_existing_note(self):
        assert tags.add_tag_to_note("learned asyncio", "python") == "learned asyncio #python"

    def test_creates_a_note_from_nothing(self):
        assert tags.add_tag_to_note("", "python") == "#python"

    def test_does_not_duplicate_an_existing_tag(self):
        assert tags.add_tag_to_note("#python asyncio", "Python") == "#python asyncio"

    def test_does_not_match_a_tag_inside_a_word(self):
        assert tags.add_tag_to_note("#pythonic", "python") == "#pythonic #python"

    def test_ignores_an_empty_tag(self):
        assert tags.add_tag_to_note("note", "#") == "note"

    def test_adding_several_builds_up_the_note(self):
        note = ""
        for tag in ("python", "rust", "python"):
            note = tags.add_tag_to_note(note, tag)
        assert note == "#python #rust"


class TestCounts:
    def test_counts_across_notes(self):
        counts = tags.tag_counts(["#python work", "#rust and #python", "no tags"])
        assert counts == {"python": 2, "rust": 1}

    def test_ranked_sorts_by_count_then_alphabetically(self):
        ranked = tags.ranked_tag_counts(["#b #a #a #c #c #c"])
        assert ranked == [("c", 3), ("a", 2), ("b", 1)]

    def test_ranked_of_nothing_is_empty(self):
        assert tags.ranked_tag_counts([]) == []
        assert tags.ranked_tag_counts(["plain note"]) == []

    def test_counts_only_strings(self):
        notes: list = ["#python", None, 42, "#python"]
        assert tags.tag_counts(notes) == {"python": 2}

    def test_repeated_tag_in_one_note_counts_once(self):
        assert tags.tag_counts(["#python then #python again"]) == {"python": 2}


class TestDateTagInterop:
    def test_note_round_trips_through_tracker(self):
        from habit_tracker import tracker

        data: dict = {"goal": 5, "sessions": {}}
        tracker.mark_session(data, date(2026, 3, 1), "wrote #pytest tests")
        assert tracker.get_tags(tracker.note_for(data, date(2026, 3, 1))) == ["pytest"]
