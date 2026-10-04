"""Import and export of the full data document as portable JSON.

The core functions are free of Tkinter so the CLI and tests can use them
headlessly. The ``*_dialog`` helpers wrap them in native file pickers and import
Tkinter lazily.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import storage

EXPORT_SUFFIX = ".json"
FILETYPES = [("JSON files", "*.json"), ("All files", "*.*")]


class BackupError(RuntimeError):
    """Raised when a backup cannot be written or read."""


def export_to(path: str | Path, data: dict | None = None) -> Path:
    """Write ``data`` to ``path`` as JSON. Returns the written path."""
    target = Path(path).expanduser()
    payload = storage.ensure_schema(data if data is not None else storage.load_data())
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    except OSError as exc:
        raise BackupError(f"Could not export to {target}: {exc}") from exc
    return target


def import_from(path: str | Path) -> dict:
    """Read a JSON export and return validated state. Never writes anything."""
    source = Path(path).expanduser()
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BackupError(f"No such file: {source}") from exc
    except json.JSONDecodeError as exc:
        raise BackupError(f"{source.name} is not valid JSON: {exc}") from exc
    except OSError as exc:
        raise BackupError(f"Could not read {source}: {exc}") from exc

    if not isinstance(raw, dict):
        raise BackupError(f"{source.name} does not contain a habit tracker export")
    return storage.ensure_schema(raw)


def export_dialog(parent=None) -> Path | None:
    """Ask for a destination and write an export. ``None`` if cancelled."""
    from tkinter import filedialog

    filename = filedialog.asksaveasfilename(
        parent=parent,
        defaultextension=EXPORT_SUFFIX,
        filetypes=FILETYPES,
        title="Export data",
    )
    if not filename:
        return None
    return export_to(filename)


def import_dialog(parent=None) -> dict | None:
    """Ask for a file, read it and write it into the live store. ``None`` if cancelled."""
    from tkinter import filedialog

    filename = filedialog.askopenfilename(parent=parent, filetypes=FILETYPES, title="Import data")
    if not filename:
        return None
    data = import_from(filename)
    storage.save_data(data)
    return data
