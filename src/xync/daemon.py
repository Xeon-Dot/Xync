"""Background daemon support for xync."""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import FrameType
from typing import Optional

from xync.config import get_config_dir, load_config
from xync.sync import run_sync_batch

logger = logging.getLogger(__name__)

_PID_FILENAME = "xync-daemon.pid"
_DAEMON_LOG_FILENAME = "daemon.log"


# ---------------------------------------------------------------------------
# PID helpers
# ---------------------------------------------------------------------------


def get_pid_file(config_dir: Path) -> Path:
    """Return the path to the daemon PID file."""
    return config_dir / _PID_FILENAME


def get_daemon_log_file(config_dir: Path) -> Path:
    """Return the path to the daemon log file."""
    return config_dir / "logs" / _DAEMON_LOG_FILENAME


def read_pid(pid_file: Path) -> Optional[int]:
    """Read the PID from *pid_file*; return ``None`` if missing or invalid."""
    try:
        return int(pid_file.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def is_running(pid_file: Path) -> bool:
    """Return ``True`` if the daemon process recorded in *pid_file* is alive."""
    pid = read_pid(pid_file)
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we don't own it.
        return True


def stop_daemon(pid_file: Path, force: bool = False) -> bool:
    """Send SIGTERM (or SIGKILL with force=True) to the recorded daemon process.

    Returns ``True`` if a signal was delivered, ``False`` if the process was
    not found (stale PID file is cleaned up automatically).
    """
    pid = read_pid(pid_file)
    if pid is None:
        return False
    try:
        os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)
        return True
    except ProcessLookupError:
        pid_file.unlink(missing_ok=True)
        return False


# ---------------------------------------------------------------------------
# Daemonise
# ---------------------------------------------------------------------------


def daemonize(log_file: Path) -> None:
    """Double-fork daemonise the current process.

    After this call returns the caller is running as a proper Unix daemon:

    * Detached from any controlling terminal.
    * In a new session (``os.setsid``).
    * Working directory changed to ``/``.
    * ``stdin`` redirected to ``/dev/null``.
    * ``stdout`` / ``stderr`` redirected to *log_file* (append mode).

    The two intermediate parent processes exit with ``sys.exit(0)`` so the
    shell that invoked *xync* regains control immediately.

    Raises:
        RuntimeError: if either ``os.fork`` call fails.
    """
    log_file.parent.mkdir(parents=True, exist_ok=True)

    # ---- first fork --------------------------------------------------------
    try:
        pid = os.fork()
        if pid > 0:
            sys.exit(0)
    except OSError as exc:
        raise RuntimeError(f"First fork failed: {exc}") from exc

    os.setsid()
    os.umask(0o022)

    # ---- second fork -------------------------------------------------------
    try:
        pid = os.fork()
        if pid > 0:
            sys.exit(0)
    except OSError as exc:
        raise RuntimeError(f"Second fork failed: {exc}") from exc

    # ---- redirect standard file descriptors --------------------------------
    os.chdir("/")

    with open(os.devnull, "r") as devnull_fh:
        os.dup2(devnull_fh.fileno(), sys.stdin.fileno())

    log_fh = open(log_file, "a", encoding="utf-8")  # noqa: SIM115
    os.dup2(log_fh.fileno(), sys.stdout.fileno())
    os.dup2(log_fh.fileno(), sys.stderr.fileno())
    log_fh.close()


# ---------------------------------------------------------------------------
# Daemon loop
# ---------------------------------------------------------------------------


def _log(msg: str) -> None:
    """Write a timestamped message to stdout (which the daemon routes to its log)."""
    print(f"[{datetime.now(tz=timezone.utc).isoformat()}] {msg}", flush=True)


def _sleep_interruptible(seconds: float, running: list[bool]) -> None:
    """Sleep for *seconds*, checking *running* every 5 s."""
    elapsed = 0.0
    while running[0] and elapsed < seconds:
        step = min(5, seconds - elapsed)
        time.sleep(step)
        elapsed += step


def run_daemon_loop(
    config_dir: Path,
    names: Optional[list[str]],
    interval: int,
    api_enabled: bool = False,
    api_port: int = 58080,
) -> None:
    """Write the PID file then run the sync loop until SIGTERM is received.

    Args:
        config_dir: xync configuration directory (resolved absolute path).
        names: Mirror names to sync.  ``None`` means *all enabled* mirrors.
        interval: Seconds to wait between sync cycles (fallback when no cron).
        api_enabled: If True, start the API server in a background thread.
        api_port: Port for the API server.
    """
    # Late import: xync.api imports this module's PID helpers at load time.
    from xync.api import init_api_state, start_api_server_thread  # noqa: PLC0415

    pid_file = get_pid_file(config_dir)
    pid_file.write_text(str(os.getpid()))

    # Graceful shutdown flag.
    running = [True]

    def _handle_signal(signum: int, frame: Optional[FrameType]) -> None:
        running[0] = False

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    if api_enabled:
        init_api_state(config_dir)
        start_api_server_thread(port=api_port)
        _log(f"API server started on port {api_port}")

    _log(f"xync daemon started (PID {os.getpid()}, interval={interval}s)")

    try:
        while running[0]:
            cfg = load_config(config_dir)
            cfg_dir_path = get_config_dir(config_dir)
            log_dir_base = (
                Path(cfg.global_config.log_dir)
                if cfg.global_config.log_dir
                else cfg_dir_path / "logs"
            )

            # Cron scheduling: sleep until next trigger
            if cfg.global_config.daemon_schedule:
                try:
                    from croniter import croniter  # noqa: PLC0415

                    now = datetime.now(tz=timezone.utc)
                    itr = croniter(cfg.global_config.daemon_schedule, now)
                    next_run = itr.get_next(datetime)
                    sleep_secs = max(0.0, (next_run - now).total_seconds())
                    _log(
                        f"Next cron run at {next_run.isoformat()} "
                        f"(sleeping {sleep_secs:.0f}s)"
                    )
                    _sleep_interruptible(sleep_secs, running)
                    if not running[0]:
                        break
                except (ValueError, KeyError) as exc:
                    _log(
                        f"Invalid cron expression "
                        f"'{cfg.global_config.daemon_schedule}': {exc}"
                    )
                    _sleep_interruptible(float(interval), running)
                    continue

            # Resolve targets: explicit names, or all enabled mirrors.
            if names:
                targets = [
                    cfg.mirrors[n]
                    for n in names
                    if n in cfg.mirrors and cfg.mirrors[n].enabled
                ]
            else:
                targets = [m for m in cfg.mirrors.values() if m.enabled]

            if not targets:
                _log("No enabled mirrors to sync.")
            else:
                _log(f"Starting sync cycle for {len(targets)} mirror(s).")
                run_sync_batch(
                    cfg,
                    config_dir,
                    log_dir_base,
                    targets,
                    should_stop=lambda: not running[0],
                    report=lambda mirror, result: _log(
                        f"Mirror {mirror.name}: {result.status.value} "
                        f"({result.duration_seconds:.1f}s)"
                    ),
                )

            # Interval sleep (only when cron is not configured)
            if not cfg.global_config.daemon_schedule:
                _sleep_interruptible(float(interval), running)

    finally:
        pid_file.unlink(missing_ok=True)
        _log("xync daemon stopped.")
