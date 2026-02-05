"""Configuration management for blurcam."""

import json
import os
from pathlib import Path
from typing import Any

CONFIG_DIR = Path.home() / ".config" / "blurcam"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "blur": 35,
    "threshold": 0.5,
    "input": 0,
    "output": "/dev/video10",
    "width": 640,
    "height": 480,
    "fps": 30,
}


def get_config_path() -> Path:
    """Get the config file path, creating directory if needed."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return CONFIG_FILE


def load_config() -> dict[str, Any]:
    """Load config from file, returning defaults if not found."""
    config_path = get_config_path()
    if config_path.exists():
        try:
            with open(config_path) as f:
                saved = json.load(f)
                # Merge with defaults for any missing keys
                return {**DEFAULT_CONFIG, **saved}
        except (json.JSONDecodeError, IOError):
            pass
    return DEFAULT_CONFIG.copy()


def save_config(config: dict[str, Any]) -> None:
    """Save config to file."""
    config_path = get_config_path()
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)


def update_config(**kwargs) -> dict[str, Any]:
    """Update specific config values and save."""
    config = load_config()
    for key, value in kwargs.items():
        if value is not None and key in DEFAULT_CONFIG:
            config[key] = value
    save_config(config)
    return config


def get_config_mtime() -> float:
    """Get config file modification time, or 0 if not exists."""
    config_path = get_config_path()
    if config_path.exists():
        return config_path.stat().st_mtime
    return 0
