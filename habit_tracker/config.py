"""Runtime configuration: data locations, timezone and backend selection.

Every setting is resolved in this order (highest priority first):

1. an explicit command-line flag
2. an environment variable (``HABIT_TRACKER_*``)
3. ``config.json`` inside the data directory
4. a built-in default

The data directory is resolved through ``platformdirs`` when it is installed and
falls back to a hand-rolled XDG/AppData lookup otherwise, so the core stays
dependency-free.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

APP_NAME = "habit-tracker"
APP_TITLE = "Habit Tracker"
DEFAULT_GOAL = 5
DEFAULT_BACKEND = "json"
BACKENDS = ("json", "sqlite")
CONFIG_FILENAME = "config.json"

ENV_DATA_DIR = "HABIT_TRACKER_DATA_DIR"
ENV_BACKEND = "HABIT_TRACKER_BACKEND"
ENV_TZ = "HABIT_TRACKER_TZ"
ENV_WEBHOOK = "HABIT_TRACKER_WEBHOOK_URL"
ENV_THEME = "HABIT_TRACKER_THEME"
THEMES = ("system", "dark", "light")
DEFAULT_THEME = "system"

log = logging.getLogger(__name__)


class ConfigError(RuntimeError):
    """Raised when the environment or config file cannot be honoured."""


@dataclass(frozen=True)
class Settings:
    """Fully resolved runtime settings."""

    data_dir: Path
    backend: str = DEFAULT_BACKEND
    timezone: str | None = None
    webhook_url: str | None = None
    theme: str = DEFAULT_THEME

    @property
    def data_file(self) -> Path:
        return data_file(self.data_dir, self.backend)

    @property
    def config_file(self) -> Path:
        return self.data_dir / CONFIG_FILENAME


def resolve_data_dir(data_dir: str | Path | None = None) -> Path:
    """Resolve the data directory from an explicit value, the environment, or the default."""
    if data_dir is not None:
        return Path(data_dir).expanduser()
    if os.environ.get(ENV_DATA_DIR):
        return Path(os.environ[ENV_DATA_DIR]).expanduser()
    return default_data_dir()


def data_file(data_dir: str | Path | None = None, backend: str = DEFAULT_BACKEND) -> Path:
    """Path of the data file for a backend, honouring ``HABIT_TRACKER_DATA_DIR``."""
    base = resolve_data_dir(data_dir)
    suffix = ".sqlite3" if backend == "sqlite" else ".json"
    return base / f"data{suffix}"


def _fallback_data_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
    else:
        base = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(base).expanduser() / APP_NAME


def default_data_dir() -> Path:
    """Platform-appropriate data directory, honouring ``platformdirs`` if present."""
    try:
        from platformdirs import user_data_path
    except ImportError:
        return _fallback_data_dir()
    return Path(user_data_path(APP_NAME, appauthor=False, ensure_exists=False))


def _read_config_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Ignoring unreadable config file %s: %s", path, exc)
        return {}
    return loaded if isinstance(loaded, dict) else {}


def resolve_settings(
    data_dir: str | Path | None = None,
    backend: str | None = None,
    timezone: str | None = None,
) -> Settings:
    """Combine flags, environment and config file into final :class:`Settings`."""
    base = resolve_data_dir(data_dir)
    file_config = _read_config_file(base / CONFIG_FILENAME)

    chosen_backend = backend or os.environ.get(ENV_BACKEND) or file_config.get("backend")
    if not chosen_backend:
        chosen_backend = DEFAULT_BACKEND
    if chosen_backend not in BACKENDS:
        raise ConfigError(
            f"Unknown backend {chosen_backend!r}. Choose one of: {', '.join(BACKENDS)}."
        )

    chosen_tz = timezone or os.environ.get(ENV_TZ) or file_config.get("timezone")
    if chosen_tz is not None:
        chosen_tz = str(chosen_tz).strip() or None

    if chosen_tz is not None:
        load_timezone(chosen_tz)

    webhook = os.environ.get(ENV_WEBHOOK) or file_config.get("webhook_url")
    if webhook is not None:
        webhook = str(webhook).strip() or None

    theme = os.environ.get(ENV_THEME) or file_config.get("theme") or DEFAULT_THEME
    theme = str(theme).strip().lower() or DEFAULT_THEME
    if theme not in THEMES:
        raise ConfigError(f"Unknown theme {theme!r}. Choose one of: {', '.join(THEMES)}.")

    return Settings(
        data_dir=base,
        backend=chosen_backend,
        timezone=chosen_tz,
        webhook_url=webhook,
        theme=theme,
    )


def load_timezone(name: str) -> ZoneInfo:
    """Return a :class:`ZoneInfo` for ``name`` or raise a friendly error."""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ConfigError(
            f"Unknown timezone {name!r}. Use an IANA name such as 'Europe/London' or 'UTC'. "
            "On Windows the timezone database comes from the 'tzdata' package."
        ) from exc


def now(timezone: str | None = None) -> datetime:
    """Current local time, or current time in ``timezone`` when one is given."""
    if timezone:
        return datetime.now(load_timezone(timezone))
    return datetime.now().astimezone()


def today(timezone: str | None = None) -> date:
    """Current date, honouring the configured timezone."""
    return now(timezone).date()
