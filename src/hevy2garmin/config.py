"""Configuration management — load/save settings from ~/.hevy2garmin/config.json."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("hevy2garmin")

CONFIG_DIR = Path("~/.hevy2garmin").expanduser()
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "hevy_api_key": "",
    "garmin_email": "",
    "garmin_token_dir": "~/.garminconnect",
    "user_profile": {
        "weight_kg": 80.0,
        "birth_year": 1990,
        "sex": "male",
        "vo2max": 45.0,
    },
    "sync": {
        "default_limit": 10,
        "skip_existing": True,
    },
    "auto_sync": {
        "enabled": False,
        "interval_minutes": 120,
    },
    "timing": {
        "working_set_seconds": 40,
        "warmup_set_seconds": 25,
        "rest_between_sets_seconds": 75,
        "rest_between_exercises_seconds": 120,
    },
}


def load_config() -> dict[str, Any]:
    """Load config from file. Returns defaults merged with saved values."""
    config = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy defaults
    if CONFIG_FILE.exists():
        try:
            saved = json.loads(CONFIG_FILE.read_text())
            _deep_merge(config, saved)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Could not load config: %s", e)
    return config


def save_config(config: dict[str, Any]) -> None:
    """Save config to file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2))


def get(key: str, default: Any = None) -> Any:
    """Get a top-level config value."""
    return load_config().get(key, default)


def is_configured() -> bool:
    """Check if initial setup has been done (API key exists)."""
    config = load_config()
    return bool(config.get("hevy_api_key"))


def _deep_merge(base: dict, override: dict) -> None:
    """Merge override into base recursively (mutates base)."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
