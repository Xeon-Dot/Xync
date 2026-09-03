"""Tests for xync.notify dispatch."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import nextcord

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


def _embed_fields(embed: nextcord.Embed) -> dict:
    return {f.name: f.value for f in embed.fields}


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

    def test_discord_send_delivers_via_nextcord(self):
        cfg = _make_dc()
        with patch("xync.notify._deliver_discord", return_value=None) as mock_deliver:
            assert notify._send_discord(cfg, "Hello!") is True
        token, channel_id, text, embed = mock_deliver.call_args[0]
        assert token == BOT_TOKEN
        assert channel_id == int(CHANNEL_ID)
        assert text == "Hello!"
        assert embed is None

    def test_discord_send_delivers_embed(self):
        cfg = _make_dc()
        embed = nextcord.Embed(title="Test")
        with patch("xync.notify._deliver_discord", return_value=None) as mock_deliver:
            assert notify._send_discord(cfg, embed=embed) is True
        assert mock_deliver.call_args[0][1] == int(CHANNEL_ID)
        assert mock_deliver.call_args[0][3] is embed

    def test_discord_rejects_invalid_channel_id(self):
        cfg = _make_dc(channel_id="not-a-number")
        with patch("xync.notify._deliver_discord") as mock_deliver:
            assert notify._send_discord(cfg, "msg") is False
        mock_deliver.assert_not_called()

    def test_discord_returns_false_on_delivery_error(self):
        cfg = _make_dc()
        with patch(
            "xync.notify._deliver_discord",
            side_effect=RuntimeError("boom"),
        ):
            assert notify._send_discord(cfg, "msg") is False

    def test_deliver_discord_uses_nextcord_client(self):
        mock_channel = AsyncMock()
        mock_client = MagicMock()
        mock_client.login = AsyncMock()
        mock_client.fetch_channel = AsyncMock(return_value=mock_channel)
        mock_client.close = AsyncMock()
        embed = nextcord.Embed(title="Test")
        with patch("xync.notify.nextcord.Client", return_value=mock_client) as mock_cls:
            asyncio.run(notify._deliver_discord(BOT_TOKEN, 123, "", embed))
        mock_cls.assert_called_once()
        mock_client.login.assert_called_once_with(BOT_TOKEN)
        mock_client.fetch_channel.assert_called_once_with(123)
        mock_channel.send.assert_called_once_with(content=None, embed=embed)
        mock_client.close.assert_called_once()

    def test_discord_skips_when_empty_payload(self):
        cfg = _make_dc()
        with patch("xync.notify._deliver_discord") as mock_deliver:
            assert notify._send_discord(cfg) is False
        mock_deliver.assert_not_called()

    def test_discord_skips_when_unconfigured(self):
        cfg = DiscordConfig(bot_token=None, channel_id=CHANNEL_ID)
        with patch("xync.notify._deliver_discord") as mock_deliver:
            assert notify._send_discord(cfg, "msg") is False
        mock_deliver.assert_not_called()

    def test_discord_skips_when_channel_missing(self):
        cfg = DiscordConfig(bot_token=BOT_TOKEN, channel_id=None)
        with patch("xync.notify._deliver_discord") as mock_deliver:
            assert notify._send_discord(cfg, "msg") is False
        mock_deliver.assert_not_called()


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
        assert isinstance(embed, nextcord.Embed)
        assert "SUCCESS" in embed.title
        assert _embed_fields(embed).get("Mirror") == "ubuntu"

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
        assert "FAILED" in embed.title
        assert _embed_fields(embed).get("Error") == "rsync failed"

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
        with (
            patch("xync.notify.post_json") as mock_post,
            patch("xync.notify._deliver_discord") as mock_deliver,
        ):
            notify.notify_sync_result(gc, "ubuntu", SyncStatus.SUCCESS, 10.0)
        mock_post.assert_not_called()
        mock_deliver.assert_not_called()


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
        assert "ubuntu" in embed.title
        assert _embed_fields(embed).get("Mirror") == "ubuntu"

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
        with (
            patch("xync.notify.post_json") as mock_post,
            patch("xync.notify._deliver_discord") as mock_deliver,
        ):
            notify.notify_sync_start(gc, "ubuntu")
        mock_post.assert_not_called()
        mock_deliver.assert_not_called()


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
        fields = _embed_fields(embed)
        assert fields.get("Progress") == "70%"
        assert fields.get("Mirror") == "ubuntu"

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
        fields = _embed_fields(embed)
        assert fields.get("Usage") == "91.5%"
        assert fields.get("Path") == "/srv/mirrors/ubuntu"

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
        assert isinstance(embed, nextcord.Embed)
        assert "Test Notification" in embed.title

    def test_send_test_notification_unknown_channel(self):
        gc = _make_global()
        assert notify.send_test_notification(gc, "email") is False


class TestDiscordEmbeds:
    def test_start_embed(self):
        embed = notify.discord_start_embed("arch")
        assert isinstance(embed, nextcord.Embed)
        assert "arch" in embed.title
        assert embed.colour.value == notify._COLOR_INFO
        assert _embed_fields(embed).get("Mirror") == "arch"
        assert embed.footer.text == "xync"

    def test_result_embed_success(self):
        embed = notify.discord_result_embed("debian", SyncStatus.SUCCESS, 4.2)
        assert "SUCCESS" in embed.title
        assert embed.colour.value == notify._COLOR_SUCCESS
        assert _embed_fields(embed).get("Duration") == "4.2s"
        assert "Error" not in _embed_fields(embed)

    def test_result_embed_failure_truncates_long_error(self):
        long_error = "x" * 2000
        embed = notify.discord_result_embed(
            "debian", SyncStatus.FAILED, 1.0, error=long_error
        )
        assert "FAILED" in embed.title
        assert embed.colour.value == notify._COLOR_FAILURE
        error_value = _embed_fields(embed)["Error"]
        assert len(error_value) <= 1003
        assert error_value.endswith("...")

    def test_progress_embed(self):
        embed = notify.discord_progress_embed("ubuntu", 85)
        assert "ubuntu" in embed.title
        assert _embed_fields(embed).get("Progress") == "85%"

    def test_disk_embed(self):
        embed = notify.discord_disk_embed("ubuntu", 92.3, 90, "/data")
        assert "ubuntu" in embed.title
        assert embed.colour.value == notify._COLOR_WARNING
        fields = _embed_fields(embed)
        assert fields.get("Usage") == "92.3%"
        assert fields.get("Path") == "/data"

    def test_test_embed(self):
        embed = notify.discord_test_embed()
        assert "Test Notification" in embed.title
        assert embed.colour.value == notify._COLOR_SUCCESS
        assert embed.description == "Discord bot integration is working properly."
