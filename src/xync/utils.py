"""Shared utility functions for xync."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

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
