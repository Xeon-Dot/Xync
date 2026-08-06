"""Discord webhook notification support for xync."""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from xync.models import DiscordConfig, SyncStatus

logger = logging.getLogger(__name__)


def send_discord_message(webhook_url: str, content: str) -> bool:
    """Send a message via a Discord webhook.

    Returns *True* on success, *False* on failure (errors are logged, not raised).
    """
    try:
        response = httpx.post(webhook_url, json={"content": content}, timeout=10)
        response.raise_for_status()
        return True
    except (httpx.HTTPError, OSError) as exc:
        logger.warning("Failed to send Discord notification: %s", exc)
        return False


def notify_sync_start(
    discord_cfg: DiscordConfig,
    mirror_name: str,
) -> None:
    """Send a Discord notification when a sync starts.

    Silently skips when ``webhook_url`` is not set, or when
    ``notify_on_start`` is *False*.
    """
    if not discord_cfg.webhook_url:
        return
    if not discord_cfg.notify_on_start:
        return

    content = f"🔄 xync: [{mirror_name}] SYNC STARTED"
    send_discord_message(discord_cfg.webhook_url, content)


def notify_sync_finish(
    discord_cfg: DiscordConfig,
    mirror_name: str,
    status: SyncStatus,
    duration_seconds: float,
    error: Optional[str] = None,
) -> None:
    """Send a Discord notification when a sync finishes (regardless of result).

    Silently skips when ``webhook_url`` is not set, or when
    ``notify_on_finish`` is *False*.
    """
    if not discord_cfg.webhook_url:
        return
    if not discord_cfg.notify_on_finish:
        return

    status_emoji = "✅" if status == SyncStatus.SUCCESS else "❌"
    content = (
        f"{status_emoji} xync: [{mirror_name}] SYNC FINISHED ({status.value.upper()})\n"  # noqa: E501
        f"Duration: {duration_seconds:.1f}s"
    )
    if error:
        content += f"\nError: {error}"

    send_discord_message(discord_cfg.webhook_url, content)


def notify_sync_progress(
    discord_cfg: DiscordConfig,
    mirror_name: str,
    progress_pct: int,
) -> None:
    """Send a Discord notification for a sync progress milestone.

    Silently skips when ``webhook_url`` is not set, or when
    ``notify_on_progress`` is *False*.
    """
    if not discord_cfg.webhook_url:
        return
    if not discord_cfg.notify_on_progress:
        return

    content = f"📊 xync: [{mirror_name}] progress {progress_pct}%"
    send_discord_message(discord_cfg.webhook_url, content)


def notify_disk_usage_warning(
    discord_cfg: DiscordConfig,
    mirror_name: str,
    usage_percent: float,
    threshold_percent: int,
    path: str,
) -> None:
    """Send a Discord warning when mirror disk usage is above the threshold."""
    if not discord_cfg.webhook_url:
        return
    if not discord_cfg.notify_on_failure:
        return

    content = (
        f"⚠️ xync: [{mirror_name}] disk usage warning\n"
        f"Usage: {usage_percent:.1f}% "
        f"(threshold: {threshold_percent}%)\n"
        f"Path: {path}"
    )
    send_discord_message(discord_cfg.webhook_url, content)


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
    """Send a Discord notification for a sync result if Discord is configured.

    Silently skips when ``webhook_url`` is not set, or when the relevant
    ``notify_on_*`` flag is *False*.
    """
    if not discord_cfg.webhook_url:
        return

    if status == SyncStatus.SUCCESS and not discord_cfg.notify_on_success:
        return
    if status == SyncStatus.FAILED and not discord_cfg.notify_on_failure:
        return

    status_emoji = "✅" if status == SyncStatus.SUCCESS else "❌"
    content = (
        f"{status_emoji} xync: [{mirror_name}] {status.value.upper()}\n"
        f"Duration: {duration_seconds:.1f}s"
    )
    if error:
        content += f"\nError: {error}"

    send_discord_message(discord_cfg.webhook_url, content)
