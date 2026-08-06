"""Telegram notification support for xync."""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from xync.models import SyncStatus, TelegramConfig

logger = logging.getLogger(__name__)

_TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


def send_telegram_message(bot_token: str, chat_id: str, text: str) -> bool:
    """Send a message via the Telegram Bot API.

    Returns *True* on success, *False* on failure (errors are logged, not raised).
    """
    url = _TELEGRAM_API_URL.format(token=bot_token)
    try:
        response = httpx.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
        response.raise_for_status()
        return True
    except (httpx.HTTPError, OSError) as exc:
        logger.warning("Failed to send Telegram notification: %s", exc)
        return False


def notify_sync_start(
    telegram_cfg: TelegramConfig,
    mirror_name: str,
) -> None:
    """Send a Telegram notification when a sync starts.

    Silently skips when ``bot_token`` or ``chat_id`` are not set, or when
    ``notify_on_start`` is *False*.
    """
    if not telegram_cfg.bot_token or not telegram_cfg.chat_id:
        return
    if not telegram_cfg.notify_on_start:
        return

    text = f"🔄 xync: [{mirror_name}] SYNC STARTED"
    send_telegram_message(telegram_cfg.bot_token, telegram_cfg.chat_id, text)


def notify_sync_finish(
    telegram_cfg: TelegramConfig,
    mirror_name: str,
    status: SyncStatus,
    duration_seconds: float,
    error: Optional[str] = None,
) -> None:
    """Send a Telegram notification when a sync finishes (regardless of result).

    Silently skips when ``bot_token`` or ``chat_id`` are not set, or when
    ``notify_on_finish`` is *False*.
    """
    if not telegram_cfg.bot_token or not telegram_cfg.chat_id:
        return
    if not telegram_cfg.notify_on_finish:
        return

    status_emoji = "✅" if status == SyncStatus.SUCCESS else "❌"
    text = (
        f"{status_emoji} xync: [{mirror_name}] SYNC FINISHED ({status.value.upper()})\n"  # noqa: E501
        f"Duration: {duration_seconds:.1f}s"
    )
    if error:
        text += f"\nError: {error}"

    send_telegram_message(telegram_cfg.bot_token, telegram_cfg.chat_id, text)


def notify_sync_progress(
    telegram_cfg: TelegramConfig,
    mirror_name: str,
    progress_pct: int,
) -> None:
    """Send a Telegram notification for a sync progress milestone.

    Silently skips when ``bot_token`` or ``chat_id`` are not set, or when
    ``notify_on_progress`` is *False*.
    """
    if not telegram_cfg.bot_token or not telegram_cfg.chat_id:
        return
    if not telegram_cfg.notify_on_progress:
        return

    text = f"📊 xync: [{mirror_name}] progress {progress_pct}%"
    send_telegram_message(telegram_cfg.bot_token, telegram_cfg.chat_id, text)


def notify_disk_usage_warning(
    telegram_cfg: TelegramConfig,
    mirror_name: str,
    usage_percent: float,
    threshold_percent: int,
    path: str,
) -> None:
    """Send a Telegram warning when mirror disk usage is above the threshold."""
    if not telegram_cfg.bot_token or not telegram_cfg.chat_id:
        return
    if not telegram_cfg.notify_on_failure:
        return

    text = (
        f"⚠️ xync: [{mirror_name}] disk usage warning\n"
        f"Usage: {usage_percent:.1f}% "
        f"(threshold: {threshold_percent}%)\n"
        f"Path: {path}"
    )
    send_telegram_message(telegram_cfg.bot_token, telegram_cfg.chat_id, text)


def send_test_notification(telegram_cfg: TelegramConfig) -> bool:
    """Send a test Telegram notification and return whether it was delivered."""
    if not telegram_cfg.bot_token or not telegram_cfg.chat_id:
        return False
    return send_telegram_message(
        telegram_cfg.bot_token,
        telegram_cfg.chat_id,
        "✅ xync test notification",
    )


def notify_sync_result(
    telegram_cfg: TelegramConfig,
    mirror_name: str,
    status: SyncStatus,
    duration_seconds: float,
    error: Optional[str] = None,
) -> None:
    """Send a Telegram notification for a sync result if Telegram is configured.

    Silently skips when ``bot_token`` or ``chat_id`` are not set, or when the
    relevant ``notify_on_*`` flag is *False*.
    """
    if not telegram_cfg.bot_token or not telegram_cfg.chat_id:
        return

    if status == SyncStatus.SUCCESS and not telegram_cfg.notify_on_success:
        return
    if status == SyncStatus.FAILED and not telegram_cfg.notify_on_failure:
        return

    status_emoji = "✅" if status == SyncStatus.SUCCESS else "❌"
    text = (
        f"{status_emoji} xync: [{mirror_name}] {status.value.upper()}\n"
        f"Duration: {duration_seconds:.1f}s"
    )
    if error:
        text += f"\nError: {error}"

    send_telegram_message(telegram_cfg.bot_token, telegram_cfg.chat_id, text)
