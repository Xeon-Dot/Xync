"""Tests for xync.telegram notification module."""

from unittest.mock import patch

from xync.models import SyncStatus, TelegramConfig
from xync.telegram import (
    notify_disk_usage_warning,
    notify_sync_finish,
    notify_sync_progress,
    notify_sync_result,
    notify_sync_start,
    send_telegram_message,
    send_test_notification,
)


class TestSendTelegramMessage:
    def test_successful_send(self):
        with patch("xync.telegram.post_json", return_value=True) as mock_post:
            result = send_telegram_message("token123", "chat456", "Hello!")
        assert result is True
        mock_post.assert_called_once()
        url, payload = mock_post.call_args[0]
        assert payload["chat_id"] == "chat456"
        assert payload["text"] == "Hello!"

    def test_http_error_returns_false(self):
        with patch("xync.telegram.post_json", return_value=False):
            result = send_telegram_message("token", "chat", "msg")
        assert result is False

    def test_uses_correct_api_url(self):
        with patch("xync.telegram.post_json", return_value=True) as mock_post:
            send_telegram_message("mytoken", "mychat", "test")
        url = mock_post.call_args[0][0]
        assert "mytoken" in url
        assert "sendMessage" in url


class TestNotifySyncResult:
    def _make_cfg(self, **kwargs) -> TelegramConfig:
        defaults = {
            "bot_token": "tok123",
            "chat_id": "chat789",
            "notify_on_success": True,
            "notify_on_failure": True,
        }
        defaults.update(kwargs)
        return TelegramConfig(**defaults)  # ty:ignore[invalid-argument-type]

    def test_skips_when_no_token(self):
        cfg = TelegramConfig(bot_token=None, chat_id="chat")
        with patch("xync.telegram.send_telegram_message") as mock_send:
            notify_sync_result(cfg, "ubuntu", SyncStatus.SUCCESS, 10.0)
        mock_send.assert_not_called()

    def test_skips_when_no_chat_id(self):
        cfg = TelegramConfig(bot_token="token", chat_id=None)
        with patch("xync.telegram.send_telegram_message") as mock_send:
            notify_sync_result(cfg, "ubuntu", SyncStatus.SUCCESS, 10.0)
        mock_send.assert_not_called()

    def test_skips_success_when_notify_on_success_false(self):
        cfg = self._make_cfg(notify_on_success=False)
        with patch("xync.telegram.send_telegram_message") as mock_send:
            notify_sync_result(cfg, "ubuntu", SyncStatus.SUCCESS, 10.0)
        mock_send.assert_not_called()

    def test_skips_failure_when_notify_on_failure_false(self):
        cfg = self._make_cfg(notify_on_failure=False)
        with patch("xync.telegram.send_telegram_message") as mock_send:
            notify_sync_result(cfg, "ubuntu", SyncStatus.FAILED, 5.0, "exit code 1")
        mock_send.assert_not_called()

    def test_sends_success_notification(self):
        cfg = self._make_cfg()
        with patch("xync.telegram.send_telegram_message") as mock_send:
            notify_sync_result(cfg, "ubuntu", SyncStatus.SUCCESS, 12.5)
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "ubuntu" in text
        assert "SUCCESS" in text
        assert "12.5s" in text
        assert "✅" in text

    def test_sends_failure_notification_with_error(self):
        cfg = self._make_cfg()
        with patch("xync.telegram.send_telegram_message") as mock_send:
            notify_sync_result(cfg, "debian", SyncStatus.FAILED, 3.0, "rsync failed")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "debian" in text
        assert "FAILED" in text
        assert "❌" in text
        assert "rsync failed" in text

    def test_sends_with_correct_credentials(self):
        cfg = self._make_cfg(bot_token="mytoken", chat_id="mychat")
        with patch("xync.telegram.send_telegram_message") as mock_send:
            notify_sync_result(cfg, "ubuntu", SyncStatus.SUCCESS, 5.0)
        mock_send.assert_called_once_with(
            "mytoken", "mychat", mock_send.call_args[0][2]
        )


class TestNotifySyncStart:
    def _make_cfg(self, **kwargs) -> TelegramConfig:
        defaults = {
            "bot_token": "tok123",
            "chat_id": "chat789",
            "notify_on_start": True,
        }
        defaults.update(kwargs)
        return TelegramConfig(**defaults)  # ty:ignore[invalid-argument-type]

    def test_skips_when_no_token(self):
        cfg = TelegramConfig(bot_token=None, chat_id="chat", notify_on_start=True)
        with patch("xync.telegram.send_telegram_message") as mock_send:
            notify_sync_start(cfg, "ubuntu")
        mock_send.assert_not_called()

    def test_skips_when_no_chat_id(self):
        cfg = TelegramConfig(bot_token="token", chat_id=None, notify_on_start=True)
        with patch("xync.telegram.send_telegram_message") as mock_send:
            notify_sync_start(cfg, "ubuntu")
        mock_send.assert_not_called()

    def test_skips_when_notify_on_start_false(self):
        cfg = self._make_cfg(notify_on_start=False)
        with patch("xync.telegram.send_telegram_message") as mock_send:
            notify_sync_start(cfg, "ubuntu")
        mock_send.assert_not_called()

    def test_sends_start_notification(self):
        cfg = self._make_cfg()
        with patch("xync.telegram.send_telegram_message") as mock_send:
            notify_sync_start(cfg, "ubuntu")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "ubuntu" in text
        assert "STARTED" in text
        assert "🔄" in text


class TestNotifySyncFinish:
    def _make_cfg(self, **kwargs) -> TelegramConfig:
        defaults = {
            "bot_token": "tok123",
            "chat_id": "chat789",
            "notify_on_finish": True,
        }
        defaults.update(kwargs)
        return TelegramConfig(**defaults)  # ty:ignore[invalid-argument-type]

    def test_skips_when_no_token(self):
        cfg = TelegramConfig(bot_token=None, chat_id="chat", notify_on_finish=True)
        with patch("xync.telegram.send_telegram_message") as mock_send:
            notify_sync_finish(cfg, "ubuntu", SyncStatus.SUCCESS, 5.0)
        mock_send.assert_not_called()

    def test_skips_when_notify_on_finish_false(self):
        cfg = self._make_cfg(notify_on_finish=False)
        with patch("xync.telegram.send_telegram_message") as mock_send:
            notify_sync_finish(cfg, "ubuntu", SyncStatus.SUCCESS, 5.0)
        mock_send.assert_not_called()

    def test_sends_finish_notification_on_success(self):
        cfg = self._make_cfg()
        with patch("xync.telegram.send_telegram_message") as mock_send:
            notify_sync_finish(cfg, "ubuntu", SyncStatus.SUCCESS, 12.5)
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "ubuntu" in text
        assert "FINISHED" in text
        assert "SUCCESS" in text
        assert "12.5s" in text
        assert "✅" in text

    def test_sends_finish_notification_on_failure(self):
        cfg = self._make_cfg()
        with patch("xync.telegram.send_telegram_message") as mock_send:
            notify_sync_finish(cfg, "debian", SyncStatus.FAILED, 3.0, "rsync failed")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "FAILED" in text
        assert "rsync failed" in text
        assert "❌" in text


class TestNotifySyncProgress:
    def _make_cfg(self, **kwargs) -> TelegramConfig:
        defaults = {
            "bot_token": "tok123",
            "chat_id": "chat789",
            "notify_on_progress": True,
        }
        defaults.update(kwargs)
        return TelegramConfig(**defaults)  # ty:ignore[invalid-argument-type]

    def test_skips_when_no_token(self):
        cfg = TelegramConfig(bot_token=None, chat_id="chat", notify_on_progress=True)
        with patch("xync.telegram.send_telegram_message") as mock_send:
            notify_sync_progress(cfg, "ubuntu", 50)
        mock_send.assert_not_called()

    def test_skips_when_notify_on_progress_false(self):
        cfg = self._make_cfg(notify_on_progress=False)
        with patch("xync.telegram.send_telegram_message") as mock_send:
            notify_sync_progress(cfg, "ubuntu", 50)
        mock_send.assert_not_called()

    def test_sends_progress_notification(self):
        cfg = self._make_cfg()
        with patch("xync.telegram.send_telegram_message") as mock_send:
            notify_sync_progress(cfg, "ubuntu", 50)
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "ubuntu" in text
        assert "50%" in text
        assert "📊" in text


class TestDiskUsageAndTestNotification:
    def test_sends_disk_usage_warning(self):
        cfg = TelegramConfig(bot_token="tok123", chat_id="chat789")
        with patch("xync.telegram.send_telegram_message") as mock_send:
            notify_disk_usage_warning(cfg, "ubuntu", 91.5, 90, "/srv/mirrors")
        mock_send.assert_called_once()
        text = mock_send.call_args[0][2]
        assert "ubuntu" in text
        assert "91.5%" in text
        assert "/srv/mirrors" in text

    def test_send_test_notification(self):
        cfg = TelegramConfig(bot_token="tok123", chat_id="chat789")
        with patch(
            "xync.telegram.send_telegram_message", return_value=True
        ) as mock_send:
            result = send_test_notification(cfg)
        assert result is True
        mock_send.assert_called_once()
