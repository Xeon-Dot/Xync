"""Shared utility functions for xync."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from xync.config import save_config
from xync.models import SyncStatus


def format_size(size_bytes: int) -> str:
    """Convert bytes to human readable size string."""
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    size = float(size_bytes)
    for unit in units:
        if abs(size) < 1024.0:
            return f"{size:.2f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024.0
    return f"{size:.2f} EiB"


def get_directory_size(path: str) -> int:
    """Calculate total size of a directory in bytes."""
    total = 0
    try:
        p = Path(path)
        if p.exists():
            for entry in p.rglob("*"):
                if entry.is_file():
                    total += entry.stat().st_size
    except (OSError, PermissionError):
        pass
    return total


def disk_usage_for_path(path: str) -> Optional[tuple[float, Path]]:
    """Return ``(used_percent, filesystem_path)`` for the filesystem at *path*.

    Returns ``None`` if the path does not exist or usage cannot be determined.
    """
    target = Path(path)
    usage_path = target if target.exists() else target.parent
    if not usage_path.exists():
        return None
    try:
        usage = shutil.disk_usage(usage_path)
    except OSError:
        return None
    if usage.total == 0:
        return None
    return usage.used / usage.total * 100, usage_path


def record_sync_result(cfg, config_dir, mirror, result) -> None:
    """Record a completed sync result on the mirror and persist the config."""
    mirror.last_sync = datetime.now(tz=timezone.utc)
    mirror.last_status = result.status
    if result.status == SyncStatus.SUCCESS and result.size_bytes is not None:
        mirror.previous_size = mirror.last_size
        mirror.last_size = result.size_bytes
    cfg.mirrors[mirror.name] = mirror
    save_config(cfg, config_dir)


def notify_disk_warning_if_needed(cfg, mirror) -> None:
    """Send Telegram/Discord disk-usage warnings if the mirror filesystem is full."""
    from xync.discord import notify_disk_usage_warning as _discord_disk
    from xync.telegram import notify_disk_usage_warning as _telegram_disk

    usage = disk_usage_for_path(mirror.local_path)
    if usage is None:
        return
    usage_percent, usage_path = usage
    threshold = cfg.global_config.disk_usage_warning_percent
    if usage_percent < threshold:
        return
    _telegram_disk(
        cfg.global_config.telegram,
        mirror.name,
        usage_percent,
        threshold,
        str(usage_path),
    )
    _discord_disk(
        cfg.global_config.discord,
        mirror.name,
        usage_percent,
        threshold,
        str(usage_path),
    )


def make_progress_callback(
    telegram_cfg,
    discord_cfg,
    name: str,
) -> Callable[[int], None]:
    """Return a progress callback that fires Telegram/Discord progress notifications.

    The caller (``xync.sync._run_with_progress``) already deduplicates milestones,
    so this callback simply forwards each percentage it is given.
    """
    from xync.discord import notify_sync_progress as _discord_progress
    from xync.telegram import notify_sync_progress as _telegram_progress

    def _cb(pct: int) -> None:
        _telegram_progress(telegram_cfg, name, pct)
        _discord_progress(discord_cfg, name, pct)

    return _cb
