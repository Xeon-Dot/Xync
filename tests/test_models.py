"""Tests for xync.models."""

import pytest
from pydantic import ValidationError

from xync.models import GlobalConfig, Mirror, MirrorType, SyncStatus, xyncConfig


class TestMirror:
    def test_valid_rsync_mirror(self):
        m = Mirror(
            name="ubuntu",
            url="rsync://mirror.example.com/ubuntu",
            local_path="/srv/mirrors/ubuntu",
        )
        assert m.name == "ubuntu"
        assert m.mirror_type == MirrorType.RSYNC
        assert m.enabled is True
        assert m.last_status == SyncStatus.NEVER

    def test_valid_http_mirror(self):
        m = Mirror(
            name="debian",
            url="http://ftp.debian.org/debian",
            local_path="/srv/mirrors/debian",
            mirror_type=MirrorType.HTTP,
        )
        assert m.mirror_type == MirrorType.HTTP

    def test_invalid_name_special_chars(self):
        with pytest.raises(ValidationError):
            Mirror(
                name="bad name!",
                url="rsync://mirror.example.com/ubuntu",
                local_path="/srv/mirrors/ubuntu",
            )

    def test_invalid_url_no_scheme(self):
        with pytest.raises(ValidationError):
            Mirror(
                name="ubuntu",
                url="mirror.example.com/ubuntu",
                local_path="/srv/mirrors/ubuntu",
            )

    def test_bandwidth_limit(self):
        m = Mirror(
            name="centos",
            url="rsync://mirror.example.com/centos",
            local_path="/srv/mirrors/centos",
            bandwidth_limit="10m",
        )
        assert m.bandwidth_limit == "10m"

    def test_default_rsync_options(self):
        m = Mirror(
            name="arch",
            url="rsync://mirror.example.com/arch",
            local_path="/srv/mirrors/arch",
        )
        assert "-avz" in m.rsync_options
        assert "--delete" in m.rsync_options

    def test_default_last_size_is_none(self):
        m = Mirror(
            name="arch",
            url="rsync://mirror.example.com/arch",
            local_path="/srv/mirrors/arch",
        )
        assert m.last_size is None


class TestxyncConfig:
    def test_default_config(self):
        cfg = xyncConfig()
        assert cfg.version == 1
        assert isinstance(cfg.global_config, GlobalConfig)
        assert cfg.mirrors == {}

    def test_add_mirror(self):
        cfg = xyncConfig()
        cfg.mirrors["ubuntu"] = Mirror(
            name="ubuntu",
            url="rsync://mirror.example.com/ubuntu",
            local_path="/srv/mirrors/ubuntu",
        )
        assert "ubuntu" in cfg.mirrors


class TestGlobalConfigValidation:
    @pytest.mark.parametrize(
        "field", ["max_log_files", "parallel_jobs", "daemon_interval"]
    )
    def test_positive_integer_fields_must_be_positive(self, field):
        with pytest.raises(ValidationError):
            GlobalConfig(**{field: 0})

    @pytest.mark.parametrize("port", [0, 70000])
    def test_api_port_range(self, port):
        with pytest.raises(ValidationError):
            GlobalConfig(api_port=port)
