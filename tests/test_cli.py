"""Tests for the Typer CLI (xync.main)."""

from pathlib import Path

from typer.testing import CliRunner

from xync.main import app
from xync.models import SyncStatus
from xync.sync import SyncResult

runner = CliRunner()


def make_cfg_opt(tmp_path: Path) -> list[str]:
    return ["--config-dir", str(tmp_path)]


class TestInit:
    def test_init_creates_config(self, tmp_path):
        result = runner.invoke(app, ["init"] + make_cfg_opt(tmp_path))
        assert result.exit_code == 0, result.output
        assert (tmp_path / "config.toml").exists()

    def test_init_idempotent(self, tmp_path):
        runner.invoke(app, ["init"] + make_cfg_opt(tmp_path))
        result = runner.invoke(app, ["init"] + make_cfg_opt(tmp_path))
        assert result.exit_code == 0
        assert "already exists" in result.output


class TestMirrorAdd:
    def test_add_rsync_mirror(self, tmp_path):
        result = runner.invoke(
            app,
            [
                "mirror",
                "add",
                "ubuntu",
                "rsync://mirror.example.com/ubuntu",
                "/srv/mirrors/ubuntu",
            ]
            + make_cfg_opt(tmp_path),
        )
        assert result.exit_code == 0, result.output
        assert "ubuntu" in result.output

    def test_add_http_mirror(self, tmp_path):
        result = runner.invoke(
            app,
            [
                "mirror",
                "add",
                "debian",
                "http://ftp.debian.org/debian",
                "/srv/mirrors/debian",
                "--type",
                "http",
            ]
            + make_cfg_opt(tmp_path),
        )
        assert result.exit_code == 0, result.output

    def test_duplicate_mirror_fails(self, tmp_path):
        args = [
            "mirror",
            "add",
            "ubuntu",
            "rsync://mirror.example.com/ubuntu",
            "/srv/mirrors/ubuntu",
        ] + make_cfg_opt(tmp_path)
        runner.invoke(app, args)
        result = runner.invoke(app, args)
        assert result.exit_code != 0
        assert "already exists" in result.output

    def test_add_invalid_url_fails(self, tmp_path):
        result = runner.invoke(
            app,
            [
                "mirror",
                "add",
                "bad",
                "noscheme.example.com/path",
                "/srv/mirrors/bad",
            ]
            + make_cfg_opt(tmp_path),
        )
        assert result.exit_code != 0

    def test_add_invalid_name_fails(self, tmp_path):
        result = runner.invoke(
            app,
            [
                "mirror",
                "add",
                "bad name!",
                "rsync://mirror.example.com/path",
                "/srv/mirrors/bad",
            ]
            + make_cfg_opt(tmp_path),
        )
        assert result.exit_code != 0


class TestMirrorList:
    def test_list_empty(self, tmp_path):
        result = runner.invoke(app, ["mirror", "list"] + make_cfg_opt(tmp_path))
        assert result.exit_code == 0
        assert "No mirrors" in result.output

    def test_list_shows_mirror(self, tmp_path):
        runner.invoke(
            app,
            [
                "mirror",
                "add",
                "ubuntu",
                "rsync://mirror.example.com/ubuntu",
                "/srv/mirrors/ubuntu",
            ]
            + make_cfg_opt(tmp_path),
        )
        result = runner.invoke(app, ["mirror", "list"] + make_cfg_opt(tmp_path))
        assert result.exit_code == 0
        assert "ubuntu" in result.output


class TestMirrorRemove:
    def test_remove_existing(self, tmp_path):
        runner.invoke(
            app,
            [
                "mirror",
                "add",
                "ubuntu",
                "rsync://mirror.example.com/ubuntu",
                "/srv/mirrors/ubuntu",
            ]
            + make_cfg_opt(tmp_path),
        )
        result = runner.invoke(
            app, ["mirror", "remove", "ubuntu", "--yes"] + make_cfg_opt(tmp_path)
        )
        assert result.exit_code == 0
        assert "Removed" in result.output

    def test_remove_missing_fails(self, tmp_path):
        result = runner.invoke(
            app, ["mirror", "remove", "nonexistent", "--yes"] + make_cfg_opt(tmp_path)
        )
        assert result.exit_code != 0


class TestMirrorShow:
    def test_show_existing(self, tmp_path):
        runner.invoke(
            app,
            [
                "mirror",
                "add",
                "ubuntu",
                "rsync://mirror.example.com/ubuntu",
                "/srv/mirrors/ubuntu",
                "--description",
                "Ubuntu LTS mirror",
            ]
            + make_cfg_opt(tmp_path),
        )
        result = runner.invoke(
            app, ["mirror", "show", "ubuntu"] + make_cfg_opt(tmp_path)
        )
        assert result.exit_code == 0
        assert "ubuntu" in result.output
        assert "Ubuntu LTS mirror" in result.output

    def test_show_missing_fails(self, tmp_path):
        result = runner.invoke(
            app, ["mirror", "show", "nonexistent"] + make_cfg_opt(tmp_path)
        )
        assert result.exit_code != 0


class TestMirrorEnableDisable:
    def _add_mirror(self, tmp_path):
        runner.invoke(
            app,
            [
                "mirror",
                "add",
                "ubuntu",
                "rsync://mirror.example.com/ubuntu",
                "/srv/mirrors/ubuntu",
            ]
            + make_cfg_opt(tmp_path),
        )

    def test_disable_mirror(self, tmp_path):
        self._add_mirror(tmp_path)
        result = runner.invoke(
            app, ["mirror", "disable", "ubuntu"] + make_cfg_opt(tmp_path)
        )
        assert result.exit_code == 0
        assert "disabled" in result.output

    def test_enable_mirror(self, tmp_path):
        self._add_mirror(tmp_path)
        runner.invoke(app, ["mirror", "disable", "ubuntu"] + make_cfg_opt(tmp_path))
        result = runner.invoke(
            app, ["mirror", "enable", "ubuntu"] + make_cfg_opt(tmp_path)
        )
        assert result.exit_code == 0
        assert "enabled" in result.output


class TestStatus:
    def test_status_no_mirrors(self, tmp_path):
        result = runner.invoke(app, ["status"] + make_cfg_opt(tmp_path))
        assert result.exit_code == 0
        assert "No mirrors" in result.output

    def test_status_shows_mirror(self, tmp_path):
        runner.invoke(
            app,
            [
                "mirror",
                "add",
                "ubuntu",
                "rsync://mirror.example.com/ubuntu",
                "/srv/mirrors/ubuntu",
            ]
            + make_cfg_opt(tmp_path),
        )
        result = runner.invoke(app, ["status"] + make_cfg_opt(tmp_path))
        assert result.exit_code == 0
        assert "ubuntu" in result.output


class TestConfigCommands:
    def test_config_show(self, tmp_path):
        result = runner.invoke(app, ["config", "show"] + make_cfg_opt(tmp_path))
        assert result.exit_code == 0
        assert "max_log_files" in result.output

    def test_config_show_includes_telegram(self, tmp_path):
        result = runner.invoke(app, ["config", "show"] + make_cfg_opt(tmp_path))
        assert result.exit_code == 0
        assert "telegram" in result.output

    def test_config_set_max_log_files(self, tmp_path):
        result = runner.invoke(
            app, ["config", "set", "max_log_files", "20"] + make_cfg_opt(tmp_path)
        )
        assert result.exit_code == 0
        assert "max_log_files" in result.output

    def test_config_set_invalid_key(self, tmp_path):
        result = runner.invoke(
            app, ["config", "set", "nonexistent_key", "value"] + make_cfg_opt(tmp_path)
        )
        assert result.exit_code != 0

    def test_config_set_invalid_int(self, tmp_path):
        result = runner.invoke(
            app,
            ["config", "set", "max_log_files", "not_a_number"] + make_cfg_opt(tmp_path),
        )
        assert result.exit_code != 0

    def test_config_set_disk_usage_warning_percent(self, tmp_path):
        result = runner.invoke(
            app,
            ["config", "set", "disk_usage_warning_percent", "85"]
            + make_cfg_opt(tmp_path),
        )
        assert result.exit_code == 0
        assert "disk_usage_warning_percent" in result.output

    def test_config_set_telegram_bot_token(self, tmp_path):
        result = runner.invoke(
            app,
            ["config", "set", "telegram.bot_token", "123456:ABC-DEF"]
            + make_cfg_opt(tmp_path),
        )
        assert result.exit_code == 0
        assert "telegram.bot_token" in result.output

    def test_config_set_telegram_chat_id(self, tmp_path):
        result = runner.invoke(
            app,
            ["config", "set", "telegram.chat_id", "100123456"] + make_cfg_opt(tmp_path),
        )
        assert result.exit_code == 0
        assert "telegram.chat_id" in result.output

    def test_config_set_telegram_notify_on_success(self, tmp_path):
        result = runner.invoke(
            app,
            ["config", "set", "telegram.notify_on_success", "false"]
            + make_cfg_opt(tmp_path),
        )
        assert result.exit_code == 0

    def test_config_set_telegram_notify_on_failure(self, tmp_path):
        result = runner.invoke(
            app,
            ["config", "set", "telegram.notify_on_failure", "true"]
            + make_cfg_opt(tmp_path),
        )
        assert result.exit_code == 0

    def test_config_set_telegram_bool_invalid(self, tmp_path):
        result = runner.invoke(
            app,
            ["config", "set", "telegram.notify_on_success", "maybe"]
            + make_cfg_opt(tmp_path),
        )
        assert result.exit_code != 0

    def test_config_set_rejects_bare_nested_section(self, tmp_path):
        result = runner.invoke(
            app, ["config", "set", "telegram", "foo"] + make_cfg_opt(tmp_path)
        )
        assert result.exit_code != 0


class TestSync:
    def test_sync_no_mirrors(self, tmp_path):
        result = runner.invoke(app, ["sync"] + make_cfg_opt(tmp_path))
        assert result.exit_code == 0
        assert "No mirrors" in result.output

    def test_sync_dry_run(self, tmp_path):
        runner.invoke(
            app,
            [
                "mirror",
                "add",
                "ubuntu",
                "rsync://mirror.example.com/ubuntu",
                "/srv/mirrors/ubuntu",
            ]
            + make_cfg_opt(tmp_path),
        )
        result = runner.invoke(app, ["sync", "--dry-run"] + make_cfg_opt(tmp_path))
        assert result.exit_code == 0

    def test_sync_missing_mirror_fails(self, tmp_path):
        result = runner.invoke(app, ["sync", "nonexistent"] + make_cfg_opt(tmp_path))
        assert result.exit_code != 0

    def test_sends_start_before_result_notifications(
        self, tmp_path, mocker
    ):
        runner.invoke(
            app,
            [
                "mirror",
                "add",
                "ubuntu",
                "rsync://mirror.example.com/ubuntu",
                str(tmp_path / "ubuntu"),
            ]
            + make_cfg_opt(tmp_path),
        )
        calls = []
        mocker.patch(
            "xync.sync.sync_mirror",
            return_value=SyncResult("ubuntu", SyncStatus.SUCCESS, 1.0),
        )
        mocker.patch(
            "xync.notify.notify_sync_start",
            lambda *args: calls.append("start"),
        )
        mocker.patch(
            "xync.notify.notify_sync_result",
            lambda *args: calls.append("result"),
        )
        mocker.patch("xync.notify.notify_disk_warning")
        mocker.patch("xync.sync.purge_old_logs")

        result = runner.invoke(app, ["sync", "ubuntu"] + make_cfg_opt(tmp_path))

        assert result.exit_code == 0, result.output
        assert calls == ["start", "result"]


class TestHealth:
    def test_health_no_mirrors_warns_but_succeeds(self, tmp_path):
        result = runner.invoke(app, ["health"] + make_cfg_opt(tmp_path))
        assert result.exit_code == 0
        assert "no mirrors configured" in result.output

    def test_health_checks_mirror(self, tmp_path, mocker):
        mocker.patch("xync.main.shutil.which", return_value="/usr/bin/rsync")
        local_path = tmp_path / "ubuntu"
        result = runner.invoke(
            app,
            [
                "mirror",
                "add",
                "ubuntu",
                "rsync://mirror.example.com/ubuntu",
                str(local_path),
            ]
            + make_cfg_opt(tmp_path),
        )
        assert result.exit_code == 0, result.output

        result = runner.invoke(app, ["health"] + make_cfg_opt(tmp_path))
        assert result.exit_code == 0, result.output
        assert "ubuntu" in result.output
        assert "disk" in result.output


class TestNotifyCommands:
    def test_notify_test_telegram(self, tmp_path, mocker):
        runner.invoke(
            app,
            ["config", "set", "telegram.bot_token", "tok123"] + make_cfg_opt(tmp_path),
        )
        runner.invoke(
            app,
            ["config", "set", "telegram.chat_id", "chat456"] + make_cfg_opt(tmp_path),
        )
        mock_send = mocker.patch(
            "xync.main.send_test_notification", return_value=True
        )

        result = runner.invoke(
            app, ["notify", "test", "telegram"] + make_cfg_opt(tmp_path)
        )

        assert result.exit_code == 0, result.output
        assert "telegram" in result.output
        mock_send.assert_called_once()

    def test_notify_test_invalid_channel_fails(self, tmp_path):
        result = runner.invoke(
            app, ["notify", "test", "email"] + make_cfg_opt(tmp_path)
        )
        assert result.exit_code != 0


class TestDaemonCommands:
    """Tests for xync daemon start / stop / status."""

    def test_daemon_status_not_running(self, tmp_path):
        result = runner.invoke(app, ["daemon", "status"] + make_cfg_opt(tmp_path))
        assert result.exit_code == 0
        assert "not running" in result.output

    def test_daemon_stop_not_running(self, tmp_path):
        result = runner.invoke(app, ["daemon", "stop"] + make_cfg_opt(tmp_path))
        assert result.exit_code == 0
        assert "not running" in result.output

    def test_daemon_status_running(self, tmp_path, mocker):
        mocker.patch("xync.daemon.is_running", return_value=True)
        mocker.patch("xync.daemon.read_pid", return_value=12345)
        result = runner.invoke(app, ["daemon", "status"] + make_cfg_opt(tmp_path))
        assert result.exit_code == 0
        assert "12345" in result.output

    def test_daemon_stop_sends_sigterm(self, tmp_path, mocker):
        mocker.patch("xync.daemon.is_running", return_value=True)
        mocker.patch("xync.daemon.read_pid", return_value=12345)
        mock_stop = mocker.patch("xync.daemon.stop_daemon", return_value=True)
        result = runner.invoke(app, ["daemon", "stop"] + make_cfg_opt(tmp_path))
        assert result.exit_code == 0
        assert "12345" in result.output
        mock_stop.assert_called_once()

    def test_daemon_start_already_running(self, tmp_path, mocker):
        mocker.patch("xync.daemon.is_running", return_value=True)
        mocker.patch("xync.daemon.read_pid", return_value=12345)
        result = runner.invoke(app, ["daemon", "start"] + make_cfg_opt(tmp_path))
        assert result.exit_code != 0
        assert "already running" in result.output

    def test_daemon_start_forks(self, tmp_path, mocker):
        mocker.patch("xync.daemon.is_running", return_value=False)
        mock_daemonize = mocker.patch("xync.daemon.daemonize")
        mock_loop = mocker.patch("xync.daemon.run_daemon_loop")
        result = runner.invoke(app, ["daemon", "start"] + make_cfg_opt(tmp_path))
        assert result.exit_code == 0
        mock_daemonize.assert_called_once()
        mock_loop.assert_called_once()

    def test_daemon_start_custom_interval(self, tmp_path, mocker):
        mocker.patch("xync.daemon.is_running", return_value=False)
        mocker.patch("xync.daemon.daemonize")
        mock_loop = mocker.patch("xync.daemon.run_daemon_loop")
        result = runner.invoke(
            app,
            ["daemon", "start", "--interval", "1800"] + make_cfg_opt(tmp_path),
        )
        assert result.exit_code == 0
        _cfg_dir, _names, interval, _api_enabled, _api_port = mock_loop.call_args[0]
        assert interval == 1800

    def test_daemon_start_uses_config_interval(self, tmp_path, mocker):
        runner.invoke(
            app,
            ["config", "set", "daemon_interval", "7200"] + make_cfg_opt(tmp_path),
        )
        mocker.patch("xync.daemon.is_running", return_value=False)
        mocker.patch("xync.daemon.daemonize")
        mock_loop = mocker.patch("xync.daemon.run_daemon_loop")
        runner.invoke(app, ["daemon", "start"] + make_cfg_opt(tmp_path))
        _cfg_dir, _names, interval, _api_enabled, _api_port = mock_loop.call_args[0]
        assert interval == 7200

    def test_daemon_stop_sends_sigkill_with_force(self, tmp_path, mocker):
        mocker.patch("xync.daemon.is_running", return_value=True)
        mocker.patch("xync.daemon.read_pid", return_value=12345)
        mock_stop = mocker.patch("xync.daemon.stop_daemon", return_value=True)
        result = runner.invoke(
            app, ["daemon", "stop", "--force"] + make_cfg_opt(tmp_path)
        )
        assert result.exit_code == 0
        assert "SIGKILL" in result.output
        mock_stop.assert_called_once_with(mocker.ANY, True)

    def test_daemon_sends_start_before_result_notifications(
        self, tmp_path, mocker
    ):
        from xync.config import load_config, save_config
        from xync.daemon import run_daemon_loop
        from xync.models import Mirror, MirrorType

        cfg = load_config(tmp_path)
        cfg.mirrors["ubuntu"] = Mirror(  # pyright: ignore[reportCallIssue]
            name="ubuntu",
            url="rsync://mirror.example.com/ubuntu",
            local_path=str(tmp_path / "ubuntu"),
            mirror_type=MirrorType.RSYNC,
        )
        save_config(cfg, tmp_path)
        calls = []

        def stop_after_cycle(_seconds, running):
            running[0] = False

        mocker.patch("xync.daemon._sleep_interruptible", stop_after_cycle)
        mocker.patch(
            "xync.sync.sync_mirror",
            return_value=SyncResult("ubuntu", SyncStatus.SUCCESS, 1.0),
        )
        mocker.patch(
            "xync.notify.notify_sync_start",
            lambda *args: calls.append("start"),
        )
        mocker.patch(
            "xync.notify.notify_sync_result",
            lambda *args: calls.append("result"),
        )
        mocker.patch("xync.notify.disk_usage_for_path", return_value=None)
        mocker.patch("xync.sync.purge_old_logs")

        run_daemon_loop(tmp_path, ["ubuntu"], interval=1)

        assert calls == ["start", "result"]
