"""Configuration file management for xync."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Optional

import tomli_w

from xync.models import xyncConfig

_DEFAULT_CONFIG_DIR = Path.home() / ".config" / "xync"
_CONFIG_FILE = "config.toml"


def get_config_dir(config_dir: Optional[Path] = None) -> Path:
    """Return the configuration directory, creating it if needed."""
    path = config_dir or _DEFAULT_CONFIG_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_config_path(config_dir: Optional[Path] = None) -> Path:
    """Return the path to the config TOML file."""
    return get_config_dir(config_dir) / _CONFIG_FILE


def load_config(config_dir: Optional[Path] = None) -> xyncConfig:
    """Load and return the xync configuration from disk.

    If the config file does not exist, returns a default :class:`xyncConfig`.
    """
    path = get_config_path(config_dir)
    if not path.exists():
        return xyncConfig()  # pyright: ignore[reportCallIssue]
    with path.open("rb") as fh:
        raw = tomllib.load(fh)
    mirrors_raw = raw.get("mirrors", {})
    for name, entry in mirrors_raw.items():
        entry.setdefault("name", name)
    return xyncConfig.model_validate(
        {
            "version": raw.get("version", 1),
            "global_config": raw.get("global", {}),
            "mirrors": mirrors_raw,
        }
    )


def save_config(cfg: xyncConfig, config_dir: Optional[Path] = None) -> None:
    """Persist the xync configuration to disk."""
    path = get_config_path(config_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = cfg.model_dump(mode="json", exclude_none=True)
    data["global"] = data.pop("global_config")
    with path.open("wb") as fh:
        tomli_w.dump(data, fh)
