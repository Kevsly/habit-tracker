"""Terminal output.

Every message the CLI prints goes through :class:`Console`. It renders with
``rich`` when that package is installed and a TTY is attached, and otherwise
falls back to plain ASCII, so the tool stays fully usable with no third-party
packages and in pipes, logs and CI.

``--json`` switches to machine-readable output for scripting.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from importlib.util import find_spec
from typing import Any, TextIO

BAR_WIDTH = 20
_DONE = "#"
_TODO = "-"
_UNKNOWN = "?"


def _package_available(name: str) -> bool:
    try:
        return find_spec(name) is not None
    except (ImportError, ValueError):
        return False


HAS_RICH = _package_available("rich")


@dataclass(frozen=True)
class _RichApi:
    """The ``rich`` symbols, resolved only when the package is importable."""

    console: type
    panel: type
    table: type


def _load_rich() -> _RichApi | None:
    try:
        from rich.console import Console as RichConsole
        from rich.panel import Panel
        from rich.table import Table
    except ImportError:
        return None
    return _RichApi(console=RichConsole, panel=Panel, table=Table)


def bar(done: int, goal: int, width: int = BAR_WIDTH) -> str:
    """Render a fixed-width progress bar. A goal of zero reads as unknown."""
    if goal <= 0:
        return f"[{_UNKNOWN * width}]  off"
    filled = max(0, min(width, round(width * done / goal)))
    return f"[{_DONE * filled}{_TODO * (width - filled)}]  {done}/{goal}"


def percentage(done: int, goal: int) -> int:
    """Completion percentage, or 0 when no goal is set."""
    return min(max(round(done / goal * 100), 0), 100) if goal > 0 else 0


class Console:
    """Output sink with rich, plain and JSON modes."""

    def __init__(
        self,
        *,
        color: bool | None = None,
        json_mode: bool = False,
        stream: TextIO | None = None,
        error_stream: TextIO | None = None,
    ) -> None:
        self.stream = stream or sys.stdout
        self.error_stream = error_stream or sys.stderr
        self.json_mode = json_mode
        self._api = None if json_mode or not self._color_allowed(color) else _load_rich()
        self.use_rich = self._api is not None
        self._rich = self._api.console(file=self.stream) if self._api else None

    def _color_allowed(self, color: bool | None) -> bool:
        if color is not None:
            return color
        if os.environ.get("NO_COLOR"):
            return False
        if os.environ.get("TERM") == "dumb":
            return False
        return self._isatty

    @property
    def _isatty(self) -> bool:
        return bool(getattr(self.stream, "isatty", lambda: False)())

    def emit(self, payload: dict[str, Any]) -> None:
        """Write a JSON document. Used instead of human output in ``--json`` mode."""
        if not self.json_mode:
            return
        json.dump(payload, self.stream, indent=2, sort_keys=True, default=str)
        self.stream.write("\n")

    def line(self, text: str = "") -> None:
        if self.json_mode:
            return
        self.stream.write(f"{text}\n")

    def detail(self, label: str, value: Any) -> None:
        """An aligned ``label   value`` pair."""
        if self.json_mode:
            return
        self.stream.write(f"  {label:<18}{value}\n")

    def heading(self, text: str) -> None:
        if self.json_mode:
            return
        if self._rich is not None:
            self._rich.print(self._api.panel(text, expand=False))
            return
        self.line()
        self.line(f"  {text}")
        self.line(f"  {'-' * len(text)}")

    def success(self, text: str) -> None:
        self._status(text, "+")

    def warn(self, text: str) -> None:
        self._status(text, "!")

    def error(self, text: str) -> None:
        if self.json_mode:
            self.emit({"ok": False, "error": text})
            return
        self.error_stream.write(f"  error: {text}\n")

    def _status(self, text: str, marker: str) -> None:
        if self.json_mode:
            return
        self.stream.write(f"  {marker} {text}\n")

    def clear(self) -> None:
        if self.json_mode or self._rich is not None or not self._isatty:
            return
        self.stream.write("\x1b[2J\x1b[H")

    def table(self, headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> None:
        """Render a bordered table."""
        if self.json_mode:
            return
        if self._rich is not None:
            table = self._api.table(show_header=True, header_style="bold", box=None)
            for header in headers:
                table.add_column(str(header))
            for row in rows:
                table.add_row(*[str(cell) for cell in row])
            self._rich.print(table)
            return

        plain_rows = [[str(cell) for cell in row] for row in rows]
        columns = max([len(headers), *(len(row) for row in plain_rows)])
        widths = [
            max(
                [len(headers[i]) if i < len(headers) else 0]
                + [len(row[i]) for row in plain_rows if i < len(row)]
            )
            for i in range(columns)
        ]

        def render(cells: list[str]) -> str:
            padded = [cell.ljust(widths[i]) for i, cell in enumerate(cells)]
            padded.extend(" " * widths[i] for i in range(len(padded), columns))
            return ("  " + "  ".join(padded)).rstrip()

        self.line(render([str(header) for header in headers]))
        self.line("  " + "  ".join("-" * width for width in widths))
        for row in plain_rows:
            self.line(render(row))

    def progress(self, done: int, goal: int) -> None:
        """A progress line: bar plus percentage, or a note when the goal is off."""
        if self.json_mode:
            return
        if goal <= 0:
            self.line(f"  {bar(done, goal)}")
            return
        self.line(f"  {bar(done, goal)}  {percentage(done, goal)}%")
