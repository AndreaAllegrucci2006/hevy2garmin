"""Tests for configuration system."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from hevy2garmin.config import (
    DEFAULT_CONFIG,
    is_configured,
    load_config,
    save_config,
)


class TestLoadConfig:
    def test_returns_defaults_when_no_file(self, tmp_path: Path) -> None:
        with patch("hevy2garmin.config.CONFIG_FILE", tmp_path / "missing.json"):
            config = load_config()
            assert config["user_profile"]["weight_kg"] == 80.0
            assert config["timing"]["working_set_seconds"] == 40

    def test_save_load_roundtrip(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        with patch("hevy2garmin.config.CONFIG_DIR", tmp_path), \
             patch("hevy2garmin.config.CONFIG_FILE", config_file):
            original = load_config()
            original["hevy_api_key"] = "test-key-123"
            original["user_profile"]["weight_kg"] = 75.5
            save_config(original)

            loaded = load_config()
            assert loaded["hevy_api_key"] == "test-key-123"
            assert loaded["user_profile"]["weight_kg"] == 75.5

    def test_deep_merge_preserves_defaults(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        # Save partial config (missing timing)
        config_file.write_text(json.dumps({"hevy_api_key": "key", "user_profile": {"weight_kg": 90}}))

        with patch("hevy2garmin.config.CONFIG_FILE", config_file):
            config = load_config()
            assert config["hevy_api_key"] == "key"
            assert config["user_profile"]["weight_kg"] == 90
            # Defaults preserved for unset values
            assert config["user_profile"]["birth_year"] == 1990
            assert config["timing"]["working_set_seconds"] == 40

    def test_corrupt_file_returns_defaults(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text("{corrupt json!!!")

        with patch("hevy2garmin.config.CONFIG_FILE", config_file):
            config = load_config()
            assert config["user_profile"]["weight_kg"] == 80.0


class TestIsConfigured:
    def test_false_without_api_key(self, tmp_path: Path) -> None:
        with patch("hevy2garmin.config.CONFIG_FILE", tmp_path / "missing.json"):
            assert is_configured() is False

    def test_true_with_api_key(self, tmp_path: Path, monkeypatch) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"hevy_api_key": "some-key"}))

        # When DATABASE_URL is set, is_configured also checks for Garmin tokens.
        # Clear it so this test only validates the API key check.
        monkeypatch.delenv("DATABASE_URL", raising=False)

        with patch("hevy2garmin.config.CONFIG_FILE", config_file):
            assert is_configured() is True

    def test_false_with_empty_api_key(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"hevy_api_key": ""}))

        with patch("hevy2garmin.config.CONFIG_FILE", config_file):
            assert is_configured() is False
