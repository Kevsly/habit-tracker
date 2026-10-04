"""The desktop window's widget styling.

Every colour comes from a :class:`habit_tracker.theme.Palette` and is applied to
``tkinter.ttk`` through the ``clam`` theme, which ships with Tk everywhere. The
native Windows and macOS themes ignore ``background`` on most widgets, which is
why the theme is switched rather than merely configured.

There is no third-party dependency here on purpose. ``ttkbootstrap`` used to
live in this role, but version 2 replaced its ``ttk`` theme with a separate
widget library, so it is no longer a drop-in and the palette is applied
directly instead. That also means dark mode costs nothing to install.

The two rules for callers:

1. never hardcode a hex colour, take it from the palette
2. plain ``tk`` widgets are not themed by ttk, so pass ``palette`` to anything
   built from ``tk.Label`` or ``tk.Text``
"""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import ttk

from .theme import Palette

log = logging.getLogger(__name__)

BASE_TTK_THEME = "clam"


def apply_theme(palette: Palette) -> ttk.Style:
    """Install the palette as the default ttk style and return it.

    Safe to call again at runtime to switch between light and dark.
    """
    style = ttk.Style()
    if BASE_TTK_THEME in style.theme_names():
        style.theme_use(BASE_TTK_THEME)

    base = {
        "background": palette.background,
        "foreground": palette.text,
        "fieldbackground": palette.surface,
        "bordercolor": palette.border,
        "lightcolor": palette.border,
        "darkcolor": palette.border,
        "troughcolor": palette.surface_alt,
        "insertcolor": palette.text,
        "selectbackground": palette.accent,
        "selectforeground": palette.on_accent,
        "font": ("TkDefaultFont",),
    }
    style.configure(".", **base)

    style.configure("TFrame", background=palette.background)
    style.configure("TLabel", background=palette.background, foreground=palette.text)
    style.configure("Muted.TLabel", background=palette.background, foreground=palette.text_muted)
    style.configure("Card.TFrame", background=palette.surface)

    style.configure(
        "TButton",
        background=palette.surface_alt,
        foreground=palette.text,
        borderwidth=0,
        focusthickness=0,
        focuscolor=palette.background,
        padding=(10, 5),
    )
    style.map(
        "TButton",
        background=[("pressed", palette.accent), ("active", palette.surface_alt)],
        foreground=[("pressed", palette.on_accent), ("disabled", palette.text_muted)],
    )

    style.configure(
        "TEntry",
        fieldbackground=palette.surface,
        foreground=palette.text,
        insertcolor=palette.text,
        borderwidth=1,
        relief="solid",
        padding=4,
    )
    style.configure(
        "TCombobox",
        fieldbackground=palette.surface,
        background=palette.surface,
        foreground=palette.text,
        arrowcolor=palette.text,
        borderwidth=1,
        relief="solid",
        padding=3,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", palette.surface)],
        foreground=[("readonly", palette.text)],
        selectbackground=[("readonly", palette.surface)],
        selectforeground=[("readonly", palette.text)],
    )
    root = style.master
    if hasattr(root, "option_add"):
        # The dropdown list is a plain Tk listbox, so it needs an option database entry.
        root.option_add("*TCombobox*Listbox.background", palette.surface)
        root.option_add("*TCombobox*Listbox.foreground", palette.text)
        root.option_add("*TCombobox*Listbox.selectBackground", palette.accent)
        root.option_add("*TCombobox*Listbox.selectForeground", palette.on_accent)

    style.configure(
        "Treeview",
        background=palette.surface,
        fieldbackground=palette.surface,
        foreground=palette.text,
        borderwidth=0,
        rowheight=26,
    )
    style.map(
        "Treeview",
        background=[("selected", palette.accent)],
        foreground=[("selected", palette.on_accent)],
    )
    style.configure(
        "Treeview.Heading",
        background=palette.surface_alt,
        foreground=palette.text_muted,
        relief="flat",
        borderwidth=0,
        padding=(6, 5),
    )
    style.map(
        "Treeview.Heading",
        background=[("active", palette.accent)],
        foreground=[("active", palette.on_accent)],
    )

    style.configure(
        "TNotebook", background=palette.background, borderwidth=0, tabmargins=(0, 0, 0, 0)
    )
    style.configure(
        "TNotebook.Tab",
        background=palette.surface_alt,
        foreground=palette.text_muted,
        borderwidth=0,
        focuscolor=palette.surface_alt,
        padding=(16, 8),
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", palette.background)],
        foreground=[("selected", palette.text)],
        expand=[("selected", (0, 0, 0, 0))],
    )

    style.configure(
        "Horizontal.TProgressbar",
        background=palette.accent,
        troughcolor=palette.surface_alt,
        bordercolor=palette.surface_alt,
        lightcolor=palette.accent,
        darkcolor=palette.accent,
        borderwidth=0,
        thickness=10,
    )
    style.configure(
        "Vertical.TScrollbar",
        background=palette.surface_alt,
        troughcolor=palette.background,
        bordercolor=palette.background,
        arrowcolor=palette.text_muted,
        borderwidth=0,
    )
    style.configure(
        "Horizontal.TScrollbar",
        background=palette.surface_alt,
        troughcolor=palette.background,
        bordercolor=palette.background,
        arrowcolor=palette.text_muted,
        borderwidth=0,
    )

    log.debug("Applied the %s theme", palette.name)
    return style


def style_swatch(widget: tk.Misc, background: str) -> None:
    """Set the background of a plain ``tk`` widget, which ttk cannot reach."""
    try:
        widget.configure(background=background)
    except tk.TclError:  # pragma: no cover - a widget without a background option
        log.debug("Could not set the background of %r", widget, exc_info=True)
