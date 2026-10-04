"""Tests for the palette layer and the ttk styling built from it.

No display needed: everything here is data, except the styling tests which are
skipped without one.
"""

from __future__ import annotations

import json

import pytest

from habit_tracker import config, theme

MODES = theme.THEME_MODES


class TestPalettes:
    @pytest.mark.parametrize("palette", [theme.LIGHT, theme.DARK])
    def test_every_colour_is_a_hex_triplet(self, palette):
        for field in theme.Palette.__dataclass_fields__.values():
            if field.name == "name":
                continue
            value = getattr(palette, field.name)
            assert value.startswith("#"), field.name
            assert len(value) == 7, f"{field.name}={value}"

    @pytest.mark.parametrize("palette", [theme.LIGHT, theme.DARK])
    def test_all_colours_are_distinct_where_it_matters(self, palette):
        # surface and background must be separable, or cards vanish.
        assert palette.surface != palette.background
        assert palette.text != palette.surface

    @pytest.mark.parametrize("palette", [theme.LIGHT, theme.DARK])
    def test_accent_text_is_readable_on_accent_and_success(self, palette):
        # A crude luminance check: on_accent must contrast with both fills.
        def brightness(colour: str) -> float:
            red, green, blue = (int(colour[i : i + 2], 16) for i in (1, 3, 5))
            return (0.299 * red + 0.587 * green + 0.114 * blue) / 255

        on_accent = brightness(palette.on_accent)
        for fill in (palette.accent, palette.success):
            assert abs(brightness(fill) - on_accent) > 0.25, fill

    def test_the_two_palettes_are_named(self):
        assert theme.LIGHT.name == "light"
        assert theme.DARK.name == "dark"
        assert theme.PALETTES == {"light": theme.LIGHT, "dark": theme.DARK}


class TestNormaliseMode:
    @pytest.mark.parametrize("value", ["dark", "DARK", " Dark ", "light"])
    def test_it_accepts_and_normalises(self, value):
        assert theme.normalise_mode(value) == value.strip().lower()

    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_empty_means_system(self, value):
        assert theme.normalise_mode(value) == "system"

    @pytest.mark.parametrize("value", ["solarized", "auto", "TRUE"])
    def test_unknown_modes_are_rejected(self, value):
        with pytest.raises(theme.ThemeError, match="Choose one of"):
            theme.normalise_mode(value)


class TestResolvePalette:
    @pytest.mark.parametrize("mode", ["light", "dark"])
    def test_explicit_modes_ignore_the_system(self, mode):
        assert theme.resolve_palette(mode) is theme.PALETTES[mode]

    def test_system_follows_the_desktop(self, monkeypatch):
        for prefers_dark, expected in ((True, "dark"), (False, "light")):
            monkeypatch.setattr(theme, "system_prefers_dark", lambda d=prefers_dark: d)
            assert theme.resolve_palette("system").name == expected

    def test_system_defaults_to_light_when_unknown(self, monkeypatch):
        monkeypatch.setattr(theme, "_windows_prefers_dark", lambda: None)
        monkeypatch.setattr(theme, "_unix_prefers_dark", lambda: None)
        theme.system_prefers_dark.cache_clear()
        assert theme.system_prefers_dark() is False
        theme.system_prefers_dark.cache_clear()

    def test_gtk_theme_env_is_honoured(self, monkeypatch):
        monkeypatch.setattr(theme, "_windows_prefers_dark", lambda: None)
        monkeypatch.setenv("GTK_THEME", "Adwaita-dark")
        assert theme._unix_prefers_dark() is True
        monkeypatch.setenv("GTK_THEME", "Adwaita")
        assert theme._unix_prefers_dark() is False

    def test_system_detection_is_cached(self, monkeypatch):
        calls = []

        def counting() -> bool:
            calls.append(1)
            return False

        monkeypatch.setattr(theme, "_windows_prefers_dark", counting)
        monkeypatch.setattr(theme, "_unix_prefers_dark", lambda: None)
        theme.system_prefers_dark.cache_clear()
        try:
            assert theme.system_prefers_dark() is False
            assert theme.system_prefers_dark() is False
            assert len(calls) == 1, "the platform lookup should happen once"
        finally:
            theme.system_prefers_dark.cache_clear()


class TestSettings:
    def test_the_default_is_system(self, tmp_path):
        assert config.resolve_settings(tmp_path).theme == "system"

    def test_the_config_file_can_set_it(self, tmp_path):
        (tmp_path / config.CONFIG_FILENAME).write_text(
            json.dumps({"theme": "dark"}), encoding="utf-8"
        )
        assert config.resolve_settings(tmp_path).theme == "dark"

    def test_the_environment_wins(self, tmp_path, monkeypatch):
        (tmp_path / config.CONFIG_FILENAME).write_text(
            json.dumps({"theme": "dark"}), encoding="utf-8"
        )
        monkeypatch.setenv(config.ENV_THEME, "light")
        assert config.resolve_settings(tmp_path).theme == "light"

    def test_it_is_normalised(self, tmp_path, monkeypatch):
        monkeypatch.setenv(config.ENV_THEME, "  DARK ")
        assert config.resolve_settings(tmp_path).theme == "dark"

    def test_an_unknown_theme_is_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setenv(config.ENV_THEME, "neon")
        with pytest.raises(config.ConfigError, match="Choose one of"):
            config.resolve_settings(tmp_path)

    def test_an_unreadable_config_falls_back(self, tmp_path):
        (tmp_path / config.CONFIG_FILENAME).write_text("{not json", encoding="utf-8")
        assert config.resolve_settings(tmp_path).theme == "system"


class TestStyling:
    """The ttk styles are applied for real, so these need a display."""

    @staticmethod
    def _root():
        tk = pytest.importorskip("tkinter")
        try:
            root = tk.Tk()
        except tk.TclError:  # pragma: no cover - no display
            pytest.skip("no display available")
        root.withdraw()
        return root

    def test_apply_theme_switches_to_a_styleable_theme(self):
        from habit_tracker import ui

        root = self._root()
        try:
            style = ui.apply_theme(theme.LIGHT)
            assert style.theme_use() == ui.BASE_TTK_THEME
            assert style.lookup("TLabel", "background") == theme.LIGHT.background
        finally:
            root.destroy()

    def test_switching_palette_updates_the_live_styles(self):
        from habit_tracker import ui

        root = self._root()
        try:
            ui.apply_theme(theme.LIGHT)
            light_button = style_value("TButton", "background")
            ui.apply_theme(theme.DARK)
            assert style_value("TButton", "background") != light_button
            assert style_value("TButton", "background") == theme.DARK.surface_alt
        finally:
            root.destroy()

    def test_every_widget_kind_builds_in_both_modes(self):
        from tkinter import ttk

        from habit_tracker import ui

        root = self._root()
        try:
            for palette in (theme.LIGHT, theme.DARK):
                ui.apply_theme(palette)
                frame = ttk.Frame(root)
                frame.pack()
                ttk.Label(frame, text="x").pack()
                ttk.Button(frame, text="x").pack()
                ttk.Entry(frame).pack()
                ttk.Combobox(frame, state="readonly", values=["a"]).pack()
                notebook = ttk.Notebook(frame)
                notebook.pack()
                notebook.add(ttk.Frame(notebook), text="tab")
                ttk.Treeview(notebook, columns=("a",)).pack()
                ttk.Scrollbar(frame).pack()
                ttk.Progressbar(frame).pack()
                root.update_idletasks()
        finally:
            root.destroy()


def style_value(style_name: str, option: str) -> str:
    from tkinter import ttk

    return ttk.Style().lookup(style_name, option) or ""
