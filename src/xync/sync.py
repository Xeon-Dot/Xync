"""Mirror synchronization engine for xync."""

from __future__ import annotations

import os
import re
import shutil
import subprocess

try:
    import fcntl
except ImportError:  # non-POSIX (e.g. Windows): advisory locking unavailable
    fcntl = None  # type: ignore[assignment]

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from xync import notify
from xync.config import load_config
from xync.models import Mirror, MirrorType, SyncStatus, xyncConfig
from xync.utils import get_directory_size, record_sync_result

# Matches rsync --info=progress2 lines: "to-chk=<remaining>/<total>"
_RSYNC_TOCHK_RE = re.compile(r"to-chk=(\d+)/(\d+)")


@dataclass
class SyncResult:
    """Result of a single mirror sync run."""

    mirror_name: str
    status: SyncStatus
    duration_seconds: float = 0.0
    log_path: Optional[Path] = None
    error: Optional[str] = None
    size_bytes: Optional[int] = None


# ---------------------------------------------------------------------------
# Lock helpers
# ---------------------------------------------------------------------------


# Open file descriptors for locks held by this process, keyed by lock path.
_held_locks: dict[str, int] = {}


def _get_lock_path(log_dir: Path, mirror_name: str) -> Path:
    lock_dir = log_dir.parent / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    return lock_dir / f"{mirror_name}.lock"


def acquire_lock(lock_path: Path) -> bool:
    """Acquire an exclusive ``flock`` on *lock_path*.

    Returns *True* if the lock was acquired, *False* if it is already held.
    ``flock`` is released automatically by the kernel if the holding process
    exits or crashes, so no stale-lock detection is required.  On non-POSIX
    platforms without ``fcntl`` this always succeeds (no locking).
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if fcntl is None:
        lock_path.touch(exist_ok=True)
        return True
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return False
    _held_locks[str(lock_path)] = fd
    return True


def release_lock(lock_path: Path) -> None:
    """Release a lock acquired by :func:`acquire_lock`."""
    if fcntl is None:
        return
    fd = _held_locks.pop(str(lock_path), None)
    if fd is None:
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


# ---------------------------------------------------------------------------
# Main sync routine
# ---------------------------------------------------------------------------


def sync_mirror(
    mirror: Mirror,
    log_dir: Path,
    verbose: bool = False,
    on_progress: Optional[Callable[[int], None]] = None,
) -> SyncResult:
    """Run a sync for the given mirror and return a :class:`SyncResult`.

    Args:
        mirror: The mirror configuration to sync.
        log_dir: Directory where log files are written.
        verbose: If *True*, print subprocess output to console.
        on_progress: Optional callback invoked with an integer 0–100 each time
            a new 10 % progress milestone is reached (rsync only).  The callback
            is called with ``0`` immediately before the process starts and with
            ``100`` when the file-transfer loop completes.

    Returns:
        A :class:`SyncResult` describing the outcome.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = log_dir / f"{mirror.name}-{timestamp}.log"
    lock_path = _get_lock_path(log_dir, mirror.name)

    if not acquire_lock(lock_path):
        return SyncResult(
            mirror_name=mirror.name,
            status=SyncStatus.RUNNING,
            log_path=log_path,
            error="Another sync is already running (lock held)",
        )

    # Late import to avoid circular dependency at module load time.
    from xync import api as _api  # noqa: PLC0415

    _api.set_current_mirror(mirror.name)
    _api.set_sync_status(mirror.name, SyncStatus.RUNNING)

    try:
        try:
            cmd = _build_command(mirror)
        except FileNotFoundError as exc:
            return SyncResult(
                mirror_name=mirror.name,
                status=SyncStatus.FAILED,
                log_path=log_path,
                error=str(exc),
            )

        Path(mirror.local_path).mkdir(parents=True, exist_ok=True)

        # Inject --info=progress2 for rsync when a progress callback is supplied so
        # that we can parse "to-chk=X/Y" lines from the output stream.
        track_progress = (
            on_progress is not None and mirror.mirror_type == MirrorType.RSYNC
        )
        if track_progress:
            cmd = _inject_rsync_progress_flag(cmd)

        start = datetime.now(tz=timezone.utc)
        error_msg: Optional[str] = None

        try:
            with log_path.open("w", encoding="utf-8") as log_fh:
                log_fh.write(f"# xync log — {mirror.name}\n")
                log_fh.write(f"# Started: {start.isoformat()}\n")
                log_fh.write(f"# Command: {' '.join(cmd)}\n\n")

                if track_progress:
                    returncode = _run_with_progress(cmd, log_fh, on_progress, verbose)  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]
                else:
                    returncode = _run_without_progress(cmd, log_fh, verbose)

            end = datetime.now(tz=timezone.utc)
            duration = (end - start).total_seconds()

            if returncode == 0:
                status = SyncStatus.SUCCESS
            else:
                status = SyncStatus.FAILED
                error_msg = f"Process exited with code {returncode}"
        except FileNotFoundError as exc:
            end = datetime.now(tz=timezone.utc)
            duration = (end - start).total_seconds()
            status = SyncStatus.FAILED
            error_msg = f"Command not found: {exc}"
            with log_path.open("a", encoding="utf-8") as log_fh:
                log_fh.write(f"\n# ERROR: {error_msg}\n")
        except Exception as exc:  # noqa: BLE001  # safety net for unexpected subprocess errors
            end = datetime.now(tz=timezone.utc)
            duration = (end - start).total_seconds()
            status = SyncStatus.FAILED
            error_msg = str(exc)
            with log_path.open("a", encoding="utf-8") as log_fh:
                log_fh.write(f"\n# ERROR: {error_msg}\n")

        with log_path.open("a", encoding="utf-8") as log_fh:
            log_fh.write(
                f"\n# Finished: {end.isoformat()}  Duration: {duration:.1f}s  Status: {status.value}\n"  # noqa: E501
            )

        size_bytes = None
        if status == SyncStatus.SUCCESS:
            size_bytes = get_directory_size(mirror.local_path)

        _api.set_sync_status(mirror.name, status)
        if _api.get_current_mirror() == mirror.name:
            _api.set_current_mirror(None)

        return SyncResult(
            mirror_name=mirror.name,
            status=status,
            duration_seconds=duration,
            log_path=log_path,
            error=error_msg,
            size_bytes=size_bytes,
        )
    finally:
        release_lock(lock_path)


# ---------------------------------------------------------------------------
# Batch runner (shared by the CLI and the daemon loop)
# ---------------------------------------------------------------------------


def run_sync_batch(
    cfg: xyncConfig,
    config_dir: Optional[Path],
    log_dir_base: Path,
    targets: list[Mirror],
    verbose: bool = False,
    should_stop: Optional[Callable[[], bool]] = None,
    report: Optional[Callable[[Mirror, SyncResult], None]] = None,
) -> bool:
    """Sync all *targets*, fire notifications and record results.

    Args:
        cfg: Loaded configuration (used for parallelism and notify flags).
        config_dir: Configuration directory, for reloading before each save.
        log_dir_base: Base directory for per-mirror sync logs.
        targets: Mirrors to sync.
        verbose: If *True*, print subprocess output to console.
        should_stop: Polled between sequential syncs; abort the batch when True.
        report: Optional callback for each finished ``(mirror, result)`` pair.

    Returns:
        ``True`` when at least one mirror failed.
    """
    gc = cfg.global_config

    for mirror in targets:
        notify.notify_sync_start(gc, mirror.name)

    def _sync_one(mirror: Mirror) -> tuple[Mirror, SyncResult]:
        log_dir = log_dir_base / mirror.name
        on_progress = None
        if gc.telegram.notify_on_progress or gc.discord.notify_on_progress:
            on_progress = notify.make_progress_callback(gc, mirror.name)
        result = sync_mirror(mirror, log_dir, verbose=verbose, on_progress=on_progress)
        return mirror, result

    completed: list[tuple[Mirror, SyncResult]] = []
    if gc.parallel_jobs > 1 and len(targets) > 1:
        with ThreadPoolExecutor(max_workers=gc.parallel_jobs) as executor:
            futures = [executor.submit(_sync_one, m) for m in targets]
            for future in as_completed(futures):
                completed.append(future.result())
    else:
        for mirror in targets:
            if should_stop and should_stop():
                break
            completed.append(_sync_one(mirror))

    any_failure = False
    for mirror, result in completed:
        # Reload config before saving to avoid clobbering concurrent edits.
        fresh = load_config(config_dir)
        record_sync_result(fresh, config_dir, mirror, result)
        notify.notify_sync_result(
            fresh.global_config,
            mirror.name,
            result.status,
            result.duration_seconds,
            result.error,
        )
        notify.notify_disk_warning(fresh.global_config, mirror)
        purge_old_logs(
            log_dir_base / mirror.name,
            mirror.name,
            fresh.global_config.max_log_files,
        )
        if report:
            report(mirror, result)
        if result.error:
            any_failure = True
    return any_failure


# ---------------------------------------------------------------------------
# Diff (dry-run) helper
# ---------------------------------------------------------------------------


def diff_mirror(mirror: Mirror) -> str:
    """Run an rsync dry-run with itemized changes and return the output.

    Raises:
        ValueError: If the mirror type is not rsync.
        FileNotFoundError: If ``rsync`` is not installed.
    """
    if mirror.mirror_type != MirrorType.RSYNC:
        raise ValueError("diff is only supported for rsync mirrors")
    if not shutil.which("rsync"):
        raise FileNotFoundError("rsync is not installed or not on PATH")

    cmd = ["rsync", "--dry-run", "--itemize-changes"] + list(mirror.rsync_options)
    if mirror.bandwidth_limit:
        cmd += [f"--bwlimit={mirror.bandwidth_limit}"]
    cmd += [mirror.url.rstrip("/") + "/", mirror.local_path.rstrip("/") + "/"]

    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return proc.stdout + proc.stderr


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _inject_rsync_progress_flag(cmd: list[str]) -> list[str]:
    """Return a copy of *cmd* with ``--info=progress2`` inserted after ``rsync``."""
    if "--info=progress2" in cmd or "--progress" in cmd:
        return cmd
    return [cmd[0], "--info=progress2"] + cmd[1:]


def _run_without_progress(
    cmd: list[str],
    log_fh,
    verbose: bool,
) -> int:
    """Run *cmd* as a subprocess, writing output to *log_fh* and optionally to console.

    Returns the process exit code.
    """
    if verbose:
        with subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        ) as proc:
            for line in proc.stdout:  # type: ignore[union-attr]  # ty:ignore[not-iterable]
                log_fh.write(line)
                print(line, end="")
        return proc.returncode
    else:
        proc = subprocess.run(
            cmd,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        return proc.returncode


def _run_with_progress(
    cmd: list[str],
    log_fh,
    on_progress: Callable[[int], None],
    verbose: bool = False,
) -> int:
    """Run *cmd* as a subprocess, streaming stdout line-by-line.

    Parses rsync ``to-chk=X/Y`` progress markers, fires *on_progress* at each
    new 10 % milestone, and writes all output to *log_fh*.  Returns the process
    exit code.
    """
    last_milestone = -1

    with subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    ) as proc:
        for line in proc.stdout:  # type: ignore[union-attr]  # ty:ignore[not-iterable]
            log_fh.write(line)
            if verbose:
                print(line, end="")

            match = _RSYNC_TOCHK_RE.search(line)
            if match:
                remaining = int(match.group(1))
                total = int(match.group(2))
                if total > 0:
                    pct = int((total - remaining) / total * 100)
                    milestone = (pct // 10) * 10
                    if milestone > last_milestone:
                        last_milestone = milestone
                        on_progress(milestone)

    return proc.returncode


def _build_command(mirror: Mirror, check_tools: bool = True) -> list[str]:
    """Build the shell command list for syncing a mirror."""
    if mirror.mirror_type == MirrorType.RSYNC:
        return _build_rsync_command(mirror, check_tools=check_tools)
    if mirror.mirror_type in (MirrorType.HTTP, MirrorType.FTP):
        return _build_wget_command(mirror, check_tools=check_tools)
    raise ValueError(f"Unsupported mirror type: {mirror.mirror_type}")


def _build_rsync_command(mirror: Mirror, check_tools: bool = True) -> list[str]:
    """Build an rsync command."""
    if check_tools and not shutil.which("rsync"):
        raise FileNotFoundError("rsync is not installed or not on PATH")
    cmd = ["rsync"] + list(mirror.rsync_options)
    if mirror.bandwidth_limit:
        cmd += [f"--bwlimit={mirror.bandwidth_limit}"]
    cmd += [mirror.url.rstrip("/") + "/", mirror.local_path.rstrip("/") + "/"]
    return cmd


def _build_wget_command(mirror: Mirror, check_tools: bool = True) -> list[str]:
    """Build a wget mirror command for HTTP/FTP mirrors."""
    if check_tools and not shutil.which("wget"):
        raise FileNotFoundError("wget is not installed or not on PATH")
    cmd = [
        "wget",
        "--mirror",
        "--no-host-directories",
        "--directory-prefix",
        mirror.local_path,
    ] + list(mirror.http_options)
    cmd.append(mirror.url)
    return cmd


def purge_old_logs(log_dir: Path, mirror_name: str, max_files: int) -> int:
    """Remove old log files, keeping at most *max_files* for a mirror.

    Returns the number of files removed.
    """
    logs = sorted(log_dir.glob(f"{mirror_name}-*.log"))
    to_remove = logs[: max(0, len(logs) - max_files)]
    for f in to_remove:
        f.unlink()
    return len(to_remove)
