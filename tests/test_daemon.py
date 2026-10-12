"""Tests for xync.daemon."""

from __future__ import annotations

import os
import signal
import time
from pathlib import Path

from xync.daemon import get_pid_file, is_running, read_pid, stop_daemon


def test_read_pid_missing(tmp_path: Path) -> None:
    assert read_pid(tmp_path / "nope.pid") is None


def test_read_pid_valid(tmp_path: Path) -> None:
    pf = tmp_path / "xync-daemon.pid"
    pf.write_text("12345")
    assert read_pid(pf) == 12345


def test_read_pid_invalid(tmp_path: Path) -> None:
    pf = tmp_path / "xync-daemon.pid"
    pf.write_text("not-a-number")
    assert read_pid(pf) is None


def test_is_running_false_when_no_pid_file(tmp_path: Path) -> None:
    assert not is_running(tmp_path / "xync-daemon.pid")


def test_is_running_true_for_current_process(tmp_path: Path) -> None:
    pf = tmp_path / "xync-daemon.pid"
    pf.write_text(str(os.getpid()))
    assert is_running(pf)


def test_is_running_false_for_stale_pid(tmp_path: Path) -> None:
    pf = tmp_path / "xync-daemon.pid"
    pf.write_text("99999999")
    assert not is_running(pf)


def test_stop_daemon_missing_pid_file(tmp_path: Path) -> None:
    assert not stop_daemon(tmp_path / "xync-daemon.pid")


def test_stop_daemon_stale_pid_cleans_up(tmp_path: Path) -> None:
    pf = tmp_path / "xync-daemon.pid"
    pf.write_text("99999999")
    assert not stop_daemon(pf)
    assert not pf.exists()


def test_stop_daemon_sigterm_waits_for_exit(tmp_path: Path) -> None:
    """stop_daemon must wait until the process actually exits."""
    pid = os.fork()
    if pid == 0:
        # Child: ignore SIGTERM so we can verify stop_daemon waits.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        time.sleep(30)
        os._exit(0)

    pf = tmp_path / "xync-daemon.pid"
    pf.write_text(str(pid))

    t0 = time.monotonic()
    result = stop_daemon(pf, timeout=0.5)
    elapsed = time.monotonic() - t0

    # Process ignored SIGTERM → stop_daemon should time out and return False.
    assert result is False
    assert elapsed >= 0.5

    # Clean up the child.
    os.kill(pid, signal.SIGKILL)
    os.waitpid(pid, 0)


def test_stop_daemon_sigkill_force(tmp_path: Path) -> None:
    """force=True sends SIGKILL and waits for exit."""
    # Auto-reap children so stop_daemon's os.kill(pid, 0) sees ProcessLookupError.
    signal.signal(signal.SIGCHLD, signal.SIG_IGN)

    pid = os.fork()
    if pid == 0:
        time.sleep(30)
        os._exit(0)

    pf = tmp_path / "xync-daemon.pid"
    pf.write_text(str(pid))

    t0 = time.monotonic()
    result = stop_daemon(pf, force=True, timeout=5.0)
    elapsed = time.monotonic() - t0

    assert result is True
    assert elapsed < 5.0
    assert not pf.exists()


def test_get_pid_file(tmp_path: Path) -> None:
    assert get_pid_file(tmp_path) == tmp_path / "xync-daemon.pid"
