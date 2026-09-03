"""Tests for xync.config."""

import pytest

from xync.config import get_config_path, load_config, save_config
from xync.models import Mirror, MirrorType, xyncConfig


@pytest.fixture
def tmp_config_dir(tmp_path):
    return tmp_path / "xync"


class TestLoadSaveConfig:
    def test_default_config_when_missing(self, tmp_config_dir):
        cfg = load_config(tmp_config_dir)
        assert cfg.version == 1
        assert cfg.mirrors == {}

    def test_save_and_reload_empty(self, tmp_config_dir):
        cfg = xyncConfig()
        save_config(cfg, tmp_config_dir)
        assert get_config_path(tmp_config_dir).exists()
        loaded = load_config(tmp_config_dir)
        assert loaded.version == 1
        assert loaded.mirrors == {}

    def test_save_and_reload_with_mirror(self, tmp_config_dir):
        cfg = xyncConfig()
        cfg.mirrors["ubuntu"] = Mirror(
            name="ubuntu",
            url="rsync://mirror.example.com/ubuntu",
            local_path="/srv/mirrors/ubuntu",
            description="Ubuntu mirror",
        )
        save_config(cfg, tmp_config_dir)

        loaded = load_config(tmp_config_dir)
        assert "ubuntu" in loaded.mirrors
        m = loaded.mirrors["ubuntu"]
        assert m.url == "rsync://mirror.example.com/ubuntu"
        assert m.local_path == "/srv/mirrors/ubuntu"
        assert m.description == "Ubuntu mirror"
        assert m.mirror_type == MirrorType.RSYNC

    def test_save_and_reload_http_mirror(self, tmp_config_dir):
        cfg = xyncConfig()
        cfg.mirrors["debian"] = Mirror(
            name="debian",
            url="http://ftp.debian.org/debian",
            local_path="/srv/mirrors/debian",
            mirror_type=MirrorType.HTTP,
        )
        save_config(cfg, tmp_config_dir)
        loaded = load_config(tmp_config_dir)
        assert loaded.mirrors["debian"].mirror_type == MirrorType.HTTP

    def test_global_config_roundtrip(self, tmp_config_dir):
        cfg = xyncConfig()
        cfg.global_config.max_log_files = 10
        cfg.global_config.parallel_jobs = 4
        cfg.global_config.log_dir = "/var/log/xync"
        save_config(cfg, tmp_config_dir)

        loaded = load_config(tmp_config_dir)
        assert loaded.global_config.max_log_files == 10
        assert loaded.global_config.parallel_jobs == 4
        assert loaded.global_config.log_dir == "/var/log/xync"

    def test_bandwidth_limit_roundtrip(self, tmp_config_dir):
        cfg = xyncConfig()
        cfg.mirrors["centos"] = Mirror(
            name="centos",
            url="rsync://mirror.example.com/centos",
            local_path="/srv/mirrors/centos",
            bandwidth_limit="5m",
        )
        save_config(cfg, tmp_config_dir)
        loaded = load_config(tmp_config_dir)
        assert loaded.mirrors["centos"].bandwidth_limit == "5m"

    def test_telegram_config_roundtrip(self, tmp_config_dir):
        cfg = xyncConfig()
        cfg.global_config.telegram.bot_token = "123456:ABC"
        cfg.global_config.telegram.chat_id = "-100987"
        cfg.global_config.telegram.notify_on_success = False
        cfg.global_config.telegram.notify_on_failure = True
        save_config(cfg, tmp_config_dir)
        loaded = load_config(tmp_config_dir)
        tg = loaded.global_config.telegram
        assert tg.bot_token == "123456:ABC"
        assert tg.chat_id == "-100987"
        assert tg.notify_on_success is False
        assert tg.notify_on_failure is True

    def test_telegram_config_defaults(self, tmp_config_dir):
        cfg = xyncConfig()
        save_config(cfg, tmp_config_dir)
        loaded = load_config(tmp_config_dir)
        tg = loaded.global_config.telegram
        assert tg.bot_token is None
        assert tg.chat_id is None
        assert tg.notify_on_success is True
        assert tg.notify_on_failure is True

    def test_discord_config_roundtrip(self, tmp_config_dir):
        cfg = xyncConfig()
        cfg.global_config.discord.bot_token = "discord-bot-token"
        cfg.global_config.discord.channel_id = "123456789"
        cfg.global_config.discord.notify_on_success = False
        cfg.global_config.discord.notify_on_failure = True
        save_config(cfg, tmp_config_dir)
        loaded = load_config(tmp_config_dir)
        dc = loaded.global_config.discord
        assert dc.bot_token == "discord-bot-token"
        assert dc.channel_id == "123456789"
        assert dc.notify_on_success is False
        assert dc.notify_on_failure is True

    def test_discord_config_defaults(self, tmp_config_dir):
        cfg = xyncConfig()
        save_config(cfg, tmp_config_dir)
        loaded = load_config(tmp_config_dir)
        dc = loaded.global_config.discord
        assert dc.bot_token is None
        assert dc.channel_id is None
        assert dc.notify_on_success is True
        assert dc.notify_on_failure is True

    def test_last_size_roundtrip(self, tmp_config_dir):
        cfg = xyncConfig()
        cfg.mirrors["ubuntu"] = Mirror(
            name="ubuntu",
            url="rsync://mirror.example.com/ubuntu",
            local_path="/srv/mirrors/ubuntu",
        )
        cfg.mirrors["ubuntu"].last_size = 12345678
        save_config(cfg, tmp_config_dir)
        loaded = load_config(tmp_config_dir)
        assert loaded.mirrors["ubuntu"].last_size == 12345678
