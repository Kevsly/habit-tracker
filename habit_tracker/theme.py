"""Colour palettes for the desktop window.

The GUI used to hardcode a single light theme in every module. Keeping the
colours in one place is what makes a dark mode possible, and it is the
prerequisite for swapping the widget toolkit later.

Nothing here imports Tkinter, so the CLI and TUI never pay for it.
"""

from __future__ import annotations

import functools
import logging
import os
from dataclasses import dataclass

log = logging.getLogger(__name__)

ENV_THEME = "HABIT_TRACKER_THEME"
THEME_MODES = ("system", "dark", "light")
DEFAULT_THEME = "system"


class ThemeError(ValueError):
    """Raised when an unknown theme mode is requested."""


@dataclass(frozen=True)
class Palette:
    """Every colour the desktop window paints with.

    Kept deliberately small: if a screen needs a colour that is not here, the
    palette is the right place to add it rather than a hex literal.
    """

    background: str
    """Window and notebook background."""

    surface: str
    """Cards, tab bodies and other raised panels."""

    surface_alt: str
    """Nested or alternate rows, such as form strips."""

    border: str
    """Dividers and cell outlines."""

    text: str
    """Primary text."""

    text_muted: str
    """Secondary text: labels, units, hints."""

    accent: str
    """Today, focus rings and the active selection."""

    on_accent: str
    """Text drawn on top of :attr:`accent` or :attr:`success`."""

    success: str
    """A completed session."""

    missed: str
    """A day in the past with nothing logged."""

    future: str
    """A day that has not happened yet."""

    danger: str
    """Destructive actions and errors."""

    name: str = "light"
    """``"light"`` or ``"dark"``, for status text and logs."""


LIGHT = Palette(
    name="light",
    background="#f1f3f5",
    surface="#ffffff",
    surface_alt="#e9ecef",
    border="#dee2e6",
    text="#212529",
    text_muted="#57606a",
    accent="#1971c2",
    on_accent="#ffffff",
    success="#2f9e44",
    missed="#e9ecef",
    future="#f8f9fa",
    danger="#c92a2a",
)

DARK = Palette(
    name="dark",
    background="#16181d",
    surface="#1f2229",
    surface_alt="#282c35",
    border="#3a4150",
    text="#e6e8ec",
    text_muted="#9aa3b2",
    accent="#4c9aff",
    on_accent="#0b1220",
    success="#3fb950",
    missed="#2c313a",
    future="#1b1e24",
    danger="#f85149",
)

PALETTES = {"light": LIGHT, "dark": DARK}


def normalise_mode(mode: str | None) -> str:
    """Validate and lowercase a theme mode, defaulting to ``system``."""
    chosen = (mode or DEFAULT_THEME).strip().lower() or DEFAULT_THEME
    if chosen not in THEME_MODES:
        raise ThemeError(f"Unknown theme {mode!r}. Choose one of: {', '.join(THEME_MODES)}.")
    return chosen


@functools.lru_cache(maxsize=1)
def system_prefers_dark() -> bool:
    """Best-effort read of the desktop appearance setting.

    Falls back to light when the platform offers no way to ask. The result is
    cached because the answer cannot change while the process runs in any
    meaningful way, and Windows needs a registry read.
    """
    detected = _windows_prefers_dark()
    if detected is None:
        detected = _unix_prefers_dark()
    if detected is None:
        log.debug("No system appearance setting available; using the light theme.")
        return False
    return detected


def _windows_prefers_dark() -> bool | None:
    if os.name != "nt":
        return None
    try:
        import winreg
    except ImportError:  # pragma: no cover - winreg ships with CPython on Windows
        return None
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            light, _kind = winreg.QueryValueEx(key, "AppsUseLightTheme")
    except OSError:
        return None
    return not bool(int(light))


def _unix_prefers_dark() -> bool | None:
    """Honour ``GTK_THEME``, the only dark hint available without dependencies."""
    for name in ("GTK_THEME", "QT_STYLE_OVERRIDE"):
        value = os.environ.get(name, "").strip().lower()
        if value:
            return "dark" in value
    return None


def resolve_palette(mode: str | None = None) -> Palette:
    """Palette for ``system``, ``dark`` or ``light``.

    ``system`` follows the desktop setting; the other two are explicit.
    """
    chosen = normalise_mode(mode)
    if chosen == "system":
        chosen = "dark" if system_prefers_dark() else "light"
    return PALETTES[chosen]
