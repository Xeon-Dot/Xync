"""Telegram notification support for xync."""

from __future__ import annotations

from typing import Optional

from xync.models import SyncStatus, TelegramConfig
from xync.notify import (
    disk_text,
    finish_text,
    post_json,
    progress_text,
    result_text,
    start_text,
)

_TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


def send_telegram_message(bot_token: str, chat_id: str, text: str) -> bool:
    """Send a message via the Telegram Bot API.

    Returns *True* on success, *False* on failure (errors are logged, not raised).
    """
    url = _TELEGRAM_API_URL.format(token=bot_token)
    return post_json(url, {"chat_id": chat_id, "text": text})


def _configured(telegram_cfg: TelegramConfig) -> bool:
    return bool(telegram_cfg.bot_token and telegram_cfg.chat_id)


def notify_sync_start(telegram_cfg: TelegramConfig, mirror_name: str) -> None:
    """Send a Telegram notification when a sync starts."""
    if not _configured(telegram_cfg) or not telegram_cfg.notify_on_start:
        return
    send_telegram_message(
        telegram_cfg.bot_token, telegram_cfg.chat_id, start_text(mirror_name)
    )


def notify_sync_finish(
    telegram_cfg: TelegramConfig,
    mirror_name: str,
    status: SyncStatus,
    duration_seconds: float,
    error: Optional[str] = None,
) -> None:
    """Send a Telegram notification when a sync finishes (regardless of result)."""
    if not _configured(telegram_cfg) or not telegram_cfg.notify_on_finish:
        return
    send_telegram_message(
        telegram_cfg.bot_token,
        telegram_cfg.chat_id,
        finish_text(mirror_name, status, duration_seconds, error),
    )


def notify_sync_progress(
    telegram_cfg: TelegramConfig,
    mirror_name: str,
    progress_pct: int,
) -> None:
    """Send a Telegram notification for a sync progress milestone."""
    if not _configured(telegram_cfg) or not telegram_cfg.notify_on_progress:
        return
    send_telegram_message(
        telegram_cfg.bot_token,
        telegram_cfg.chat_id,
        progress_text(mirror_name, progress_pct),
    )


def notify_disk_usage_warning(
    telegram_cfg: TelegramConfig,
    mirror_name: str,
    usage_percent: float,
    threshold_percent: int,
    path: str,
) -> None:
    """Send a Telegram warning when mirror disk usage is above the threshold."""
    if not _configured(telegram_cfg) or not telegram_cfg.notify_on_failure:
        return
    send_telegram_message(
        telegram_cfg.bot_token,
        telegram_cfg.chat_id,
        disk_text(mirror_name, usage_percent, threshold_percent, path),
    )


def send_test_notification(telegram_cfg: TelegramConfig) -> bool:
    """Send a test Telegram notification and return whether it was delivered."""
    if not _configured(telegram_cfg):
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
    """Send a Telegram notification for a sync result if Telegram is configured."""
    if not _configured(telegram_cfg):
        return
    if status == SyncStatus.SUCCESS and not telegram_cfg.notify_on_success:
        return
    if status == SyncStatus.FAILED and not telegram_cfg.notify_on_failure:
        return
    send_telegram_message(
        telegram_cfg.bot_token,
        telegram_cfg.chat_id,
        result_text(mirror_name, status, duration_seconds, error),
    )
