"""Tests for xync.notify dispatch."""

from unittest.mock import patch

from xync import notify
from xync.models import DiscordConfig, GlobalConfig, SyncStatus, TelegramConfig

BOT_TOKEN = "discord-bot-token"
CHANNEL_ID = "123456789"


class MirrorStub:
    def __init__(self, name: str, local_path: str):
        self.name = name
        self.local_path = local_path


def _make_dc(**kwargs) -> DiscordConfig:
    defaults = {"bot_token": BOT_TOKEN, "channel_id": CHANNEL_ID}
    defaults.update(kwargs)
    return DiscordConfig(**defaults)


def _make_tg(**kwargs) -> TelegramConfig:
    defaults = {"bot_token": "tok123", "chat_id": "chat789"}
    defaults.update(kwargs)
    return TelegramConfig(**defaults)


def _make_global(telegram=None, discord=None) -> GlobalConfig:
    return GlobalConfig(
        telegram=telegram or TelegramConfig(),
        discord=discord or DiscordConfig(),
    )


class TestTransport:
    def test_telegram_send_posts_to_api(self):
        cfg = _make_tg(bot_token="mytoken", chat_id="mychat")
        with patch("xync.notify.post_json", return_value=True) as mock_post:
            assert notify._send_telegram(cfg, "Hello!") is True
        url, payload = mock_post.call_args[0]
        assert "mytoken" in url
        assert "sendMessage" in url
        assert payload == {"chat_id": "mychat", "text": "Hello!"}

    def test_telegram_skips_when_unconfigured(self):
        cfg = TelegramConfig(bot_token=None, chat_id="chat")
        with patch("xync.notify.post_json") as mock_post:
            assert notify._send_telegram(cfg, "msg") is False
        mock_post.assert_not_called()

    def test_discord_send_posts_bot_api(self):
        cfg = _make_dc()
        with patch("xync.notify.post_json", return_value=True) as mock_post:
            assert notify._send_discord(cfg, "Hello!") is True
        url, payload = mock_post.call_args[0]
        assert url == f"https://discord.com/api/v10/channels/{CHANNEL_ID}/messages"
        assert payload == {"content": "Hello!"}
        assert mock_post.call_args.kwargs["headers"] == {
            "Authorization": f"Bot {BOT_TOKEN}"
        }

    def test_discord_send_posts_embed(self):
        cfg = _make_dc()
        embed = {"title": "Test", "color": 0x2ECC71}
        with patch("xync.notify.post_json", return_value=True) as mock_post:
            assert notify._send_discord(cfg, embed=embed) is True
        url, payload = mock_post.call_args[0]
        assert url == f"https://discord.com/api/v10/channels/{CHANNEL_ID}/messages"
        assert payload == {"embeds": [embed]}
        assert mock_post.call_args.kwargs["headers"] == {
            "Authorization": f"Bot {BOT_TOKEN}"
        }

    def test_discord_skips_when_empty_payload(self):
        cfg = _make_dc()
        with patch("xync.notify.post_json") as mock_post:
            assert notify._send_discord(cfg) is False
        mock_post.assert_not_called()

    def test_discord_skips_when_unconfigured(self):
        cfg = DiscordConfig(bot_token=None, channel_id=CHANNEL_ID)
        with patch("xync.notify.post_json") as mock_post:
            assert notify._send_discord(cfg, "msg") is False
        mock_post.assert_not_called()

    def test_discord_skips_when_channel_missing(self):
        cfg = DiscordConfig(bot_token=BOT_TOKEN, channel_id=None)
        with patch("xync.notify.post_json") as mock_post:
            assert notify._send_discord(cfg, "msg") is False
        mock_post.assert_not_called()


class TestNotifySyncResult:
    def test_sends_success_to_both_channels(self):
        gc = _make_global(_make_tg(), _make_dc())
        with (
            patch("xync.notify._send_telegram") as mock_tg,
            patch("xync.notify._send_discord") as mock_dc,
        ):
            notify.notify_sync_result(gc, "ubuntu", SyncStatus.SUCCESS, 12.5)
        assert "SUCCESS" in mock_tg.call_args[0][1]
        assert "12.5s" in mock_tg.call_args[0][1]
        embed = mock_dc.call_args.kwargs["embed"]
        assert "SUCCESS" in embed["title"]
        assert any(f["value"] == "ubuntu" for f in embed["fields"])

    def test_sends_failure_with_error(self):
        gc = _make_global(_make_tg(), _make_dc())
        with (
            patch("xync.notify._send_telegram") as mock_tg,
            patch("xync.notify._send_discord") as mock_dc,
        ):
            notify.notify_sync_result(
                gc, "debian", SyncStatus.FAILED, 3.0, "rsync failed"
            )
        text = mock_tg.call_args[0][1]
        assert "FAILED" in text
        assert "rsync failed" in text
        embed = mock_dc.call_args.kwargs["embed"]
        assert "FAILED" in embed["title"]
        assert any(f["value"] == "rsync failed" for f in embed["fields"])

    def test_skips_success_when_notify_on_success_false(self):
        gc = _make_global(
            _make_tg(notify_on_success=False), _make_dc(notify_on_success=False)
        )
        with (
            patch("xync.notify._send_telegram") as mock_tg,
            patch("xync.notify._send_discord") as mock_dc,
        ):
            notify.notify_sync_result(gc, "ubuntu", SyncStatus.SUCCESS, 10.0)
        mock_tg.assert_not_called()
        mock_dc.assert_not_called()

    def test_skips_failure_when_notify_on_failure_false(self):
        gc = _make_global(
            _make_tg(notify_on_failure=False), _make_dc(notify_on_failure=False)
        )
        with (
            patch("xync.notify._send_telegram") as mock_tg,
            patch("xync.notify._send_discord") as mock_dc,
        ):
            notify.notify_sync_result(gc, "ubuntu", SyncStatus.FAILED, 5.0, "boom")
        mock_tg.assert_not_called()
        mock_dc.assert_not_called()

    def test_notify_on_finish_forces_send(self):
        gc = _make_global(
            _make_tg(notify_on_success=False, notify_on_finish=True),
            _make_dc(notify_on_failure=False, notify_on_finish=True),
        )
        with (
            patch("xync.notify._send_telegram") as mock_tg,
            patch("xync.notify._send_discord") as mock_dc,
        ):
            notify.notify_sync_result(gc, "ubuntu", SyncStatus.SUCCESS, 5.0)
        mock_tg.assert_called_once()
        mock_dc.assert_called_once()

    def test_skips_unconfigured_channels(self):
        gc = _make_global()
        with patch("xync.notify.post_json") as mock_post:
            notify.notify_sync_result(gc, "ubuntu", SyncStatus.SUCCESS, 10.0)
        mock_post.assert_not_called()


class TestNotifySyncStart:
    def test_sends_start_to_both_channels(self):
        gc = _make_global(
            _make_tg(notify_on_start=True), _make_dc(notify_on_start=True)
        )
        with (
            patch("xync.notify._send_telegram") as mock_tg,
            patch("xync.notify._send_discord") as mock_dc,
        ):
            notify.notify_sync_start(gc, "ubuntu")
        assert "STARTED" in mock_tg.call_args[0][1]
        embed = mock_dc.call_args.kwargs["embed"]
        assert "ubuntu" in embed["title"]
        assert any(f["value"] == "ubuntu" for f in embed["fields"])

    def test_skips_when_notify_on_start_false(self):
        gc = _make_global(_make_tg(), _make_dc())
        with (
            patch("xync.notify._send_telegram") as mock_tg,
            patch("xync.notify._send_discord") as mock_dc,
        ):
            notify.notify_sync_start(gc, "ubuntu")
        mock_tg.assert_not_called()
        mock_dc.assert_not_called()

    def test_skips_unconfigured_channels(self):
        gc = _make_global(
            TelegramConfig(notify_on_start=True), DiscordConfig(notify_on_start=True)
        )
        with patch("xync.notify.post_json") as mock_post:
            notify.notify_sync_start(gc, "ubuntu")
        mock_post.assert_not_called()


class TestNotifySyncProgress:
    def test_sends_progress_to_both_channels(self):
        gc = _make_global(
            _make_tg(notify_on_progress=True), _make_dc(notify_on_progress=True)
        )
        with (
            patch("xync.notify._send_telegram") as mock_tg,
            patch("xync.notify._send_discord") as mock_dc,
        ):
            notify.notify_sync_progress(gc, "ubuntu", 70)
        assert "70%" in mock_tg.call_args[0][1]
        embed = mock_dc.call_args.kwargs["embed"]
        assert "70%" in str(embed)
        assert any(f["value"] == "ubuntu" for f in embed["fields"])

    def test_skips_when_notify_on_progress_false(self):
        gc = _make_global()
        with (
            patch("xync.notify._send_telegram") as mock_tg,
            patch("xync.notify._send_discord") as mock_dc,
        ):
            notify.notify_sync_progress(gc, "ubuntu", 50)
        mock_tg.assert_not_called()
        mock_dc.assert_not_called()


class TestNotifyDiskWarning:
    def test_sends_warning_above_threshold(self):
        gc = _make_global(_make_tg(), _make_dc())
        mirror = MirrorStub(local_path="/srv/mirrors/ubuntu", name="ubuntu")
        with (
            patch(
                "xync.notify.disk_usage_for_path",
                return_value=(91.5, "/srv/mirrors/ubuntu"),
            ),
            patch("xync.notify._send_telegram") as mock_tg,
            patch("xync.notify._send_discord") as mock_dc,
        ):
            notify.notify_disk_warning(gc, mirror)
        text = mock_tg.call_args[0][1]
        assert "91.5%" in text
        assert "/srv/mirrors/ubuntu" in text
        mock_dc.assert_called_once()
        embed = mock_dc.call_args.kwargs["embed"]
        assert "91.5%" in str(embed)
        assert "/srv/mirrors/ubuntu" in str(embed)

    def test_skips_below_threshold(self):
        gc = _make_global(_make_tg(), _make_dc())
        mirror = MirrorStub(local_path="/srv/mirrors/ubuntu", name="ubuntu")
        with (
            patch(
                "xync.notify.disk_usage_for_path",
                return_value=(50.0, "/srv/mirrors/ubuntu"),
            ),
            patch("xync.notify._send_telegram") as mock_tg,
        ):
            notify.notify_disk_warning(gc, mirror)
        mock_tg.assert_not_called()

    def test_skips_when_usage_unknown(self):
        gc = _make_global(_make_tg(), _make_dc())
        mirror = MirrorStub(local_path="/srv/mirrors/ubuntu", name="ubuntu")
        with (
            patch("xync.notify.disk_usage_for_path", return_value=None),
            patch("xync.notify._send_telegram") as mock_tg,
        ):
            notify.notify_disk_warning(gc, mirror)
        mock_tg.assert_not_called()


class TestHelpers:
    def test_make_progress_callback_forwards_percentage(self):
        gc = _make_global()
        with patch("xync.notify.notify_sync_progress") as mock_progress:
            notify.make_progress_callback(gc, "ubuntu")(50)
        mock_progress.assert_called_once_with(gc, "ubuntu", 50)

    def test_send_test_notification_telegram(self):
        gc = _make_global(_make_tg(), _make_dc())
        with patch("xync.notify._send_telegram", return_value=True) as mock_tg:
            assert notify.send_test_notification(gc, "telegram") is True
        mock_tg.assert_called_once()

    def test_send_test_notification_discord(self):
        gc = _make_global(_make_tg(), _make_dc())
        with patch("xync.notify._send_discord", return_value=True) as mock_dc:
            assert notify.send_test_notification(gc, "discord") is True
        mock_dc.assert_called_once()
        embed = mock_dc.call_args.kwargs["embed"]
        assert "Test Notification" in embed["title"]

    def test_send_test_notification_unknown_channel(self):
        gc = _make_global()
        assert notify.send_test_notification(gc, "email") is False


class TestDiscordEmbeds:
    def test_start_embed(self):
        embed = notify.discord_start_embed("arch")
        assert "arch" in embed["title"]
        assert embed["color"] == notify._COLOR_INFO
        assert any(
            f["name"] == "Mirror" and f["value"] == "arch" for f in embed["fields"]
        )

    def test_result_embed_success(self):
        embed = notify.discord_result_embed("debian", SyncStatus.SUCCESS, 4.2)
        assert "SUCCESS" in embed["title"]
        assert embed["color"] == notify._COLOR_SUCCESS
        assert any(
            f["name"] == "Duration" and f["value"] == "4.2s" for f in embed["fields"]
        )
        assert not any(f["name"] == "Error" for f in embed["fields"])

    def test_result_embed_failure_truncates_long_error(self):
        long_error = "x" * 2000
        embed = notify.discord_result_embed(
            "debian", SyncStatus.FAILED, 1.0, error=long_error
        )
        assert "FAILED" in embed["title"]
        assert embed["color"] == notify._COLOR_FAILURE
        error_field = next(f for f in embed["fields"] if f["name"] == "Error")
        assert len(error_field["value"]) <= 1003
        assert error_field["value"].endswith("...")

    def test_progress_embed(self):
        embed = notify.discord_progress_embed("ubuntu", 85)
        assert "ubuntu" in embed["title"]
        assert any(
            f["name"] == "Progress" and f["value"] == "85%" for f in embed["fields"]
        )

    def test_disk_embed(self):
        embed = notify.discord_disk_embed("ubuntu", 92.3, 90, "/data")
        assert "ubuntu" in embed["title"]
        assert embed["color"] == notify._COLOR_WARNING
        assert any(
            f["name"] == "Usage" and f["value"] == "92.3%" for f in embed["fields"]
        )
        assert any(
            f["name"] == "Path" and f["value"] == "/data" for f in embed["fields"]
        )

    def test_test_embed(self):
        embed = notify.discord_test_embed()
        assert "Test Notification" in embed["title"]
        assert embed["color"] == notify._COLOR_SUCCESS
