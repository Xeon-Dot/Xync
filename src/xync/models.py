"""Data models for xync."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Optional

from pydantic import BaseModel, BeforeValidator, Field, field_validator


class MirrorType(str, Enum):
    """Supported mirror sync protocols."""

    RSYNC = "rsync"
    HTTP = "http"
    FTP = "ftp"


class SyncStatus(str, Enum):
    """Sync run status."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    NEVER = "never"


class Mirror(BaseModel):
    """A configured mirror entry."""

    name: str = Field(..., description="Unique mirror name")
    url: str = Field(..., description="Source URL for the mirror")
    local_path: str = Field(..., description="Local destination path")
    mirror_type: MirrorType = Field(MirrorType.RSYNC, description="Sync protocol")
    enabled: bool = Field(True, description="Whether this mirror is active")
    description: str = Field("", description="Optional description")
    rsync_options: list[str] = Field(
        default_factory=lambda: ["-avz", "--delete"],
        description="Extra options passed to rsync",
    )
    http_options: list[str] = Field(
        default_factory=list,
        description="Extra options passed to wget/lftp for HTTP mirrors",
    )
    bandwidth_limit: Optional[str] = Field(
        None, description="Bandwidth limit (e.g. '10m' for 10 MB/s, rsync only)"
    )
    last_sync: Optional[datetime] = Field(None, description="Timestamp of last sync")
    last_status: SyncStatus = Field(SyncStatus.NEVER, description="Last sync result")
    last_size: Optional[int] = Field(
        None, description="Size in bytes of the local mirror after last successful sync"
    )
    previous_size: Optional[int] = Field(
        None,
        description=(
            "Size in bytes from the previous successful sync (for trend display)"
        ),
    )

    @field_validator("name")
    @classmethod
    def name_must_be_slug(cls, v: str) -> str:
        if not v.replace("-", "").replace("_", "").isalnum():
            raise ValueError(
                "Mirror name must contain only alphanumeric characters, "
                "hyphens, or underscores"
            )
        return v

    @field_validator("url")
    @classmethod
    def url_must_have_scheme(cls, v: str) -> str:
        valid_schemes = ("rsync://", "http://", "https://", "ftp://")
        if not any(v.startswith(s) for s in valid_schemes):
            raise ValueError(f"URL must start with one of: {', '.join(valid_schemes)}")
        return v


Credential = Annotated[Optional[str], BeforeValidator(lambda v: v or None)]


class NotificationConfig(BaseModel):
    """Shared notification-channel settings."""

    notify_on_success: bool = Field(
        True, description="Send notification on successful sync"
    )
    notify_on_failure: bool = Field(
        True, description="Send notification on failed sync"
    )
    notify_on_start: bool = Field(
        False, description="Send notification when sync starts"
    )
    notify_on_finish: bool = Field(
        False, description="Send notification when sync finishes (regardless of result)"
    )
    notify_on_progress: bool = Field(
        False, description="Send notification at every 10% sync progress (rsync only)"
    )


class TelegramConfig(NotificationConfig):
    """Telegram notification configuration."""

    bot_token: Credential = Field(None, description="Telegram Bot API token")
    chat_id: Credential = Field(
        None, description="Telegram chat ID to send notifications to"
    )


class DiscordConfig(NotificationConfig):
    """Discord webhook notification configuration."""

    webhook_url: Credential = Field(None, description="Discord webhook URL")


class GlobalConfig(BaseModel):
    """Global xync configuration."""

    default_rsync_options: list[str] = Field(
        default_factory=lambda: ["-avz", "--delete"],
        description="Default rsync options applied to all mirrors unless overridden",
    )
    log_dir: str = Field(
        "", description="Directory for sync logs (default: config_dir/logs)"
    )
    max_log_files: int = Field(
        30, description="Maximum number of log files to keep per mirror"
    )
    parallel_jobs: int = Field(1, description="Number of mirrors to sync in parallel")
    daemon_interval: int = Field(
        3600, description="Daemon sync interval in seconds (default: 3600)"
    )
    api_enabled: bool = Field(
        False, description="Enable API server when daemon starts (default: False)"
    )
    api_port: int = Field(58080, description="API server port (default: 58080)")
    daemon_schedule: Optional[str] = Field(
        None, description="Cron expression for daemon scheduling (e.g. '0 2 * * *')"
    )
    disk_usage_warning_percent: int = Field(
        90,
        description=(
            "Send a warning when a mirror filesystem reaches this usage percent"
        ),
    )
    telegram: TelegramConfig = Field(
        default_factory=TelegramConfig, description="Telegram notification settings"
    )
    discord: DiscordConfig = Field(
        default_factory=DiscordConfig,
        description="Discord webhook notification settings",
    )

    @field_validator("max_log_files", "parallel_jobs", "daemon_interval")
    @classmethod
    def must_be_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("Value must be greater than or equal to 1")
        return v

    @field_validator("api_port")
    @classmethod
    def valid_api_port(cls, v: int) -> int:
        if v < 1 or v > 65535:
            raise ValueError("API port must be between 1 and 65535")
        return v

    @field_validator("disk_usage_warning_percent")
    @classmethod
    def valid_disk_usage_warning_percent(cls, v: int) -> int:
        if v < 1 or v > 100:
            raise ValueError("Disk usage warning percent must be between 1 and 100")
        return v


class xyncConfig(BaseModel):
    """Top-level configuration container."""

    version: int = Field(1, description="Config schema version")
    global_config: GlobalConfig = Field(default_factory=GlobalConfig)
    mirrors: dict[str, Mirror] = Field(default_factory=dict)
