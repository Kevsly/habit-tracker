from __future__ import annotations

import json

import pytest

from habit_tracker import config
from habit_tracker.config import ConfigError

ENV_VARS = (config.ENV_DATA_DIR, config.ENV_BACKEND, config.ENV_TZ)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    yield


class TestResolution:
    def test_explicit_data_dir_wins(self, tmp_path):
        assert config.resolve_settings(tmp_path).data_dir == tmp_path

    def test_data_dir_expands_the_user_home(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        assert "~" not in str(config.resolve_settings("~").data_dir)

    def test_environment_variable_is_used_when_no_flag(self, tmp_path, monkeypatch):
        monkeypatch.setenv(config.ENV_DATA_DIR, str(tmp_path / "from-env"))
        assert config.resolve_settings().data_dir == tmp_path / "from-env"

    def test_default_backend_is_json(self, tmp_path):
        assert config.resolve_settings(tmp_path).backend == "json"

    def test_backend_flag_is_honoured(self, tmp_path):
        assert config.resolve_settings(tmp_path, backend="sqlite").backend == "sqlite"

    def test_backend_from_the_environment(self, tmp_path, monkeypatch):
        monkeypatch.setenv(config.ENV_BACKEND, "sqlite")
        assert config.resolve_settings(tmp_path).backend == "sqlite"

    def test_backend_from_the_config_file(self, tmp_path):
        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / config.CONFIG_FILENAME).write_text(
            json.dumps({"backend": "sqlite"}), encoding="utf-8"
        )
        assert config.resolve_settings(tmp_path).backend == "sqlite"

    def test_unknown_backend_is_rejected(self, tmp_path):
        with pytest.raises(ConfigError, match="Unknown backend"):
            config.resolve_settings(tmp_path, backend="mysql")

    def test_unparseable_config_file_is_ignored(self, tmp_path):
        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / config.CONFIG_FILENAME).write_text("{ not json", encoding="utf-8")
        assert config.resolve_settings(tmp_path).backend == "json"

    def test_non_object_config_file_is_ignored(self, tmp_path):
        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / config.CONFIG_FILENAME).write_text("[1, 2]", encoding="utf-8")
        assert config.resolve_settings(tmp_path).backend == "json"


class TestDataFile:
    def test_json_path(self, tmp_path):
        assert config.data_file(tmp_path, "json") == tmp_path / "data.json"

    def test_sqlite_path(self, tmp_path):
        assert config.data_file(tmp_path, "sqlite") == tmp_path / "data.sqlite3"

    def test_settings_expose_the_same_path(self, tmp_path):
        settings = config.resolve_settings(tmp_path, backend="sqlite")
        assert settings.data_file == tmp_path / "data.sqlite3"

    def test_config_file_lives_in_the_data_dir(self, tmp_path):
        assert config.resolve_settings(tmp_path).config_file == tmp_path / config.CONFIG_FILENAME


class TestTimezone:
    def test_no_timezone_means_local(self):
        assert config.resolve_settings().timezone is None

    def test_timezone_flag_is_honoured(self, tmp_path):
        assert config.resolve_settings(tmp_path, timezone="UTC").timezone == "UTC"

    def test_timezone_from_the_environment(self, tmp_path, monkeypatch):
        monkeypatch.setenv(config.ENV_TZ, "Europe/London")
        assert config.resolve_settings(tmp_path).timezone == "Europe/London"

    def test_timezone_from_the_config_file(self, tmp_path):
        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / config.CONFIG_FILENAME).write_text(
            json.dumps({"timezone": "Asia/Tokyo"}), encoding="utf-8"
        )
        assert config.resolve_settings(tmp_path).timezone == "Asia/Tokyo"

    def test_blank_timezone_becomes_none(self, tmp_path):
        assert config.resolve_settings(tmp_path, timezone="  ").timezone is None

    def test_unknown_timezone_is_rejected(self, tmp_path):
        with pytest.raises(ConfigError, match="Unknown timezone"):
            config.resolve_settings(tmp_path, timezone="Mars/Olympus")

    def test_load_timezone_returns_a_zoneinfo(self):
        from zoneinfo import ZoneInfo

        assert isinstance(config.load_timezone("UTC"), ZoneInfo)


class TestToday:
    def test_default_today_is_the_local_date(self):
        from datetime import date

        assert config.today() == date.today()

    @pytest.mark.parametrize("zone", ["UTC", "Europe/London", "Asia/Tokyo", "America/New_York"])
    def test_today_applies_the_named_zone(self, zone):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        assert config.today(zone) == datetime.now(ZoneInfo(zone)).date()

    def test_today_is_stable_across_calls(self):
        assert config.today("UTC") == config.today("UTC")

    def test_today_rejects_an_unknown_zone(self):
        with pytest.raises(ConfigError, match="Unknown timezone"):
            config.today("Mars/Olympus")


class TestSettingsDataclass:
    def test_is_frozen(self, tmp_path):
        settings = config.resolve_settings(tmp_path)
        with pytest.raises(AttributeError):
            settings.backend = "sqlite"
