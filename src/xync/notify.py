"""Notification dispatch for xync: transport, message text, and channel gateways."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Callable, Optional

from xync.models import DiscordConfig, GlobalConfig, Mirror, SyncStatus, TelegramConfig
from xync.utils import disk_usage_for_path

logger = logging.getLogger(__name__)

_TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"
_DISCORD_API_URL = "https://discord.com/api/v10/channels/{channel_id}/messages"

_COLOR_SUCCESS = 0x2ECC71
_COLOR_FAILURE = 0xE74C3C
_COLOR_INFO = 0x5865F2
_COLOR_WARNING = 0xF1C40F


def post_json(
    url: str, payload: dict, timeout: float = 10, headers: Optional[dict] = None
) -> bool:
    """POST *payload* as JSON to *url*; return True on a successful response."""
    merged_headers = {"Content-Type": "application/json"}
    if headers:
        merged_headers.update(headers)
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers=merged_headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read()
        return True
    except (urllib.error.URLError, OSError, ValueError) as exc:
        logger.warning("Notification POST to %s failed: %s", url, exc)
        return False


def _status_emoji(status: SyncStatus) -> str:
    return "✅" if status == SyncStatus.SUCCESS else "❌"


def start_text(mirror_name: str) -> str:
    return f"🔄 xync: [{mirror_name}] SYNC STARTED"


def progress_text(mirror_name: str, progress_pct: int) -> str:
    return f"📊 xync: [{mirror_name}] progress {progress_pct}%"


def result_text(
    mirror_name: str,
    status: SyncStatus,
    duration_seconds: float,
    error: Optional[str] = None,
) -> str:
    text = (
        f"{_status_emoji(status)} xync: [{mirror_name}] {status.value.upper()}\n"
        f"Duration: {duration_seconds:.1f}s"
    )
    if error:
        text += f"\nError: {error}"
    return text


def disk_text(
    mirror_name: str,
    usage_percent: float,
    threshold_percent: int,
    path: str,
) -> str:
    return (
        f"⚠️ xync: [{mirror_name}] disk usage warning\n"
        f"Usage: {usage_percent:.1f}% "
        f"(threshold: {threshold_percent}%)\n"
        f"Path: {path}"
    )


def _embed(
    title: str,
    color: int,
    *fields: tuple,
    desc: Optional[str] = None,
) -> dict:
    res = {
        "title": title,
        "color": color,
        "fields": [
            {
                "name": f[0],
                "value": f[1],
                "inline": f[2] if len(f) > 2 else True,
            }
            for f in fields
        ],
        "footer": {"text": "xync"},
    }
    if desc:
        res["description"] = desc
    return res


def discord_start_embed(mirror_name: str) -> dict:
    return _embed(
        f"🔄 [{mirror_name}] Sync Started",
        _COLOR_INFO,
        ("Mirror", mirror_name),
        ("Status", "Started"),
    )


def discord_result_embed(
    mirror_name: str,
    status: SyncStatus,
    duration_seconds: float,
    error: Optional[str] = None,
) -> dict:
    fields: list[tuple] = [
        ("Mirror", mirror_name),
        ("Status", status.value.upper()),
        ("Duration", f"{duration_seconds:.1f}s"),
    ]
    if error:
        err_msg = error[:1000] + "..." if len(error) > 1000 else error
        fields.append(("Error", err_msg, False))
    return _embed(
        f"{_status_emoji(status)} [{mirror_name}] {status.value.upper()}",
        _COLOR_SUCCESS if status == SyncStatus.SUCCESS else _COLOR_FAILURE,
        *fields,
    )


def discord_progress_embed(mirror_name: str, progress_pct: int) -> dict:
    return _embed(
        f"📊 [{mirror_name}] Sync Progress",
        _COLOR_INFO,
        ("Mirror", mirror_name),
        ("Progress", f"{progress_pct}%"),
    )


def discord_disk_embed(
    mirror_name: str,
    usage_percent: float,
    threshold_percent: int,
    path: str,
) -> dict:
    return _embed(
        f"⚠️ [{mirror_name}] Disk Usage Warning",
        _COLOR_WARNING,
        ("Mirror", mirror_name),
        ("Usage", f"{usage_percent:.1f}%"),
        ("Threshold", f"{threshold_percent}%"),
        ("Path", path, False),
    )


def discord_test_embed() -> dict:
    return _embed(
        "✅ xync Test Notification",
        _COLOR_SUCCESS,
        desc="Discord bot integration is working properly.",
    )


def _send_telegram(cfg: TelegramConfig, text: str) -> bool:
    """Send *text* via the Telegram Bot API; no-op (False) when unconfigured."""
    if not (cfg.bot_token and cfg.chat_id):
        return False
    url = _TELEGRAM_API_URL.format(token=cfg.bot_token)
    return post_json(url, {"chat_id": cfg.chat_id, "text": text})


def _send_discord(
    cfg: DiscordConfig,
    text: str = "",
    *,
    embed: Optional[dict] = None,
) -> bool:
    """Send message via the Discord Bot API; no-op (False) when unconfigured."""
    if not (cfg.bot_token and cfg.channel_id):
        return False
    payload: dict = {}
    if text:
        payload["content"] = text
    if embed:
        payload["embeds"] = [embed]
    if not payload:
        return False
    url = _DISCORD_API_URL.format(channel_id=cfg.channel_id)
    return post_json(
        url, payload, headers={"Authorization": f"Bot {cfg.bot_token}"}
    )


def _wants_result(cfg, status: SyncStatus) -> bool:
    """Gate for result notifications: on_finish forces a send."""
    if status == SyncStatus.SUCCESS:
        return cfg.notify_on_success or cfg.notify_on_finish
    if status == SyncStatus.FAILED:
        return cfg.notify_on_failure or cfg.notify_on_finish
    return cfg.notify_on_finish


def notify_sync_start(global_config: GlobalConfig, mirror_name: str) -> None:
    """Notify every configured channel that a sync started."""
    tg, dc = global_config.telegram, global_config.discord
    if tg.notify_on_start:
        _send_telegram(tg, start_text(mirror_name))
    if dc.notify_on_start:
        _send_discord(dc, embed=discord_start_embed(mirror_name))


def notify_sync_result(
    global_config: GlobalConfig,
    mirror_name: str,
    status: SyncStatus,
    duration_seconds: float,
    error: Optional[str] = None,
) -> None:
    """Notify every configured channel of a sync result (one message max)."""
    tg, dc = global_config.telegram, global_config.discord
    if not _wants_result(tg, status) and not _wants_result(dc, status):
        return
    if _wants_result(tg, status):
        _send_telegram(tg, result_text(mirror_name, status, duration_seconds, error))
    if _wants_result(dc, status):
        _send_discord(
            dc,
            embed=discord_result_embed(mirror_name, status, duration_seconds, error),
        )


def notify_sync_progress(
    global_config: GlobalConfig,
    mirror_name: str,
    progress_pct: int,
) -> None:
    """Notify every configured channel of a progress milestone."""
    tg, dc = global_config.telegram, global_config.discord
    if tg.notify_on_progress:
        _send_telegram(tg, progress_text(mirror_name, progress_pct))
    if dc.notify_on_progress:
        _send_discord(dc, embed=discord_progress_embed(mirror_name, progress_pct))


def notify_disk_warning(global_config: GlobalConfig, mirror: Mirror) -> None:
    """Warn every configured channel when the mirror filesystem is above threshold."""
    usage = disk_usage_for_path(mirror.local_path)
    if usage is None:
        return
    usage_percent, usage_path = usage
    threshold = global_config.disk_usage_warning_percent
    if usage_percent < threshold:
        return
    tg, dc = global_config.telegram, global_config.discord
    if not (tg.notify_on_failure or dc.notify_on_failure):
        return
    if tg.notify_on_failure:
        _send_telegram(
            tg, disk_text(mirror.name, usage_percent, threshold, str(usage_path))
        )
    if dc.notify_on_failure:
        _send_discord(
            dc,
            embed=discord_disk_embed(
                mirror.name, usage_percent, threshold, str(usage_path)
            ),
        )


def make_progress_callback(
    global_config: GlobalConfig,
    mirror_name: str,
) -> Callable[[int], None]:
    """Return a callback forwarding each progress percentage to the channels."""

    def _cb(pct: int) -> None:
        notify_sync_progress(global_config, mirror_name, pct)

    return _cb


def send_test_notification(global_config: GlobalConfig, channel: str) -> bool:
    """Send a test message through *channel* (``telegram`` or ``discord``)."""
    if channel == "telegram":
        return _send_telegram(global_config.telegram, "✅ xync test notification")
    if channel == "discord":
        return _send_discord(global_config.discord, embed=discord_test_embed())
    return False
