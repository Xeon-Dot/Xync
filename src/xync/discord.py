"""Discord webhook notification support for xync."""

from __future__ import annotations

from typing import Optional

from xync.models import DiscordConfig, SyncStatus
from xync.notify import (
    disk_text,
    finish_text,
    post_json,
    progress_text,
    result_text,
    start_text,
)


def send_discord_message(webhook_url: str, content: str) -> bool:
    """Send a message via a Discord webhook.

    Returns *True* on success, *False* on failure (errors are logged, not raised).
    """
    return post_json(webhook_url, {"content": content})


def notify_sync_start(discord_cfg: DiscordConfig, mirror_name: str) -> None:
    """Send a Discord notification when a sync starts."""
    if not discord_cfg.webhook_url or not discord_cfg.notify_on_start:
        return
    send_discord_message(discord_cfg.webhook_url, start_text(mirror_name))


def notify_sync_finish(
    discord_cfg: DiscordConfig,
    mirror_name: str,
    status: SyncStatus,
    duration_seconds: float,
    error: Optional[str] = None,
) -> None:
    """Send a Discord notification when a sync finishes (regardless of result)."""
    if not discord_cfg.webhook_url or not discord_cfg.notify_on_finish:
        return
    send_discord_message(
        discord_cfg.webhook_url,
        finish_text(mirror_name, status, duration_seconds, error),
    )


def notify_sync_progress(
    discord_cfg: DiscordConfig,
    mirror_name: str,
    progress_pct: int,
) -> None:
    """Send a Discord notification for a sync progress milestone."""
    if not discord_cfg.webhook_url or not discord_cfg.notify_on_progress:
        return
    send_discord_message(
        discord_cfg.webhook_url, progress_text(mirror_name, progress_pct)
    )


def notify_disk_usage_warning(
    discord_cfg: DiscordConfig,
    mirror_name: str,
    usage_percent: float,
    threshold_percent: int,
    path: str,
) -> None:
    """Send a Discord warning when mirror disk usage is above the threshold."""
    if not discord_cfg.webhook_url or not discord_cfg.notify_on_failure:
        return
    send_discord_message(
        discord_cfg.webhook_url,
        disk_text(mirror_name, usage_percent, threshold_percent, path),
    )


def send_test_notification(discord_cfg: DiscordConfig) -> bool:
    """Send a test Discord notification and return whether it was delivered."""
    if not discord_cfg.webhook_url:
        return False
    return send_discord_message(discord_cfg.webhook_url, "✅ xync test notification")


def notify_sync_result(
    discord_cfg: DiscordConfig,
    mirror_name: str,
    status: SyncStatus,
    duration_seconds: float,
    error: Optional[str] = None,
) -> None:
    """Send a Discord notification for a sync result if Discord is configured."""
    if not discord_cfg.webhook_url:
        return
    if status == SyncStatus.SUCCESS and not discord_cfg.notify_on_success:
        return
    if status == SyncStatus.FAILED and not discord_cfg.notify_on_failure:
        return
    send_discord_message(
        discord_cfg.webhook_url,
        result_text(mirror_name, status, duration_seconds, error),
    )
