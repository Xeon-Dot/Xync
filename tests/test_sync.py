"""Tests for xync.sync."""

from unittest.mock import MagicMock, patch

import pytest

from xync.models import Mirror, MirrorType, SyncStatus
from xync.sync import (
    _build_rsync_command,
    _build_wget_command,
    _inject_rsync_progress_flag,
    acquire_lock,
    purge_old_logs,
    sync_mirror,
)


@pytest.fixture
def rsync_mirror():
    return Mirror(  # pyright: ignore[reportCallIssue]
        name="ubuntu",
        url="rsync://mirror.example.com/ubuntu",
        local_path="/tmp/xync_test_ubuntu",
        mirror_type=MirrorType.RSYNC,
    )


@pytest.fixture
def http_mirror():
    return Mirror(  # pyright: ignore[reportCallIssue]
        name="debian",
        url="http://ftp.debian.org/debian",
        local_path="/tmp/xync_test_debian",
        mirror_type=MirrorType.HTTP,
    )


class TestBuildCommand:
    def test_rsync_basic(self, rsync_mirror):
        with patch("xync.sync.shutil.which", return_value="/usr/bin/rsync"):
            cmd = _build_rsync_command(rsync_mirror)
        assert cmd[0] == "rsync"
        assert "-avz" in cmd
        assert "--delete" in cmd
        assert rsync_mirror.url.rstrip("/") + "/" in cmd
        assert rsync_mirror.local_path.rstrip("/") + "/" in cmd

    def test_rsync_with_bwlimit(self, rsync_mirror):
        rsync_mirror.bandwidth_limit = "10m"
        with patch("xync.sync.shutil.which", return_value="/usr/bin/rsync"):
            cmd = _build_rsync_command(rsync_mirror)
        assert "--bwlimit=10m" in cmd

    def test_rsync_not_installed(self, rsync_mirror):
        with patch("xync.sync.shutil.which", return_value=None):
            with pytest.raises(FileNotFoundError, match="rsync"):
                _build_rsync_command(rsync_mirror)

    def test_wget_basic(self, http_mirror):
        with patch("xync.sync.shutil.which", return_value="/usr/bin/wget"):
            cmd = _build_wget_command(http_mirror)
        assert cmd[0] == "wget"
        assert "--mirror" in cmd
        assert http_mirror.url in cmd
        assert http_mirror.local_path in cmd

    def test_wget_not_installed(self, http_mirror):
        with patch("xync.sync.shutil.which", return_value=None):
            with pytest.raises(FileNotFoundError, match="wget"):
                _build_wget_command(http_mirror)


class TestSyncMirror:
    def test_dry_run(self, rsync_mirror, tmp_path):
        with patch("xync.sync.shutil.which", return_value="/usr/bin/rsync"):
            result = sync_mirror(rsync_mirror, tmp_path / "logs", dry_run=True)
        assert result.status == SyncStatus.PENDING
        assert result.mirror_name == "ubuntu"
        assert result.size_bytes is None

    def test_successful_sync(self, rsync_mirror, tmp_path):
        mock_result = MagicMock()
        mock_result.returncode = 0
        with (
            patch("xync.sync.shutil.which", return_value="/usr/bin/rsync"),
            patch("xync.sync.subprocess.run", return_value=mock_result),
        ):
            result = sync_mirror(rsync_mirror, tmp_path / "logs")
        assert result.status == SyncStatus.SUCCESS
        assert result.error is None
        assert result.duration_seconds >= 0
        assert result.size_bytes == 0  # local_path does not exist in test

    def test_failed_sync(self, rsync_mirror, tmp_path):
        mock_result = MagicMock()
        mock_result.returncode = 23
        with (
            patch("xync.sync.shutil.which", return_value="/usr/bin/rsync"),
            patch("xync.sync.subprocess.run", return_value=mock_result),
        ):
            result = sync_mirror(rsync_mirror, tmp_path / "logs")
        assert result.status == SyncStatus.FAILED
        assert "23" in result.error  # ty:ignore[unsupported-operator]  # pyright: ignore[reportOperatorIssue]
        assert result.size_bytes is None

    def test_command_not_found(self, rsync_mirror, tmp_path):
        with patch("xync.sync.shutil.which", return_value=None):
            result = sync_mirror(rsync_mirror, tmp_path / "logs")
        assert result.status == SyncStatus.FAILED
        assert result.error is not None


class TestPurgeOldLogs:
    def test_purge_excess_logs(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        for i in range(10):
            (log_dir / f"ubuntu-2024010{i:01d}T000000Z.log").write_text(f"log {i}")

        removed = purge_old_logs(log_dir, "ubuntu", max_files=5)
        assert removed == 5
        remaining = list(log_dir.glob("ubuntu-*.log"))
        assert len(remaining) == 5

    def test_no_purge_when_under_limit(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        for i in range(3):
            (log_dir / f"ubuntu-2024010{i}T000000Z.log").write_text(f"log {i}")

        removed = purge_old_logs(log_dir, "ubuntu", max_files=10)
        assert removed == 0

    def test_purge_empty_dir(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        removed = purge_old_logs(log_dir, "ubuntu", max_files=5)
        assert removed == 0


class TestInjectRsyncProgressFlag:
    def test_injects_flag_when_absent(self):
        cmd = ["rsync", "-avz", "rsync://src/", "/dst/"]
        result = _inject_rsync_progress_flag(cmd)
        assert result[1] == "--info=progress2"
        assert result[0] == "rsync"
        assert "-avz" in result

    def test_no_duplicate_info_progress2(self):
        cmd = ["rsync", "--info=progress2", "-avz", "rsync://src/", "/dst/"]
        result = _inject_rsync_progress_flag(cmd)
        assert result.count("--info=progress2") == 1

    def test_no_duplicate_when_progress_present(self):
        cmd = ["rsync", "--progress", "-avz", "rsync://src/", "/dst/"]
        result = _inject_rsync_progress_flag(cmd)
        assert "--info=progress2" not in result

    def test_returns_new_list(self):
        cmd = ["rsync", "-avz", "rsync://src/", "/dst/"]
        result = _inject_rsync_progress_flag(cmd)
        assert result is not cmd


class TestSyncMirrorWithProgress:
    def test_progress_callback_called_at_milestones(self, rsync_mirror, tmp_path):
        """Verify that the on_progress callback fires at each 10 % milestone."""
        progress_calls = []

        rsync_output = (
            "      0   0%    0.00kB/s    0:00:00 (xfr#0, to-chk=100/100)\n"
            "      1  10%    1.00MB/s    0:00:01 (xfr#1, to-chk=90/100)\n"
            "      2  20%    1.00MB/s    0:00:02 (xfr#2, to-chk=80/100)\n"
            "      3  50%    1.00MB/s    0:00:03 (xfr#3, to-chk=50/100)\n"
            "      4 100%    1.00MB/s    0:00:04 (xfr#4, to-chk=0/100)\n"
        )

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = iter(rsync_output.splitlines(keepends=True))
        mock_proc.__enter__ = lambda s: s
        mock_proc.__exit__ = MagicMock(return_value=False)

        with (
            patch("xync.sync.shutil.which", return_value="/usr/bin/rsync"),
            patch("xync.sync.subprocess.Popen", return_value=mock_proc),
        ):
            result = sync_mirror(
                rsync_mirror,
                tmp_path / "logs",
                on_progress=progress_calls.append,
            )

        assert result.status == SyncStatus.SUCCESS
        # Expect milestones 0, 10, 20, 50, 100 (each fired only once)
        assert progress_calls == [0, 10, 20, 50, 100]

    def test_no_progress_callback_uses_subprocess_run(self, rsync_mirror, tmp_path):
        """Without a callback, subprocess.run should be used (not Popen)."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        with (
            patch("xync.sync.shutil.which", return_value="/usr/bin/rsync"),
            patch("xync.sync.subprocess.run", return_value=mock_result) as mock_run,
            patch("xync.sync.subprocess.Popen") as mock_popen,
        ):
            sync_mirror(rsync_mirror, tmp_path / "logs")
        mock_run.assert_called_once()
        mock_popen.assert_not_called()

    def test_progress_callback_not_used_for_http(self, http_mirror, tmp_path):
        """Progress callback is ignored for HTTP mirrors (Popen not used)."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        with (
            patch("xync.sync.shutil.which", return_value="/usr/bin/wget"),
            patch("xync.sync.subprocess.run", return_value=mock_result) as mock_run,
            patch("xync.sync.subprocess.Popen") as mock_popen,
        ):
            sync_mirror(http_mirror, tmp_path / "logs", on_progress=lambda pct: None)
        mock_run.assert_called_once()
        mock_popen.assert_not_called()


class TestAcquireLock:
    def test_acquires_when_no_lock_file(self, tmp_path):
        lock_path = tmp_path / "test.lock"
        assert acquire_lock(lock_path) is True
        assert lock_path.exists()

    def test_fails_when_lock_held_by_running_process(self, tmp_path):
        import os

        lock_path = tmp_path / "test.lock"
        lock_path.write_text(str(os.getpid()))
        assert acquire_lock(lock_path) is False

    def test_clears_stale_lock_from_dead_process(self, tmp_path):
        lock_path = tmp_path / "test.lock"
        # PID 1 is init/systemd on Linux, System Idle Process on Windows —
        # never our process, so we can't own its lock. Use a PID that is
        # guaranteed not to exist: max PID + 1 overflows to an invalid PID.
        lock_path.write_text("999999999")  # PID that cannot exist
        assert acquire_lock(lock_path) is True
        assert lock_path.exists()

    def test_stale_lock_allows_subsequent_sync(self, rsync_mirror, tmp_path):
        """A lock left by a dead process must not block the next sync."""
        log_dir = tmp_path / "logs"
        lock_dir = log_dir.parent / "locks"
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_path = lock_dir / f"{rsync_mirror.name}.lock"
        lock_path.write_text("999999999")  # stale lock from dead process

        mock_result = MagicMock()
        mock_result.returncode = 0
        with (
            patch("xync.sync.shutil.which", return_value="/usr/bin/rsync"),
            patch("xync.sync.subprocess.run", return_value=mock_result),
        ):
            result = sync_mirror(rsync_mirror, log_dir)

        assert result.status == SyncStatus.SUCCESS
