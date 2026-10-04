"""Hashtag extraction and tag aggregation for session notes."""

from __future__ import annotations

import re
from collections.abc import Iterable

TAG_PATTERN = re.compile(r"#([A-Za-z0-9_]+)")
SPLIT_PATTERN = re.compile(r"[,\s]+")


def normalise_tag(tag: str) -> str:
    """Strip a leading ``#`` and lowercase, leaving only tag-legal characters."""
    cleaned = tag.strip().lstrip("#").lower()
    return "".join(char for char in cleaned if char.isalnum() or char == "_")


def get_tags(note: str) -> list[str]:
    """Every ``#hashtag`` in ``note``, lowercased, in order of appearance.

    Punctuation attached to a tag is ignored, so ``"shipped #python, finally"``
    yields ``["python"]``. Anything that is not a string yields no tags.
    """
    if not note or not isinstance(note, str):
        return []
    return [match.lower() for match in TAG_PATTERN.findall(note)]


def parse_tag_input(text: str) -> list[str]:
    """Parse a tag picker input, accepting ``#a,b #c`` or space-separated tags."""
    if not text:
        return []
    tags: list[str] = []
    for chunk in SPLIT_PATTERN.split(text):
        tag = normalise_tag(chunk)
        if tag and tag not in tags:
            tags.append(tag)
    return tags


def add_tag_to_note(note: str, tag: str) -> str:
    """Append ``tag`` to ``note`` unless it is already present."""
    normalised = normalise_tag(tag)
    if not normalised:
        return note
    if normalised in get_tags(note):
        return note
    return f"{note} #{normalised}" if note else f"#{normalised}"


def tag_counts(notes: Iterable[str]) -> dict[str, int]:
    """Count tag occurrences across ``notes``, most used first."""
    counts: dict[str, int] = {}
    for note in notes:
        for tag in get_tags(note):
            counts[tag] = counts.get(tag, 0) + 1
    return counts


def ranked_tag_counts(notes: Iterable[str]) -> list[tuple[str, int]]:
    """Tag counts sorted by descending count, then alphabetically."""
    return sorted(tag_counts(notes).items(), key=lambda item: (-item[1], item[0]))
