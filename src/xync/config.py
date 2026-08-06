"""Configuration file management for xync."""

from __future__ import annotations

import tomllib
from datetime import datetime
from pathlib import Path
from typing import Optional

import tomli_w

from xync.models import (
    DiscordConfig,
    GlobalConfig,
    Mirror,
    MirrorType,
    TelegramConfig,
    xyncConfig,
)

_DEFAULT_CONFIG_DIR = Path.home() / ".config" / "xync"
_CONFIG_FILE = "config.toml"
_NOTIFICATION_FLAG_DEFAULTS = {
    "notify_on_success": True,
    "notify_on_failure": True,
    "notify_on_start": False,
    "notify_on_finish": False,
    "notify_on_progress": False,
}


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
    return _parse_raw(raw)


def save_config(cfg: xyncConfig, config_dir: Optional[Path] = None) -> None:
    """Persist the xync configuration to disk."""
    path = get_config_path(config_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = _serialise(cfg)
    with path.open("wb") as fh:
        tomli_w.dump(raw, fh)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _serialise(cfg: xyncConfig) -> dict:
    """Convert an :class:`xyncConfig` to a plain dict suitable for TOML."""
    data: dict = {
        "version": cfg.version,
        "global": {
            "default_rsync_options": cfg.global_config.default_rsync_options,
            "log_dir": cfg.global_config.log_dir,
            "max_log_files": cfg.global_config.max_log_files,
            "parallel_jobs": cfg.global_config.parallel_jobs,
            "daemon_interval": cfg.global_config.daemon_interval,
            "api_enabled": cfg.global_config.api_enabled,
            "api_port": cfg.global_config.api_port,
            "daemon_schedule": cfg.global_config.daemon_schedule or "",
            "disk_usage_warning_percent": (
                cfg.global_config.disk_usage_warning_percent
            ),
            "telegram": _serialise_notification_config(
                cfg.global_config.telegram,
                ("bot_token", "chat_id"),
            ),
            "discord": _serialise_notification_config(
                cfg.global_config.discord,
                ("webhook_url",),
            ),
        },
        "mirrors": {},
    }
    for name, mirror in cfg.mirrors.items():
        entry: dict = {
            "url": mirror.url,
            "local_path": mirror.local_path,
            "mirror_type": mirror.mirror_type.value,
            "enabled": mirror.enabled,
            "description": mirror.description,
            "rsync_options": mirror.rsync_options,
            "http_options": mirror.http_options,
        }
        if mirror.bandwidth_limit is not None:
            entry["bandwidth_limit"] = mirror.bandwidth_limit
        if mirror.last_sync is not None:
            entry["last_sync"] = mirror.last_sync.isoformat()
        entry["last_status"] = mirror.last_status.value
        if mirror.last_size is not None:
            entry["last_size"] = mirror.last_size
        if mirror.previous_size is not None:
            entry["previous_size"] = mirror.previous_size
        data["mirrors"][name] = entry
    return data


def _parse_raw(raw: dict) -> xyncConfig:
    """Parse a raw TOML dict into an :class:`xyncConfig`."""
    global_raw = raw.get("global", {})
    telegram_raw = global_raw.get("telegram", {})
    telegram = TelegramConfig(
        bot_token=telegram_raw.get("bot_token") or None,
        chat_id=telegram_raw.get("chat_id") or None,
        **_parse_notification_flags(telegram_raw),
    )
    discord_raw = global_raw.get("discord", {})
    discord = DiscordConfig(
        webhook_url=discord_raw.get("webhook_url") or None,
        **_parse_notification_flags(discord_raw),
    )
    global_config = GlobalConfig(
        default_rsync_options=global_raw.get(
            "default_rsync_options", ["-avz", "--delete"]
        ),
        log_dir=global_raw.get("log_dir", ""),
        max_log_files=global_raw.get("max_log_files", 30),
        parallel_jobs=global_raw.get("parallel_jobs", 1),
        daemon_interval=global_raw.get("daemon_interval", 3600),
        api_enabled=global_raw.get("api_enabled", False),
        api_port=global_raw.get("api_port", 58080),
        daemon_schedule=global_raw.get("daemon_schedule") or None,
        disk_usage_warning_percent=global_raw.get("disk_usage_warning_percent", 90),
        telegram=telegram,
        discord=discord,
    )

    mirrors: dict[str, Mirror] = {}
    for name, mraw in raw.get("mirrors", {}).items():
        last_sync_raw = mraw.get("last_sync")
        last_sync = datetime.fromisoformat(last_sync_raw) if last_sync_raw else None
        mirrors[name] = Mirror(
            name=name,
            url=mraw["url"],
            local_path=mraw["local_path"],
            mirror_type=MirrorType(mraw.get("mirror_type", "rsync")),
            enabled=mraw.get("enabled", True),
            description=mraw.get("description", ""),
            rsync_options=mraw.get("rsync_options", ["-avz", "--delete"]),
            http_options=mraw.get("http_options", []),
            bandwidth_limit=mraw.get("bandwidth_limit"),
            last_sync=last_sync,
            last_status=mraw.get("last_status", "never"),
            last_size=mraw.get("last_size"),
            previous_size=mraw.get("previous_size"),
        )

    return xyncConfig(
        version=raw.get("version", 1),
        global_config=global_config,
        mirrors=mirrors,
    )


def _serialise_notification_config(
    notification_cfg: object,
    credential_fields: tuple[str, ...],
) -> dict:
    """Convert Telegram or Discord notification settings to plain TOML data."""
    data = {
        field: getattr(notification_cfg, field) or "" for field in credential_fields
    }
    data.update(
        {flag: getattr(notification_cfg, flag) for flag in _NOTIFICATION_FLAG_DEFAULTS}
    )
    return data


def _parse_notification_flags(raw: dict) -> dict:
    """Parse shared notification flags from a raw config section."""
    return {
        flag: raw.get(flag, default)
        for flag, default in _NOTIFICATION_FLAG_DEFAULTS.items()
    }
