"""Shared notification helpers: JSON POST transport and message text."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from xync.models import SyncStatus

logger = logging.getLogger(__name__)


def post_json(url: str, payload: dict, timeout: float = 10) -> bool:
    """POST *payload* as JSON to *url*; return True on a successful response."""
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
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


def finish_text(
    mirror_name: str,
    status: SyncStatus,
    duration_seconds: float,
    error: str | None = None,
) -> str:
    text = (
        f"{_status_emoji(status)} xync: [{mirror_name}] "
        f"SYNC FINISHED ({status.value.upper()})\n"
        f"Duration: {duration_seconds:.1f}s"
    )
    if error:
        text += f"\nError: {error}"
    return text


def result_text(
    mirror_name: str,
    status: SyncStatus,
    duration_seconds: float,
    error: str | None = None,
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
